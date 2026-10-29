"""
Per-se fraud sweep over the FULL Medicaid billing universe (~617k NPIs), not
just the ~106k providers above the $1M scan cutoff.

Why this exists
---------------
The prescan scores 106,660 providers — every NPI with $1M+ in lifetime Medicaid
payments. That is 17% of billing NPIs but 94.6% of the dollars, which is the
right trade for the 15 STATISTICAL signals: outlier detection needs peer stats,
HCPCS breakdowns and timelines, all of which are expensive, and a $40k biller is
rarely a statistical outlier worth an analyst's morning.

It is the WRONG trade for the two PER-SE signals. An OIG-excluded provider
billing Medicaid, or a CMS-deactivated NPI still collecting payments, is
provable fraud on the face of it — 42 CFR 1001.1901 and 42 USC 1320a-7b do not
have a dollar threshold. Those two checks need no peer statistics at all, only
set membership plus a billing date, so they can run over the entire universe in
one parquet scan.

Measured 2026-07-26, before this script existed: 506 OIG-excluded providers
billing $64.2M were invisible to MFI purely because each billed under $1M.

What it writes
--------------
backend/perse_leads.json — every NPI in the billing universe that is on the OIG
LEIE or carries an NPPES deactivation date, classified as:

  * active_exclusion   — billing DURING the exclusion period. Per-se fraud.
                         Carries paid_after_exclusion: the dollar figure a
                         referral actually needs.
  * recovery_lead      — all billing predates the exclusion date. Not active
                         fraud; a clawback lead. Scored lower, same as the
                         oig_excluded signal already does.
  * deactivated_billing— billing under an NPI CMS deactivated. Identity-theft /
                         unauthorized-billing lead.

Each row is stamped in_scan_cache so the UI can separate "MFI already ranks
this one" from "MFI could not see this at all until now".

Usage (from backend/):
    G:\\Python311\\python.exe -X utf8 scripts\\build_deactivations.py   # first
    G:\\Python311\\python.exe -X utf8 scripts\\build_perse_sweep.py

DEPLOY NOTE — this output is NOT picked up by a code deploy. perse_leads.json,
npi_deactivation_windows.json and npi_deactivations.json are GCS-synced state,
and main.py's lifespan DOWNLOADS them from the bucket at startup, overwriting
whatever is on disk. So:

  * Running this locally then restarting the local backend will silently revert
    npi_deactivations.json to the bucket's copy. (Observed 2026-07-26: a freshly
    built 9,313-entry file was replaced by the bucket's 1,025-entry one.)
  * Prod will keep serving the OLD sweep until these three files are uploaded:
        gsutil cp perse_leads.json npi_deactivation_windows.json \\
                  npi_deactivations.json gs://medicaid-inspector-data/
    Upload, THEN redeploy.
"""
import functools
import json
import pathlib
import re
import sys
import time

# A real NPI is 10 digits starting with 1 or 2. Two things in this data are
# neither, and both produced garbage leads before this filter existed:
#   * LEIE writes "0000000000" when it has no NPI for an excluded person. It
#     matched a same-named catch-all bucket in the billing file and surfaced a
#     phantom $4.4M "billing while excluded" lead — ranked second.
#   * The Medicaid file carries state-assigned billing IDs (e.g. "A430617100",
#     $139M) that are not NPIs at all.
_NPI_RE = re.compile(r"^[12]\d{9}$")

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

OUT = _BACKEND / "perse_leads.json"


def _ym(s) -> int | None:
    """Normalise a date to a sortable YYYYMM int. Accepts YYYYMMDD, YYYY-MM,
    and MM/DD/YYYY (NPPES deactivation dates use the last form)."""
    s = str(s or "").strip()
    if not s:
        return None
    if "/" in s:  # MM/DD/YYYY
        parts = s.split("/")
        if len(parts) == 3 and parts[2].isdigit():
            try:
                return int(parts[2]) * 100 + int(parts[0])
            except ValueError:
                return None
        return None
    digits = s.replace("-", "")
    if len(digits) >= 6 and digits[:6].isdigit():
        return int(digits[:6])
    return None


