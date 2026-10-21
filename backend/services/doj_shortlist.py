"""
DOJ shortlist: the leads most likely to earn a Criminal Tip Rewards award,
ordered by how provable they are.

DOJ pays only when a tip leads to unsealed criminal charges, so the order is:

  tier 1  Worked cases: confirmed fraud, or already reported to OIG / an MFCU,
          and not yet sent to DOJ. A human has already judged these.
  tier 2  Per-se findings: billing while OIG-excluded, after a Medicare
          revocation, or under a deactivated NPI. Facts a prosecutor can check
          in minutes. Recovery leads (all billing BEFORE the exclusion) are left
          out: nothing was billed while barred.
  tier 3  Statistical Brain leads in DOJ's priority areas (hospice, home
          health, day care, special services).

Inside a tier, DOJ priority areas come first, then the dollar figure.

Two filters apply to every tier:
  * Leads already logged with DOJ, dismissed (judged not fraud) or archived
    are dropped.
  * The general federal limitation period is 5 years (18 U.S.C. 3282), so a
    lead whose most recent billing is older than that is dropped. DOJ decides
    timeliness; this keeps clearly stale leads off the list.
"""
from __future__ import annotations

import datetime as _dt

LIMITATION_YEARS = 5

_PERSE_KIND_ORDER = {
    "active_exclusion": 0,
    "medicare_revoked_billing": 1,
    "deactivated_billing": 2,
    "deactivated_window": 3,
}
_PERSE_REASON = {
    "active_exclusion": "Billed Medicaid while on the OIG exclusion list",
    "medicare_revoked_billing": "Billed Medicaid after Medicare revoked the provider",
    "deactivated_billing": "Billed Medicaid under a deactivated NPI",
    "deactivated_window": "Billed Medicaid while the NPI was deactivated",
}
_WORKED_REASON = {
    "confirmed": "You confirmed this as fraud",
    "tip_filed": "You reported this to HHS-OIG",
    "referred": "You referred this to the state MFCU",
}
_DROP_STATUSES = {"doj_filed", "dismissed", "archived"}


def _ym_int(s: str | None) -> int | None:
    s = (s or "").strip().replace("-", "")
    return int(s[:6]) if len(s) >= 6 and s[:6].isdigit() else None


def cutoff_month(today: _dt.date | None = None) -> int:
    """First YYYYMM still inside the limitation period."""
    today = today or _dt.date.today()
    return (today.year - LIMITATION_YEARS) * 100 + today.month


def build_shortlist(today: _dt.date | None = None) -> dict:
    from core import perse_store
    from core.oig_tips_store import filed_npis
    from core.review_store import get_queue_statuses, get_review_queue
    from core.store import get_provider_by_npi
    from services.doj_filing_guide import doj_priority
    from services.fraud_brain import get_top_frauds

    cutoff = cutoff_month(today)
    doj_filed = filed_npis("doj")
    seen: set[str] = set()
    rows: list[dict] = []
    dropped = {"too_old": 0, "already_doj": 0, "closed": 0}

    def _provider(npi: str) -> dict:
        return get_provider_by_npi(npi) or {}

    def _add(tier: int, npi: str, base: dict, reason: str, amount: float,
             amount_label: str, last_month: str | None, statuses: dict,
             extra: dict | None = None) -> None:
        if npi in seen:
            return
        status = statuses.get(npi)
        if npi in doj_filed or status == "doj_filed":
            dropped["already_doj"] += 1
            return
        if status in _DROP_STATUSES:
            dropped["closed"] += 1
            return
        lm = _ym_int(last_month)
        if lm is None or lm < cutoff:
            dropped["too_old"] += 1
            return
        p = _provider(npi)
        specialty = base.get("specialty") or p.get("specialty") or ""
        seen.add(npi)
        rows.append({
            "npi": npi,
            "tier": tier,
            "provider_name": base.get("provider_name") or p.get("provider_name")
                             or (p.get("nppes") or {}).get("name", ""),
            "state": base.get("state") or p.get("state") or "",
            "specialty": specialty,
            "reason": reason,
            "amount": round(float(amount or 0), 2),
            "amount_label": amount_label,
            "last_month": last_month,
            "doj_priority_area": doj_priority(specialty)["area"] or None,
            "queue_status": status,
            "caveat": base.get("caveat") or "",
            **(extra or {}),
        })

    # Tier 1: worked cases not yet sent to DOJ.
    worked = [i for i in get_review_queue() if i.get("queue_status") in _WORKED_REASON]
    statuses = get_queue_statuses([i["npi"] for i in worked])
    for item in worked:
        npi = item["npi"]
        p = _provider(npi)
        _add(1, npi, {**item, "specialty": p.get("specialty")},
             _WORKED_REASON[item["queue_status"]],
             item.get("total_paid") or p.get("total_paid") or 0, "Total Medicaid paid",
             p.get("last_month"), statuses)

    # Tier 2: per-se findings.
    perse = [r for r in perse_store.list_leads(limit=100_000)["leads"]
             if r.get("kind") in _PERSE_KIND_ORDER]
    statuses = get_queue_statuses([r["npi"] for r in perse])
    for r in perse:
        barred = (r.get("paid_after_exclusion") or r.get("paid_after_revocation")
                  or r.get("paid_after_deactivation") or r.get("paid_during_deactivation") or 0)
        _add(2, r["npi"], r, _PERSE_REASON[r["kind"]], barred, "Paid while barred",
             r.get("last_month"), statuses, {"kind": r["kind"]})

    # Tier 3: statistical Brain leads in DOJ priority areas.
    brain = get_top_frauds(25, False, True).get("top", [])
    statuses = get_queue_statuses([e["npi"] for e in brain])
    for e in brain:
        _add(3, e["npi"], e, f"Fraud Brain rank #{e.get('brain_rank', '?')} "
             f"(score {e.get('brain_score', 0):.0f})",
             e.get("total_paid") or 0, "Total Medicaid paid",
             e.get("last_active_month"), statuses, {"brain_rank": e.get("brain_rank")})

    def _key(r: dict):
        return (r["tier"], r["doj_priority_area"] is None,
                _PERSE_KIND_ORDER.get(r.get("kind", ""), 0),
                r.get("brain_rank") or 0, -r["amount"])

    rows.sort(key=_key)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    by_tier = {t: sum(1 for r in rows if r["tier"] == t) for t in (1, 2, 3)}
    return {
        "leads": rows,
        "total": len(rows),
        "by_tier": by_tier,
        "dropped": dropped,
        "cutoff_month": f"{cutoff // 100:04d}-{cutoff % 100:02d}",
        "limitation_years": LIMITATION_YEARS,
    }
