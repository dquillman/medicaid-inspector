"""
Exclusion Aggregator — consolidates all exclusion/deactivation checks into one call.

Sources checked:
  1. OIG LEIE (local CSV cache)
  2. SAM.gov federal exclusion API
  3. NPI deactivation status (from NPPES data in prescan cache)
  4. NPPES enumeration date (flag if NPI < 6 months old)
"""
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# In-memory store for batch scan results
_batch_results: dict | None = None


async def check_all_exclusions(npi: str, name: str = "") -> dict:
    """
    Run all exclusion checks for a single provider.
    Returns {checks: [{source, status, details}], any_excluded: bool, risk_level: "clear"|"warning"|"excluded"}
    """
    checks: list[dict] = []

    # 1. OIG LEIE check
    try:
        from core.oig_store import is_excluded as oig_is_excluded, get_oig_stats
        excluded, record = oig_is_excluded(npi)
        stats = get_oig_stats()
        if excluded:
            checks.append({
                "source": "OIG LEIE",
                "status": "excluded",
                "details": {
                    "message": "Provider appears on the OIG List of Excluded Individuals/Entities",
                    "record": record,
                },
            })
        else:
            checks.append({
                "source": "OIG LEIE",
                "status": "clear",
                "details": {
                    "message": "Not found on OIG exclusion list",
                    "list_loaded": stats.get("loaded", False),
                    "records_checked": stats.get("record_count", 0),
                },
            })
    except Exception as e:
        log.warning("OIG check failed for %s: %s", npi, e)
        checks.append({
            "source": "OIG LEIE",
            "status": "error",
            "details": {"message": f"Check failed: {e}"},
        })

    # 2. SAM.gov check
    try:
        from core.sam_store import check_sam_exclusion
        sam_result = await check_sam_exclusion(npi=npi, name=name)
        if sam_result.get("error"):
            checks.append({
                "source": "SAM.gov",
                "status": "unavailable",
                "details": {"message": sam_result["error"]},
            })
        elif sam_result.get("excluded"):
            checks.append({
                "source": "SAM.gov",
                "status": "excluded",
                "details": {
                    "message": "Provider found on SAM.gov federal exclusion list",
                    "records": sam_result.get("records", []),
                },
            })
        else:
            checks.append({
                "source": "SAM.gov",
                "status": "clear",
                "details": {"message": "Not found on SAM.gov exclusion list"},
            })
    except Exception as e:
        log.warning("SAM.gov check failed for %s: %s", npi, e)
        checks.append({
            "source": "SAM.gov",
            "status": "error",
            "details": {"message": f"Check failed: {e}"},
        })

    # 3 & 4. NPI deactivation and enumeration date from NPPES cache
    try:
        from core.store import get_prescanned
        providers = get_prescanned()
        provider = None
        for p in providers:
            if p.get("npi") == npi:
                provider = p
                break

        nppes = provider.get("nppes", {}) if provider else {}

        # NPI deactivation check
        npi_status = nppes.get("status", "").upper() if nppes else ""
        if npi_status and npi_status != "A" and npi_status != "ACTIVE":
            checks.append({
                "source": "NPI Status",
                "status": "excluded",
                "details": {
                    "message": f"NPI is deactivated or inactive (status: {npi_status})",
                    "npi_status": npi_status,
                },
            })
        elif npi_status:
            checks.append({
                "source": "NPI Status",
                "status": "clear",
                "details": {
                    "message": "NPI is active",
                    "npi_status": npi_status,
                },
            })
        else:
            checks.append({
                "source": "NPI Status",
                "status": "unavailable",
                "details": {"message": "No NPPES status data available for this provider"},
            })

        # Enumeration date check (flag if < 6 months old)
        last_updated = nppes.get("last_updated", "") if nppes else ""
        if last_updated:
            try:
                # NPPES last_updated format varies; try common formats
                enum_date = None
                for date_fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        enum_date = datetime.strptime(last_updated, date_fmt)
                        break
                    except ValueError:
                        continue

                if enum_date:
                    age = datetime.now() - enum_date
                    six_months = timedelta(days=180)
                    if age < six_months:
                        checks.append({
                            "source": "NPI Age",
                            "status": "warning",
                            "details": {
                                "message": f"NPI was recently enumerated/updated ({last_updated}) — less than 6 months ago",
                                "enumeration_date": last_updated,
                                "days_old": age.days,
                            },
                        })
                    else:
                        checks.append({
                            "source": "NPI Age",
                            "status": "clear",
                            "details": {
                                "message": "NPI has been active for more than 6 months",
                                "enumeration_date": last_updated,
                                "days_old": age.days,
                            },
                        })
                else:
                    checks.append({
                        "source": "NPI Age",
                        "status": "unavailable",
                        "details": {"message": f"Could not parse enumeration date: {last_updated}"},
                    })
            except Exception:
                checks.append({
                    "source": "NPI Age",
                    "status": "unavailable",
                    "details": {"message": f"Could not parse enumeration date: {last_updated}"},
                })
        else:
            checks.append({
                "source": "NPI Age",
                "status": "unavailable",
                "details": {"message": "No enumeration date available"},
            })

    except Exception as e:
        log.warning("NPPES check failed for %s: %s", npi, e)
        checks.append({
            "source": "NPI Status",
            "status": "error",
            "details": {"message": f"Check failed: {e}"},
        })
        checks.append({
            "source": "NPI Age",
            "status": "error",
            "details": {"message": f"Check failed: {e}"},
        })

    # Determine overall risk level
    statuses = [c["status"] for c in checks]
    any_excluded = "excluded" in statuses
    any_warning = "warning" in statuses

    if any_excluded:
        risk_level = "excluded"
    elif any_warning:
        risk_level = "warning"
    else:
        risk_level = "clear"

    return {
        "npi": npi,
        "checks": checks,
        "any_excluded": any_excluded,
        "risk_level": risk_level,
    }


