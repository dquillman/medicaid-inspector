"""
Per-se fraud sweep results — read-only lookup over backend/perse_leads.json,
built by scripts/build_perse_sweep.py.

Why this store exists separately from the prescan cache: the prescan only scores
NPIs with $1M+ in lifetime Medicaid payments (106,660 of 617,503 billing NPIs —
94.6% of the dollars). That cutoff is correct for the statistical signals, which
need peer stats to mean anything, and wrong for the per-se ones. An OIG-excluded
provider billing while barred, or a deactivated NPI still collecting, is provable
on the face of it at ANY dollar amount — 42 CFR 1001.1901 has no threshold.

This store holds the sweep of those two checks across the FULL universe, so
leads under the scan cutoff are visible. Measured 2026-07-26: 845 of 1,081 leads
sit outside the scan cache, i.e. MFI could not see them at all before.

Lazy-loaded and GCS-synced, mirroring deactivation_store.
"""
import json
import logging
import pathlib
import threading

log = logging.getLogger(__name__)

_PATH = pathlib.Path(__file__).parent.parent / "perse_leads.json"
_lock = threading.Lock()
_payload: dict = {}
_by_npi: dict[str, dict] = {}
_loaded = False

# Ranked worst-first. active_exclusion is billing DURING an exclusion (per-se
# fraud); recovery_lead is billing that predates it (a clawback, not active
# fraud) and must never be presented as the former.
KINDS = ("active_exclusion", "medicare_revoked_billing", "paid_while_terminated",
         "deactivated_billing", "deactivated_window", "recovery_lead")

KIND_LABELS = {
    "active_exclusion": "Billing while excluded",
    "medicare_revoked_billing": "Billing after Medicare revocation",
    "paid_while_terminated": "Paid after state terminated enrollment",
    "deactivated_billing": "Billing under a dead NPI",
    "deactivated_window": "Billed while NPI was deactivated",
    "recovery_lead": "Recovery lead (excluded later)",
}


def _load() -> None:
    global _payload, _by_npi, _loaded
    with _lock:
        if _loaded:
            return
        # Reset first. Without this, a reload() after the file goes away (or
        # after a failed parse) kept serving the PREVIOUS sweep — the store
        # would report leads it could no longer justify.
        _payload = {}
        _by_npi = {}
        try:
            if _PATH.exists():
                _payload = json.loads(_PATH.read_text(encoding="utf-8"))
                _by_npi = {r["npi"]: r for r in _payload.get("leads", []) if r.get("npi")}
            _loaded = True
            log.info("[perse] loaded %d per-se leads", len(_by_npi))
        except Exception as e:  # noqa: BLE001
            log.warning("[perse] load failed: %s", e)
            _payload = {}
            _by_npi = {}
            _loaded = True


def reload() -> None:
    """Drop the cache so the next read picks up a freshly built sweep."""
    global _loaded
    with _lock:
        _loaded = False
    _load()


def _scanned_npis() -> set[str]:
    """NPIs in the scan cache RIGHT NOW.

    `in_scan_cache` inside perse_leads.json is a BUILD-TIME snapshot, and it
    goes stale the moment those providers are scanned. It did: after the
    2026-07-27 top-up the board still announced "379 leads the risk model
    can't see" and the Excluded table still badged them UNSCANNED, while all
    379 were sitting in the cache with risk scores. Overlaying the live set
    means the file can age without the UI ever lying about it.
    """
    try:
        from core.store import get_prescanned
        return {p.get("npi") for p in get_prescanned() if p.get("npi")}
    except Exception:  # noqa: BLE001 — never let this break a lead listing
        return set()


def _with_live_scan_state(rows: list[dict], scanned: set[str]) -> list[dict]:
    """Copy each row with in_scan_cache resolved against the live cache.
    Falls back to the stored value when the cache is unavailable (empty set)."""
    if not scanned:
        return rows
    return [{**r, "in_scan_cache": r.get("npi") in scanned} for r in rows]


def blind_states() -> list[str]:
    """States whose enrollment rows carry no usable NPIs (see lead_quality)."""
    if not _loaded:
        _load()
    return list(_payload.get("enrollment_blind_states") or [])


def get_lead(npi: str) -> dict | None:
    """The per-se lead for this NPI, or None. Used to badge a provider page."""
    if not _loaded:
        _load()
    row = _by_npi.get(npi)
    if row is None:
        return None
    scanned = _scanned_npis()
    return {**row, "in_scan_cache": npi in scanned} if scanned else row


def list_leads(kind: str | None = None, outside_scan_cache: bool | None = None,
               limit: int = 200, offset: int = 0) -> dict:
    """Filtered slice of the sweep, already ranked worst-first by the builder."""
    if not _loaded:
        _load()
    rows = _with_live_scan_state(_payload.get("leads", []), _scanned_npis())
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if outside_scan_cache is not None:
        rows = [r for r in rows if (r.get("in_scan_cache") is False) == outside_scan_cache]
    total = len(rows)
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "leads": rows[offset:offset + limit],
    }


