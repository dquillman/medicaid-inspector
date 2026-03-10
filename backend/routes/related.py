"""
Related Provider Auto-Discovery — finds providers related to a given NPI
via shared billing relationships, shared addresses, and shared beneficiaries.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Depends
from data.duckdb_client import query_async, get_parquet_path
from core.store import get_prescanned
from routes.auth import require_user

router = APIRouter(prefix="/api/providers", tags=["related"], dependencies=[Depends(require_user)])


def _prescan_lookup() -> dict[str, dict]:
    """Build NPI -> prescan record dict for enrichment."""
    return {p["npi"]: p for p in get_prescanned()}


@router.get("/{npi}/related")
async def get_related_providers(npi: str, limit: int = 30):
    """
    Find providers related to the given NPI through three relationship types:
    1. Shared billing/servicing NPI (same billing org or same servicing NPI)
    2. Same address or zip + similar specialty
    3. Shared beneficiary overlap (same patients)
    Returns a deduplicated, scored list sorted by strength_score descending.
    """
    parquet = get_parquet_path()
    src = f"read_parquet('{parquet}')"

    # ── 1. Shared billing/servicing relationships ──────────────────────────
    # Find providers that share the same billing NPI as this provider
    shared_billing_sql = f"""
    WITH my_billing AS (
        SELECT DISTINCT BILLING_PROVIDER_NPI_NUM AS billing_npi
        FROM {src}
        WHERE SERVICING_PROVIDER_NPI_NUM = '{npi}'
          AND BILLING_PROVIDER_NPI_NUM IS NOT NULL
          AND BILLING_PROVIDER_NPI_NUM != '{npi}'
    )
    SELECT
        s.SERVICING_PROVIDER_NPI_NUM AS related_npi,
        COUNT(DISTINCT s.BILLING_PROVIDER_NPI_NUM) AS shared_count,
        'shared_billing_org' AS relationship_type
    FROM {src} s
    INNER JOIN my_billing mb ON s.BILLING_PROVIDER_NPI_NUM = mb.billing_npi
    WHERE s.SERVICING_PROVIDER_NPI_NUM IS NOT NULL
      AND s.SERVICING_PROVIDER_NPI_NUM != '{npi}'
    GROUP BY s.SERVICING_PROVIDER_NPI_NUM
    ORDER BY shared_count DESC
    LIMIT 50
    """

    # Find providers that share the same servicing NPIs
    shared_servicing_sql = f"""
    WITH my_servicing AS (
        SELECT DISTINCT SERVICING_PROVIDER_NPI_NUM AS servicing_npi
        FROM {src}
        WHERE BILLING_PROVIDER_NPI_NUM = '{npi}'
          AND SERVICING_PROVIDER_NPI_NUM IS NOT NULL
          AND SERVICING_PROVIDER_NPI_NUM != '{npi}'
    )
    SELECT
        b.BILLING_PROVIDER_NPI_NUM AS related_npi,
        COUNT(DISTINCT b.SERVICING_PROVIDER_NPI_NUM) AS shared_count,
        'shared_servicing_npi' AS relationship_type
    FROM {src} b
    INNER JOIN my_servicing ms ON b.SERVICING_PROVIDER_NPI_NUM = ms.servicing_npi
    WHERE b.BILLING_PROVIDER_NPI_NUM IS NOT NULL
      AND b.BILLING_PROVIDER_NPI_NUM != '{npi}'
    GROUP BY b.BILLING_PROVIDER_NPI_NUM
    ORDER BY shared_count DESC
    LIMIT 50
    """

    # ── 2. Shared beneficiary overlap ──────────────────────────────────────
    shared_bene_sql = f"""
    WITH my_benes AS (
        SELECT DISTINCT BENE_ID
        FROM {src}
        WHERE (BILLING_PROVIDER_NPI_NUM = '{npi}' OR SERVICING_PROVIDER_NPI_NUM = '{npi}')
          AND BENE_ID IS NOT NULL
    ),
    other_providers AS (
        SELECT
            CASE
                WHEN BILLING_PROVIDER_NPI_NUM = '{npi}' THEN SERVICING_PROVIDER_NPI_NUM
                WHEN SERVICING_PROVIDER_NPI_NUM = '{npi}' THEN BILLING_PROVIDER_NPI_NUM
                ELSE COALESCE(BILLING_PROVIDER_NPI_NUM, SERVICING_PROVIDER_NPI_NUM)
            END AS related_npi,
            p.BENE_ID
        FROM {src} p
        INNER JOIN my_benes mb ON p.BENE_ID = mb.BENE_ID
        WHERE (BILLING_PROVIDER_NPI_NUM != '{npi}' OR SERVICING_PROVIDER_NPI_NUM != '{npi}')
    )
    SELECT
        related_npi,
        COUNT(DISTINCT BENE_ID) AS shared_count,
        'shared_patients' AS relationship_type
    FROM other_providers
    WHERE related_npi IS NOT NULL AND related_npi != '{npi}'
    GROUP BY related_npi
    ORDER BY shared_count DESC
    LIMIT 50
    """

    # Run all three queries in parallel
    try:
        billing_rows, servicing_rows, bene_rows = await asyncio.gather(
            query_async(shared_billing_sql),
            query_async(shared_servicing_sql),
            query_async(shared_bene_sql),
        )
    except Exception:
        # If BENE_ID column doesn't exist, fall back without beneficiary overlap
        try:
            billing_rows, servicing_rows = await asyncio.gather(
                query_async(shared_billing_sql),
                query_async(shared_servicing_sql),
            )
            bene_rows = []
        except Exception as e:
            raise HTTPException(500, f"Query error: {e}")

    # ── 3. Same address/zip from prescan cache ─────────────────────────────
    prescan = _prescan_lookup()
    target = prescan.get(npi)
    address_matches: list[dict] = []

    if target:
        target_state = target.get("state", "")
        target_city = target.get("city", "")
        target_zip = target.get("zip", "")[:5] if target.get("zip") else ""
        target_specialty = target.get("specialty", "")

        for p_npi, p in prescan.items():
            if p_npi == npi:
                continue
            p_zip = p.get("zip", "")[:5] if p.get("zip") else ""
            p_state = p.get("state", "")
            p_city = p.get("city", "")

            # Same zip code
            if target_zip and p_zip == target_zip:
                # Boost if same specialty
                same_specialty = (
                    target_specialty
                    and p.get("specialty", "")
                    and target_specialty == p.get("specialty", "")
                )
                address_matches.append({
                    "related_npi": p_npi,
                    "shared_count": 2 if same_specialty else 1,
                    "relationship_type": "same_address" if same_specialty else "same_zip",
                })

    # ── Merge & score ──────────────────────────────────────────────────────
    # Collect all relationships per NPI
    npi_rels: dict[str, list[dict]] = {}
    for row in billing_rows + servicing_rows + bene_rows + address_matches:
        rnpi = str(row["related_npi"])
        if rnpi not in npi_rels:
            npi_rels[rnpi] = []
        npi_rels[rnpi].append(row)

    # Compute strength score (0-100)
    results = []
    for rnpi, rels in npi_rels.items():
        # Pick strongest relationship type
        best = max(rels, key=lambda r: r["shared_count"])
        rel_type = best["relationship_type"]
        shared_count = best["shared_count"]

        # Score components — weighted by relationship type
        type_weights = {
            "shared_billing_org": 35,
            "shared_servicing_npi": 30,
            "shared_patients": 25,
            "same_address": 20,
            "same_zip": 10,
        }
        base = type_weights.get(rel_type, 10)

        # Bonus for multiple relationship types
        unique_types = {r["relationship_type"] for r in rels}
        multi_bonus = min(len(unique_types) - 1, 3) * 10

        # Volume bonus (capped)
        volume_bonus = min(shared_count * 3, 30)

        strength_score = min(base + multi_bonus + volume_bonus, 100)

        # Collect all relationship types for display
        all_types = list(unique_types)
        total_shared = sum(r["shared_count"] for r in rels)

        # Enrich from prescan cache
        cached = prescan.get(rnpi, {})
        results.append({
            "npi": rnpi,
            "name": cached.get("provider_name") or cached.get("name", ""),
            "specialty": cached.get("specialty", ""),
            "state": cached.get("state", ""),
            "city": cached.get("city", ""),
            "relationship_types": all_types,
            "relationship_type": rel_type,
            "strength_score": strength_score,
            "shared_count": total_shared,
            "risk_score": cached.get("risk_score", 0),
            "total_paid": cached.get("total_paid", 0),
        })

    # Sort by strength, take top N
    results.sort(key=lambda r: r["strength_score"], reverse=True)
    results = results[:limit]

    return {
        "npi": npi,
        "related_providers": results,
        "total": len(results),
    }