def run_batch_exclusion_scan() -> dict:
    """
    Synchronous batch scan of all providers in prescan cache.
    Checks OIG LEIE and NPI status (both are local/fast lookups).
    Stores results in memory and returns summary.
    """
    global _batch_results
    from core.store import get_prescanned
    from core.oig_store import is_excluded as oig_is_excluded, get_oig_stats

    providers = get_prescanned()
    oig_stats = get_oig_stats()

    total_checked = 0
    oig_excluded_count = 0
    deactivated_count = 0
    new_npi_count = 0
    excluded_providers: list[dict] = []

    six_months_ago = datetime.now() - timedelta(days=180)

    for p in providers:
        npi = p.get("npi", "")
        if not npi:
            continue
        total_checked += 1
        nppes = p.get("nppes", {})
        provider_name = nppes.get("name", "") if nppes else p.get("provider_name", "")
        state = nppes.get("address", {}).get("state", "") if nppes else p.get("state", "")
        risk_score = p.get("risk_score", 0)

        issues: list[str] = []

        # OIG check
        excluded, record = oig_is_excluded(npi)
        if excluded:
            oig_excluded_count += 1
            issues.append("OIG LEIE excluded")

        # NPI status check
        npi_status = (nppes.get("status", "") if nppes else "").upper()
        if npi_status and npi_status != "A" and npi_status != "ACTIVE":
            deactivated_count += 1
            issues.append(f"NPI deactivated ({npi_status})")

        # New NPI check
        last_updated = nppes.get("last_updated", "") if nppes else ""
        if last_updated:
            try:
                enum_date = None
                for date_fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        enum_date = datetime.strptime(last_updated, date_fmt)
                        break
                    except ValueError:
                        continue
                if enum_date and enum_date > six_months_ago:
                    new_npi_count += 1
                    issues.append("New NPI (< 6 months)")
            except Exception:
                pass

        if issues:
            excluded_providers.append({
                "npi": npi,
                "provider_name": provider_name,
                "state": state,
                "risk_score": risk_score,
                "issues": issues,
                "oig_excluded": excluded,
                "oig_record": record,
            })

    _batch_results = {
        "total_checked": total_checked,
        "oig_excluded_count": oig_excluded_count,
        "deactivated_count": deactivated_count,
        "new_npi_count": new_npi_count,
        "total_excluded": len(excluded_providers),
        "oig_list_loaded": oig_stats.get("loaded", False),
        "oig_list_size": oig_stats.get("record_count", 0),
        "excluded_providers": excluded_providers,
        "scanned_at": datetime.now().isoformat(),
    }

    log.info(
        "Batch exclusion scan: %d checked, %d OIG excluded, %d deactivated, %d new NPI",
        total_checked, oig_excluded_count, deactivated_count, new_npi_count,
    )

    return _batch_results


def get_batch_results() -> dict | None:
    """Return the latest batch scan results, or None if never run."""
    return _batch_results
