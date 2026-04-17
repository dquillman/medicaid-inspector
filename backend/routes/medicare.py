"""
Medicare Cross-Reference routes.
Provides Medicare utilization data and Medicaid vs Medicare comparison.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from routes.auth import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["medicare"], dependencies=[Depends(require_user)])


@router.get("/{npi}/medicare")
async def medicare_utilization(npi: str):
    """Fetch Medicare utilization data for a single provider."""
    from services.medicare_lookup import get_medicare_utilization

    result = await get_medicare_utilization(npi)
    if "error" in result:
        return {"npi": npi, "has_data": False, "error": result["error"]}
    return result


@router.get("/{npi}/medicare-compare")
async def medicare_compare(npi: str):
    """
    Side-by-side Medicaid vs Medicare comparison for a provider.
    Returns both datasets plus computed discrepancy indicators.
    """
    from services.medicare_lookup import get_medicare_utilization
    from core.store import get_provider_by_npi

    # Get Medicare data
    medicare = await get_medicare_utilization(npi)

    # Get Medicaid data from prescan cache
    medicaid_entry = get_provider_by_npi(npi)

    if not medicaid_entry:
        raise HTTPException(status_code=404, detail="Provider not found in Medicaid data")

    medicaid_paid = medicaid_entry.get("total_paid", 0)
    medicaid_claims = medicaid_entry.get("total_claims", 0)
    medicaid_benes = medicaid_entry.get("total_beneficiaries", 0)

    medicare_paid = medicare.get("medicare_total_paid", 0)
    medicare_services = medicare.get("medicare_total_services", 0)
    medicare_benes = medicare.get("medicare_beneficiaries", 0)
    medicare_has_data = medicare.get("has_data", False)

    # Compute discrepancy indicators
    discrepancies = []

    if medicare_has_data and medicare_paid > 0:
        # Medicaid-to-Medicare billing ratio
        ratio = medicaid_paid / medicare_paid if medicare_paid > 0 else None
        if ratio is not None and ratio > 3.0:
            discrepancies.append({
                "type": "billing_ratio",
                "severity": "HIGH" if ratio > 5.0 else "MEDIUM",
                "description": f"Medicaid billing is {ratio:.1f}x higher than Medicare billing",
                "medicaid_value": medicaid_paid,
                "medicare_value": medicare_paid,
                "ratio": round(ratio, 2),
            })

        # Beneficiary ratio check
        if medicare_benes > 0 and medicaid_benes > 0:
            bene_ratio = medicaid_benes / medicare_benes
            if bene_ratio > 5.0:
                discrepancies.append({
                    "type": "beneficiary_ratio",
                    "severity": "MEDIUM",
                    "description": f"Medicaid beneficiaries ({medicaid_benes:,}) are {bene_ratio:.1f}x Medicare beneficiaries ({medicare_benes:,})",
                    "medicaid_value": medicaid_benes,
                    "medicare_value": medicare_benes,
                    "ratio": round(bene_ratio, 2),
                })

        # Per-beneficiary spending comparison
        medicaid_per_bene = medicaid_paid / medicaid_benes if medicaid_benes > 0 else 0
        medicare_per_bene = medicare.get("medicare_avg_per_bene", 0)
        if medicare_per_bene > 0 and medicaid_per_bene > 0:
            per_bene_ratio = medicaid_per_bene / medicare_per_bene
            if per_bene_ratio > 2.0:
                discrepancies.append({
                    "type": "per_bene_spending",
                    "severity": "HIGH" if per_bene_ratio > 3.0 else "MEDIUM",
                    "description": f"Medicaid per-beneficiary spending (${medicaid_per_bene:,.0f}) is {per_bene_ratio:.1f}x Medicare (${medicare_per_bene:,.0f})",
                    "medicaid_value": round(medicaid_per_bene, 2),
                    "medicare_value": round(medicare_per_bene, 2),
                    "ratio": round(per_bene_ratio, 2),
                })
    elif not medicare_has_data and medicaid_paid > 50_000:
        discrepancies.append({
            "type": "no_medicare_data",
            "severity": "LOW",
            "description": "No Medicare billing found despite significant Medicaid billing -- may indicate Medicaid-only practice or data gap",
            "medicaid_value": medicaid_paid,
            "medicare_value": 0,
            "ratio": None,
        })

    # Get Medicaid HCPCS codes for comparison
    medicaid_hcpcs = []
    try:
        from data.duckdb_client import query_async, get_parquet_path
        parquet = get_parquet_path()
        sql = f"""
            SELECT hcpcs_code,
                   SUM(medicaid_paid) AS total_paid,
                   SUM(claims) AS total_claims
            FROM read_parquet('{parquet}')
            WHERE billing_npi = ?
            GROUP BY hcpcs_code
            ORDER BY total_paid DESC
            LIMIT 10
        """
        rows = await query_async(sql, [npi])
        medicaid_hcpcs = [
            {"hcpcs_code": r[0], "total_paid": float(r[1]), "total_claims": int(r[2])}
            for r in rows
        ]
    except Exception as e:
        logger.warning("Medicaid HCPCS cross-reference query failed for NPI %s: %s", npi, e)

    return {
        "npi": npi,
        "medicare_has_data": medicare_has_data,
        "medicaid": {
            "total_paid": medicaid_paid,
            "total_claims": medicaid_claims,
            "total_beneficiaries": medicaid_benes,
            "avg_per_bene": round(medicaid_paid / medicaid_benes, 2) if medicaid_benes > 0 else 0,
            "top_hcpcs": medicaid_hcpcs,
        },
        "medicare": {
            "total_paid": medicare_paid,
            "total_services": medicare_services,
            "total_submitted": medicare.get("medicare_total_submitted", 0),
            "total_beneficiaries": medicare_benes,
            "avg_per_bene": medicare.get("medicare_avg_per_bene", 0),
            "top_hcpcs": medicare.get("top_hcpcs", []),
            "provider_type": medicare.get("provider_type"),
        },
        "discrepancies": discrepancies,
        "discrepancy_count": len(discrepancies),
        "has_discrepancies": len(discrepancies) > 0,
        "error": medicare.get("error"),
    }
