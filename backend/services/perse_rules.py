"""
Pure classification rules for the per-se sweep (scripts/build_perse_sweep.py).

Kept apart from the script so they can be tested without DuckDB or the parquet.

Added 2026-10-29 (v3.63.0) after an independent re-run of the exclusion checks
against the raw public files found three gaps:

* WAIVERS. The LEIE carries WAIVERDATE / WVRSTATE. A waiver lets a state keep
  paying an excluded provider (usually the only specialist in a county). MFI
  never read either column, so a waived provider looked like "billing while
  excluded". A rescinded waiver shows WAIVERDATE 0 but keeps WVRSTATE (Mohamed
  Aswad, NM: waived 2016-2022, rescinded 2022-08-22, all billing inside it).
* SERVICING. The HHS file records the SERVICING provider too. MFI only checked
  the billing NPI, so an excluded doctor working inside someone else's clinic
  was invisible. 42 CFR 1001.1901(b) bars payment for items or services an
  excluded person furnishes or orders, employed or not (Roozbeh Badii on
  DoctorNow claims, 2020-10..2021-12).
* SERVICING FALSE HITS seen on the same day, turned into caveats rather than
  silent drops because neither can be settled from public data:
    - a same-name mix-up: a biller put an excluded aide's NPI on nurse
      medication claims, then switched to a same-named LPN's NPI the month the
      exclusion appeared (Ebony R. Gibson / Ebony Lynn Gibson at BrightView);
    - a successor owner: a county kept using a sold hospital's old NPI while
      the new owner billed the same codes under its own (Healthsmart Pacific /
      College Medical Center, Long Beach).
"""
from __future__ import annotations

import re

WAIVER_CAVEAT = ("OIG waived this exclusion for {state}. A waiver lets that state keep paying "
                 "the provider. Check the waiver dates on oig.hhs.gov/exclusions/waivers.asp "
                 "before treating any payment as barred.")
SAME_NAME_CAVEAT = ("Check the biller did not mean a same-name provider: billers sometimes put "
                    "the wrong person's NPI on claims.")
SAME_NAME_STRONG = ("The excluded person is listed as {kind}, but most of these payments are for "
                    "drugs or medication work a licensed nurse or doctor does. That points to a "
                    "same-name mix-up at the biller. Check the biller's staff before filing.")
SUCCESSOR_CAVEAT = ("An excluded facility's old NPI. Check whether a new owner at the same "
                    "address took over and kept using the old number.")
SERVICING_CITATION = ("42 CFR 1001.1901(b) (no payment for items or services furnished or "
                      "ordered by an excluded person, including as an employee or contractor)")

# LEIE specialty / general words for people who cannot lawfully do clinical
# drug work on their own.
_UNLICENSED = re.compile(r"\b(AIDE|ATTENDANT|PERSONAL CARE|HOME HEALTH AIDE|CAREGIVER|"
                         r"HOUSEKEEP|COMPANION|DRIVER|TRANSPORT)\b")


def ym(s) -> int | None:
    """YYYYMMDD / YYYY-MM / MM/DD/YYYY -> sortable YYYYMM int."""
    s = str(s or "").strip()
    if not s:
        return None
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and parts[2].isdigit() and parts[0].isdigit():
            return int(parts[2]) * 100 + int(parts[0])
        return None
    digits = s.replace("-", "")
    if len(digits) >= 6 and digits[:6].isdigit():
        return int(digits[:6])
    return None


def fmt_ym(m: int | None) -> str | None:
    return f"{m // 100:04d}-{m % 100:02d}" if m else None


def waiver_state(rec: dict) -> str | None:
    """The state an OIG waiver covers, or None. A rescinded waiver keeps its
    state code with waiver date 0, so the state column alone counts. A waiver
    date with no state still counts ('unknown state')."""
    st = str(rec.get("waiver_state") or "").strip()
    wd = str(rec.get("waiver_date") or "").strip()
    if st:
        return st
    if wd and wd != "0":
        return "an unknown state"
    return None


def is_entity(rec: dict) -> bool:
    return bool(str(rec.get("busname") or "").strip())


def classify_billing_exclusion(rec: dict, months: list[tuple[int, float]]) -> dict:
    """Kind + amount fields for an excluded NPI that BILLS Medicaid.

    months: [(YYYYMM, paid)]. Only whole months strictly after the exclusion
    month count (a bar on the 31st must not taint that whole month)."""
    ed = ym(rec.get("excl_date"))
    after = sum(p for m, p in months if ed is not None and m > ed)
    out = {"paid_after_exclusion": round(after, 2)}
    ws = waiver_state(rec)
    if ws and after > 0:
        out.update(kind="waived_exclusion", waiver_state=ws,
                   caveat=WAIVER_CAVEAT.format(state=ws))
        return out
    out["kind"] = "active_exclusion" if (ed is not None and after > 0) else "recovery_lead"
    return out


def servicing_finding(rec: dict, rows: list[tuple[str, int, float, float]],
                      min_paid: float = 0.0) -> dict | None:
    """The excluded-servicing finding for one excluded NPI, or None.

    rows: [(billing_npi, YYYYMM, paid, drug_paid)] for claims where this NPI is
    the SERVICING provider and someone else billed. Returns the payments in
    whole months after the exclusion, split by biller, with caveats. A waiver
    turns it into kind 'waived_exclusion' (not a DOJ lead)."""
    ed = ym(rec.get("excl_date"))
    if ed is None:
        return None
    by_biller: dict[str, float] = {}
    months: set[int] = set()
    paid = drug = 0.0
    last = None
    for bnpi, m, p, d in rows:
        if m is None or m <= ed or not p:
            continue
        by_biller[bnpi] = by_biller.get(bnpi, 0.0) + float(p)
        paid += float(p)
        drug += float(d or 0)
        if p > 0:
            months.add(m)
        last = m if last is None else max(last, m)
    if paid <= max(0.0, min_paid):
        return None
    billers = [{"npi": b, "paid": round(v, 2)}
               for b, v in sorted(by_biller.items(), key=lambda kv: -kv[1])]
    caveats = []
    kind = "excluded_servicing"
    ws = waiver_state(rec)
    if ws:
        kind = "waived_exclusion"
        caveats.append(WAIVER_CAVEAT.format(state=ws))
    if is_entity(rec):
        caveats.append(SUCCESSOR_CAVEAT)
    else:
        what = f"{rec.get('general') or ''} {rec.get('specialty') or ''}".upper()
        if _UNLICENSED.search(what) and drug >= 0.5 * paid:
            caveats.append(SAME_NAME_STRONG.format(kind=(rec.get("specialty") or "an aide").lower()))
        else:
            caveats.append(SAME_NAME_CAVEAT)
    return {
        "kind": kind,
        "paid_as_servicing_after_exclusion": round(paid, 2),
        "servicing_months_after_exclusion": len(months),
        "first_servicing_month_after": fmt_ym(min(months)) if months else None,
        "last_servicing_month": fmt_ym(last),
        "drug_share": round(drug / paid, 3) if paid else 0.0,
        "billers": billers[:10],
        "top_biller_npi": billers[0]["npi"],
        "caveat": " ".join(caveats),
        "waiver_state": ws,
        "citation": SERVICING_CITATION,
    }