def get_summary() -> dict:
    """Counts + dollars by kind, and how stale the sweep is.

    by_kind is RECOMPUTED from the live scan state rather than read from the
    file's stored summary block — that block carries the same build-time
    in_scan_cache the rows do, so it drifts the same way.
    """
    if not _loaded:
        _load()
    scanned = _scanned_npis()
    by_kind: dict[str, dict] = {}
    for r in _with_live_scan_state(_payload.get("leads", []), scanned):
        k = by_kind.setdefault(r.get("kind", "unknown"), {
            "count": 0, "total_paid": 0.0, "weak": 0,
            "outside_scan_cache": 0, "outside_scan_cache_paid": 0.0})
        paid = float(r.get("total_paid") or 0)
        k["count"] += 1
        if r.get("weak"):
            k["weak"] += 1
        k["total_paid"] += paid
        if r.get("in_scan_cache") is False:
            k["outside_scan_cache"] += 1
            k["outside_scan_cache_paid"] += paid
    for k in by_kind.values():
        k["total_paid"] = round(k["total_paid"], 2)
        k["outside_scan_cache_paid"] = round(k["outside_scan_cache_paid"], 2)
    return {
        "generated_at": _payload.get("generated_at"),
        "scanned_npis": len(scanned) or _payload.get("scanned_npis"),
        "total_leads": len(_by_npi),
        "by_kind": by_kind or _payload.get("summary", {}),
        "available": bool(_by_npi),
    }


def describe_finding(lead: dict | None) -> dict | None:
    """Plain report sentences for a per-se lead, for the OIG/MFCU/DOJ narrative.

    Before this existed the referral generator never read the sweep, so a tip
    on a Medicare-revoked provider listed only statistical signals and left out
    the one fact that makes it provable (Soft Touch Hospice, 2026-10-22), and the
    DOJ chat picked up total Medicaid paid instead of the amount paid while barred.
    """
    if not lead:
        return None
    kind = lead.get("kind")
    total = float(lead.get("total_paid") or 0)
    if kind == "active_exclusion":
        amt = float(lead.get("paid_after_exclusion") or 0)
        when = lead.get("exclusion_date") or "?"
        head = (f"The provider is on the HHS-OIG exclusion list (LEIE, excluded {when}) and "
                f"Medicaid still paid it ${amt:,.0f} for services after the exclusion.")
        label = "paid after the OIG exclusion"
    elif kind == "medicare_revoked_billing":
        amt = float(lead.get("paid_after_revocation") or 0)
        reason = (lead.get("revocation_reason") or "").strip()
        head = (f"Medicare revoked this provider's enrollment effective "
                f"{lead.get('revocation_date') or '?'}"
                + (f" (reason: {reason})" if reason else "")
                + f". Medicaid still paid it ${amt:,.0f} for services from the second month "
                  "after the revocation onward. A state must terminate a provider Medicare has "
                  "revoked (42 CFR 455.416(c)).")
        label = "paid after Medicare revoked the provider"
    elif kind == "paid_while_terminated":
        amt = float(lead.get("paid_while_terminated") or 0)
        status = (lead.get("enrollment_status") or "").replace("TERM - ", "").strip().lower()
        head = (f"The state Medicaid program terminated this provider's enrollment for cause "
                f"({status}) effective {lead.get('terminated_since') or '?'}, and Medicaid still "
                f"paid it ${amt:,.0f} for {lead.get('months_while_terminated') or '?'} whole "
                "months in which it had no active Medicaid enrollment in any state.")
        label = "paid after the state terminated its enrollment"
    elif kind == "deactivated_billing":
        amt = float(lead.get("paid_after_deactivation") or 0)
        head = (f"The provider's NPI was deactivated in NPPES on "
                f"{lead.get('deactivation_date') or '?'}, and Medicaid paid ${amt:,.0f} for "
                "services billed under that NPI in later months.")
        label = "paid under a deactivated NPI"
    elif kind == "deactivated_window":
        amt = float(lead.get("paid_during_deactivation") or 0)
        head = (f"The provider's NPI was deactivated from {lead.get('deactivation_date') or '?'} "
                f"to {lead.get('reactivation_date') or '?'}, and Medicaid paid ${amt:,.0f} for "
                "services in whole months inside that gap. The NPI was later reactivated.")
        label = "paid while the NPI was deactivated"
    elif kind == "recovery_lead":
        when = lead.get("exclusion_date") or "?"
        return {
            "headline": (f"The provider was later excluded by HHS-OIG (LEIE, {when}). All Medicaid "
                         "billing in the public data predates the exclusion, so this is a "
                         "possible recovery matter, not billing while excluded."),
            "amount": 0.0, "amount_label": "", "total_paid": total,
            "citation": lead.get("citation") or "", "caveat": lead.get("caveat") or "",
        }
    else:
        return None
    return {
        "headline": head,
        "amount": round(amt, 2),
        "amount_label": label,
        "total_paid": total,
        "citation": lead.get("citation") or "",
        "caveat": lead.get("caveat") or "",
    }


def count() -> int:
    if not _loaded:
        _load()
    return len(_by_npi)


# Per-se kinds that are NOT an OIG exclusion — Medicare revocation and the
# deactivated-NPI findings. The OIG ones are caught by oig_store, which is
# authoritative and always loaded.
_NON_OIG_PERSE_KINDS = ("medicare_revoked_billing", "paid_while_terminated",
                        "deactivated_billing", "deactivated_window")


def is_on_excluded_page(npi: str) -> bool:
    """True when this provider belongs to the Excluded page and NOT the worklist.

    ONE rule, so the two surfaces cannot disagree. A provider used to appear in
    both: OIG exclusions were filtered out of the Providers list, but the
    deactivated-NPI findings were not, so 343 providers sat in the worklist AND
    on the Excluded page with a per-se finding against them.

    The distinction the split encodes: the Providers list is for leads that
    still need investigating. A per-se finding — barred party, or billing under
    an NPI CMS deactivated — is already established; the work left is filing it,
    which happens on the Excluded page.

    Falls back to the OIG check alone when no sweep is loaded, so a deployment
    without perse_leads.json keeps its old behaviour instead of emptying the
    worklist or crashing.
    """
    from core.oig_store import is_excluded
    if is_excluded(npi)[0]:
        return True
    if not _loaded:
        _load()
    lead = _by_npi.get(npi)
    return bool(lead) and lead.get("kind") in _NON_OIG_PERSE_KINDS