WEAK_WINDOW_GAP_DAYS = 180


def _gap_days(start: str, end: str) -> int | None:
    import datetime as _dt
    try:
        return (_dt.datetime.strptime(end, "%m/%d/%Y") - _dt.datetime.strptime(start, "%m/%d/%Y")).days
    except (TypeError, ValueError):
        return None


def _add_months(m: int, n: int) -> int:
    y, mo = divmod(m, 100)
    idx = y * 12 + (mo - 1) + n
    return (idx // 12) * 100 + idx % 12 + 1


# A state needs time to act on a Medicare revocation, so only billing from the
# second month after the effective date counts.
_REVOCATION_GRACE_MONTHS = 2
# Measured 2026-10-20: 21 of 182 revocation leads were under $1,000 after the
# revocation (one was $3) — rounding noise, not a referral.
_REVOCATION_MIN_PAID = 1_000.0


def _revocation_caveat(recs: list[dict]) -> str:
    """A revocation that rests ONLY on DME supplier standards (424.535(a)(1)) can
    cover just the supply enrollment of a practice that also bills lawfully."""
    reasons = [(r.get("reason") or "").lower() for r in recs]
    if reasons and all("dme standards" in x and "felon" not in x for x in reasons):
        return ("Medicare revoked this provider's DME supplier enrollment for failing "
                "supplier standards. Confirm the state terminated the same enrollment "
                "before filing; other services the practice bills may still be lawful.")
    if any("felon" in x for x in reasons):
        # 424.535(a)(3) revocations follow a conviction, so prosecutors already
        # know the provider. Only the billing AFTER the revocation is new.
        return ("Revoked after a felony conviction, so prosecutors already know this "
                "provider. Your tip's new fact is the Medicaid billing after the "
                "revocation; lead with that.")
    return ""


def _revocation_windows(recs: list[dict]) -> list[tuple[int, int | None]]:
    """[start, end) YYYYMM windows in which Medicaid billing is barred by a
    Medicare revocation. Billing after the re-enrollment bar expires is not
    counted — the provider may have lawfully re-enrolled."""
    out = []
    for r in recs:
        rd = _ym(r.get("revocation_date"))
        if rd is None:
            continue
        out.append((_add_months(rd, _REVOCATION_GRACE_MONTHS), _ym(r.get("reenrollment_bar_until"))))
    return out


def main() -> int:
    import duckdb
    from services import perse_rules
    from data.duckdb_client import get_parquet_path
    from core.oig_store import load_oig_from_disk, get_oig_stats
    import core.oig_store as oig_store
    import core.deactivation_store as deact_store

    started = time.time()

    # ── Reference data. A dark store here silently produces an empty sweep,
    # so fail loudly rather than writing a confidently-empty file.
    load_oig_from_disk()
    exclusions = dict(oig_store._exclusions)
    deact_store._load()
    deacts = dict(deact_store._deacts)
    # NPIs deactivated and later reactivated. Alive today, so they are NOT in
    # the deactivation store — but billing inside the closed window was still
    # unauthorized, and that is a narrower, checkable claim.
    try:
        windows = json.loads((_BACKEND / "npi_deactivation_windows.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        windows = {}
    import core.revocation_store as rev_store
    revocations = dict(rev_store.all_revocations())
    # Built by build_enrollment_leads.py from the HHS enrollment segments.
    try:
        enroll = json.loads((_BACKEND / "enrollment_leads.json").read_text(encoding="utf-8"))["leads"]
    except (OSError, ValueError, KeyError):
        enroll = {}
    try:
        npi_states = json.loads((_BACKEND / "npi_states.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        npi_states = {}
    # States whose enrollment rows carry no usable NPI (the any-state test is
    # blind there) and each lead NPI's NPPES practice state. See
    # fetch_practice_states.py and core/lead_quality.py (audit 2026-10-28).
    try:
        blind_states = json.loads((_BACKEND / "enrollment_leads.json").read_text(encoding="utf-8")).get("blind_states") or []
    except (OSError, ValueError):
        blind_states = []
    try:
        practice = json.loads((_BACKEND / "perse_practice_states.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        practice = {}
    print(f"State-terminated-but-paid leads: {len(enroll):,}  ·  NPIs with an enrolled state: {len(npi_states):,}")
    print(f"Medicare revocations: {len(revocations):,}  (built {rev_store.generated_at()})")
    print(f"OIG LEIE records: {len(exclusions):,}  (store reports "
          f"{(get_oig_stats() or {}).get('record_count')})")
    print(f"NPPES deactivations (currently dead): {len(deacts):,}")
    print(f"NPPES deactivation windows (reactivated since): {len(windows):,}")
    if not exclusions and not deacts:
        print("ERROR: both reference stores are empty — refusing to write an "
              "empty sweep. Run the OIG refresh and build_deactivations.py first.")
        return 1
    if not deacts:
        print("WARN: deactivation store is empty — the deactivated_billing "
              "portion of this sweep will be blank.")

    raw_targets = set(exclusions) | set(deacts) | set(windows) | set(revocations) | set(enroll)
    targets = {n for n in raw_targets if _NPI_RE.match(str(n))}
    dropped = len(raw_targets) - len(targets)
    print(f"target NPIs to check against billing: {len(targets):,}"
          + (f"  (dropped {dropped} non-NPI identifiers)" if dropped else ""))

    # ── Which NPIs does MFI already rank? Used only to label rows.
    try:
        slim = json.loads((_BACKEND / "prescan_slim.json").read_text(encoding="utf-8"))
        scanned = {p["npi"] for p in slim.get("providers", []) if p.get("npi")}
    except (OSError, ValueError) as e:
        print(f"WARN: could not read prescan_slim.json ({e}) — in_scan_cache "
              "will be reported as unknown for every row.")
        scanned = None
    print(f"already in scan cache: {len(scanned):,}" if scanned is not None else "")

    parquet = get_parquet_path()
    print(f"parquet: {parquet}")

    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET threads=4;")

    # Push the target list into DuckDB via CSV — the same trick
    # rebuild_prescan_bulk uses, because executemany stalls at this row count.
    tgt = _BACKEND / "_perse_targets.csv.tmp"
    with open(tgt, "w", encoding="utf-8") as f:
        f.write("npi\n")
        f.writelines(f"{n}\n" for n in targets)
    tpath = str(tgt).replace("\\", "/")
    con.execute(f"CREATE TEMP TABLE t AS SELECT npi FROM read_csv_auto('{tpath}', header=true, all_varchar=true)")

    # ── One scan: per-NPI billing totals AND the month-resolved detail needed
    # to split billing before vs. during an exclusion.
    print("scanning parquet for billing by these NPIs…")
    t0 = time.time()
    rows = con.execute(f"""
        SELECT
            p.BILLING_PROVIDER_NPI_NUM        AS npi,
            p.CLAIM_FROM_MONTH                AS month,
            SUM(p.TOTAL_PAID)                 AS paid,
            SUM(p.TOTAL_CLAIMS)               AS claims,
            SUM(p.TOTAL_UNIQUE_BENEFICIARIES) AS benes
        FROM read_parquet('{parquet}') p
        INNER JOIN t ON p.BILLING_PROVIDER_NPI_NUM = t.npi
        GROUP BY 1, 2
    """).fetchall()
    # ── v3.63.0: a second scan by SERVICING provider. An excluded person who
    # works inside someone else's practice never appears as a billing NPI, so
    # the scan above cannot see them (42 CFR 1001.1901(b) bars those payments
    # too). Drug/medication lines are summed separately for the same-name
    # caveat in services/perse_rules.servicing_finding.
    excl_ids = sorted(n for n in exclusions if _NPI_RE.match(str(n)))
    xtgt = _BACKEND / "_perse_excl.csv.tmp"
    with open(xtgt, "w", encoding="utf-8") as f:
        f.write("npi\n")
        f.writelines(f"{n}\n" for n in excl_ids)
    xpath = str(xtgt).replace("\\", "/")
    con.execute(f"CREATE TEMP TABLE x AS SELECT npi FROM read_csv_auto('{xpath}', header=true, all_varchar=true)")
    print("scanning parquet for excluded SERVICING providers…")
    t0 = time.time()
    serv_rows = con.execute(f"""
        SELECT
            p.SERVICING_PROVIDER_NPI_NUM AS snpi,
            p.BILLING_PROVIDER_NPI_NUM   AS bnpi,
            p.CLAIM_FROM_MONTH           AS month,
            SUM(p.TOTAL_PAID)            AS paid,
            SUM(CASE WHEN p.HCPCS_CODE LIKE 'J%'
                       OR p.HCPCS_CODE IN ('S5000', 'S5001', 'T1502', 'T1503')
                     THEN p.TOTAL_PAID ELSE 0 END) AS drug_paid
        FROM read_parquet('{parquet}') p
        INNER JOIN x ON p.SERVICING_PROVIDER_NPI_NUM = x.npi
        WHERE p.SERVICING_PROVIDER_NPI_NUM <> p.BILLING_PROVIDER_NPI_NUM
        GROUP BY 1, 2, 3
    """).fetchall()
    print(f"  {len(serv_rows):,} servicing npi-biller-month rows in {time.time() - t0:.0f}s")
    con.close()
    tgt.unlink(missing_ok=True)
    xtgt.unlink(missing_ok=True)
    serv_by_npi: dict[str, list] = {}
    for snpi, bnpi, month, paid, drug in serv_rows:
        serv_by_npi.setdefault(snpi, []).append((bnpi, _ym(month), float(paid or 0), float(drug or 0)))
    print(f"  {len(rows):,} npi-month rows in {time.time() - t0:.0f}s")

    # ── Fold months into per-NPI totals + the after-cutoff slice.
    agg: dict[str, dict] = {}
    for npi, month, paid, claims, benes in rows:
        m = _ym(month)
        a = agg.setdefault(npi, {
            "paid": 0.0, "claims": 0, "benes": 0,
            "first_month": None, "last_month": None, "months": [],
        })
        a["paid"] += float(paid or 0)
        a["claims"] += int(claims or 0)
        a["benes"] += int(benes or 0)
        if m is not None:
            a["months"].append((m, float(paid or 0)))
            a["first_month"] = m if a["first_month"] is None else min(a["first_month"], m)
            a["last_month"] = m if a["last_month"] is None else max(a["last_month"], m)

    print(f"  {len(agg):,} of {len(targets):,} target NPIs actually bill Medicaid")

    def _fmt(m: int | None) -> str | None:
        return f"{m // 100:04d}-{m % 100:02d}" if m else None

    leads: list[dict] = []
    for npi, a in agg.items():
        if a["paid"] <= 0:
            continue  # no money moved; nothing to refer
        base = {
            "npi": npi,
            "total_paid": round(a["paid"], 2),
            "total_claims": a["claims"],
            "total_beneficiaries": a["benes"],
            "first_month": _fmt(a["first_month"]),
            "last_month": _fmt(a["last_month"]),
            "in_scan_cache": (npi in scanned) if scanned is not None else None,
        }

        # Billing is monthly, so only months wholly AFTER a bar date count. A
        # bar that starts on the 31st must not turn that whole month's billing
        # into "paid while barred" (measured 2026-10-21: 66 of 338 dead-NPI
        # leads billed only in the deactivation month itself).
        rec = exclusions.get(npi)
        if rec:
            # v3.63.0: waiver-aware (services/perse_rules.py).
            cls = perse_rules.classify_billing_exclusion(rec, a["months"])
            active = cls["kind"] == "active_exclusion"
            leads.append({
                **base,
                **cls,
                "provider_name": rec.get("busname") or rec.get("name") or "",
                "state": rec.get("state") or "",
                "specialty": rec.get("specialty") or "",
                "exclusion_date": rec.get("excl_date"),
                "exclusion_type": rec.get("excl_type"),
                "citation": (
                    "42 CFR § 1001.1901 (payment prohibition — excluded persons); "
                    "42 U.S.C. § 1320a-7b(a) (false claims)"
                ) if active else (
                    "42 CFR § 1001.1901 (recovery of payments made to a since-excluded provider)"
                ) if cls["kind"] == "recovery_lead" else "",
            })
            continue

        revs = revocations.get(npi)
        if revs:
            wins = _revocation_windows(revs)
            after = sum(p for m, p in a["months"]
                        if any(s <= m and (e is None or m < e) for s, e in wins))
            if after >= _REVOCATION_MIN_PAID:
                first = revs[0]
                leads.append({
                    **base,
                    "kind": "medicare_revoked_billing",
                    "provider_name": first.get("name") or "",
                    "state": first.get("state") or "",
                    "specialty": first.get("provider_type") or "",
                    "revocation_date": first.get("revocation_date"),
                    "revocation_reason": first.get("reason") or "",
                    "reenrollment_bar_until": first.get("reenrollment_bar_until"),
                    "paid_after_revocation": round(after, 2),
                    "caveat": _revocation_caveat(revs),
                    "citation": (
                        "42 CFR § 455.416(c) (state Medicaid must terminate a provider "
                        "Medicare has revoked); 42 CFR § 455.436"
                    ),
                })
                continue

        el = enroll.get(npi)
        if el:
            leads.append({
                **base,
                "kind": "paid_while_terminated",
                "provider_name": "",
                "state": el.get("terminated_state") or "",
                "specialty": "",
                "enrollment_status": el.get("enrollment_status"),
                "terminated_since": el.get("terminated_since"),
                "paid_while_terminated": el.get("paid_while_terminated"),
                "months_while_terminated": el.get("months_while_terminated"),
                "reinstated_after": bool(el.get("reinstated_after")),
                "caveat": el.get("caveat") or "",
                "citation": ("42 CFR § 455.416 (termination of provider participation); "
                             "42 U.S.C. § 1320a-7b(a) (false claims)"),
            })
            continue

        dt = deacts.get(npi)
        if dt:
            dd = _ym(dt)
            after = sum(p for m, p in a["months"] if dd is not None and m > dd)
            if after <= 0:
                # Deactivated AFTER all its billing. The NPI is dead now, but
                # nothing was billed while it was dead — no per-se claim.
                continue
            leads.append({
                **base,
                "kind": "deactivated_billing",
                "provider_name": "",
                "state": "",
                "specialty": "",
                "deactivation_date": dt,
                "paid_after_deactivation": round(after, 2),
                "citation": "42 U.S.C. § 1320a-7b(a)(1) (false statements — billing under a deactivated NPI)",
            })
            continue

        win = windows.get(npi)
        if win:
            dd, rd = _ym(win[0]), _ym(win[1])
            if dd is None or rd is None or rd <= dd:
                continue
            # Whole months strictly inside the gap only. Most gaps are
            # paperwork lapses (median 40 days), and a 20-day gap spanning a
            # month boundary contains no whole month at all.
            inside = sum(p for m, p in a["months"] if dd < m < rd)
            if inside <= 0:
                continue  # billed only outside the window — the NPI was valid then
            gap = _gap_days(win[0], win[1])
            leads.append({
                **base,
                "kind": "deactivated_window",
                "provider_name": "",
                "state": "",
                "specialty": "",
                "deactivation_date": win[0],
                "reactivation_date": win[1],
                "gap_days": gap,
                # A short gap the provider closed is usually a paperwork lapse
                # (median 40 days, measured 2026-10-21) — real but weak.
                "weak": gap is None or gap < WEAK_WINDOW_GAP_DAYS,
                "paid_during_deactivation": round(inside, 2),
                "citation": "42 U.S.C. § 1320a-7b(a)(1) (false statements — billing while the NPI was deactivated)",
            })

    # ── v3.63.0: merge the servicing findings. An NPI that already has an
    # exclusion lead gets the servicing money added to it; one whose own
    # billing all predates the exclusion (recovery_lead) becomes an
    # excluded_servicing lead; one that never billed gets a new row.
    by_npi = {r["npi"]: r for r in leads}
    for snpi, srows in serv_by_npi.items():
        rec = exclusions.get(snpi)
        if not rec:
            continue
        fnd = perse_rules.servicing_finding(rec, srows)
        if not fnd:
            continue
        cur = by_npi.get(snpi)
        if cur is not None:
            extra = {k: v for k, v in fnd.items() if k not in ("kind", "citation", "caveat")}
            cur.update(extra)
            if cur["kind"] == "recovery_lead" and fnd["kind"] == "excluded_servicing":
                cur["kind"] = "excluded_servicing"
                cur["citation"] = fnd["citation"]
            if fnd["caveat"] and fnd["caveat"] not in (cur.get("caveat") or ""):
                cur["caveat"] = ((cur.get("caveat") or "") + " " + fnd["caveat"]).strip()
            continue
        months = sorted({m for _, m, _, _ in srows if m})
        row = {
            "npi": snpi,
            "total_paid": round(sum(p for _, _, p, _ in srows), 2),
            "total_claims": None,
            "total_beneficiaries": None,
            "first_month": _fmt(months[0]) if months else None,
            "last_month": fnd["last_servicing_month"],
            "in_scan_cache": (snpi in scanned) if scanned is not None else None,
            "provider_name": rec.get("busname") or rec.get("name") or "",
            "state": rec.get("state") or "",
            "specialty": rec.get("specialty") or "",
            "exclusion_date": rec.get("excl_date"),
            "exclusion_type": rec.get("excl_type"),
            **fnd,
        }
        leads.append(row)
        by_npi[snpi] = row

    # Practice state from NPPES, kept separate from `state` (which for a
    # paid_while_terminated lead is the TERMINATING state).
    for r in leads:
        ps = (practice.get(r["npi"]) or {}).get("state")
        if ps:
            r["practice_state"] = ps

    # The spend parquet has no state; fill it from Medicaid enrollment.
    for r in leads:
        if not r.get("state") and npi_states.get(r["npi"]):
            r["state"] = npi_states[r["npi"]][0]

    # Rank: active per-se fraud first, then by the dollars billed while barred.
    _ORDER = {"active_exclusion": 0, "excluded_servicing": 1, "medicare_revoked_billing": 2,
              "paid_while_terminated": 3, "deactivated_billing": 4, "deactivated_window": 5,
              "waived_exclusion": 6, "recovery_lead": 7}
    leads.sort(key=lambda r: (
        _ORDER.get(r["kind"], 9),
        -(r.get("paid_after_exclusion") or r.get("paid_as_servicing_after_exclusion")
          or r.get("paid_after_revocation")
          or r.get("paid_while_terminated")
          or r.get("paid_after_deactivation") or r.get("paid_during_deactivation") or 0),
        -r["total_paid"],
    ))

    by_kind: dict[str, dict] = {}
    for r in leads:
        k = by_kind.setdefault(r["kind"], {"count": 0, "paid": 0.0, "new": 0, "new_paid": 0.0})
        k["count"] += 1
        k["paid"] += r["total_paid"]
        if r["in_scan_cache"] is False:
            k["new"] += 1
            k["new_paid"] += r["total_paid"]

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "universe_npis": None,   # filled below
        "scanned_npis": len(scanned) if scanned is not None else None,
        "enrollment_blind_states": blind_states,
        "summary": {k: {"count": v["count"], "total_paid": round(v["paid"], 2),
                        "outside_scan_cache": v["new"],
                        "outside_scan_cache_paid": round(v["new_paid"], 2)}
                    for k, v in by_kind.items()},
        "leads": leads,
    }

    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    print()
    print(f"wrote {len(leads):,} per-se leads -> {OUT.name}  ({time.time() - started:.0f}s)")
    for kind, v in payload["summary"].items():
        print(f"  {kind:22s} {v['count']:6,}  ${v['total_paid']:>16,.0f}   "
              f"of which OUTSIDE the scan cache: {v['outside_scan_cache']:,} "
              f"(${v['outside_scan_cache_paid']:,.0f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
