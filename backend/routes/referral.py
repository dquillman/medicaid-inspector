"""
Referral Packet endpoint — generates a comprehensive HTML fraud investigation
referral packet suitable for printing or PDF conversion (browser Print → Save
as PDF). The heavy lifting lives in services.referral_packet: build_referral_packet
assembles a structured dict by REUSING the app's already-computed signal /
timeline / exclusion / ownership / narrative data, and render_referral_html turns
that into the print-ready HTML. This route just fetches + enriches the provider,
fetches HCPCS descriptions, and delegates.
"""
import logging

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse

from core.store import get_provider_by_npi
from routes.auth import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["referral"], dependencies=[Depends(require_user)])


@router.get("/{npi}/referral-packet", response_class=HTMLResponse)
async def generate_referral_packet(npi: str):
    """Generate a comprehensive HTML fraud investigation referral packet."""
    from core.review_store import get_review_item
    from data.nppes_client import get_provider
    from services.hcpcs_lookup import fetch_hcpcs_descriptions
    from services.slim_cache_enricher import enrich_provider_detail
    from services.referral_packet import build_referral_packet, render_referral_html

    cached = get_provider_by_npi(npi)
    if not cached:
        raise HTTPException(404, f"Provider {npi} not found in scan cache - run a scan first")

    # Slim cache (Cloud Run) omits per-HCPCS/timeline arrays; enrich from a local
    # parquet when available, else carry a note so the packet degrades gracefully.
    cached, slim_note = enrich_provider_detail(cached)

    # Fill missing billing aggregates from DuckDB when the slim cache is sparse.
    if not (cached.get("total_paid") and cached.get("total_beneficiaries") and cached.get("total_claims")):
        try:
            from data.duckdb_client import query_async as _ddb_query, provider_aggregate_sql as _ddb_agg
            rows = await _ddb_query(_ddb_agg(where=f"BILLING_PROVIDER_NPI_NUM = '{npi}'", limit=1))
            if rows:
                agg = rows[0]
                cached = {**cached,
                          "total_paid": cached.get("total_paid") or agg.get("total_paid"),
                          "total_claims": cached.get("total_claims") or agg.get("total_claims"),
                          "total_beneficiaries": cached.get("total_beneficiaries") or agg.get("total_beneficiaries")}
        except Exception:
            logger.debug("DuckDB enrichment failed for referral NPI %s", npi, exc_info=True)

    # NPPES identity (live lookup only if the cache lacks it).
    if not cached.get("nppes"):
        try:
            cached = {**cached, "nppes": await get_provider(npi)}
        except Exception as e:
            logger.warning("NPPES lookup failed for referral NPI %s: %s", npi, e)

    # Attach the review item so the builder can include case-management status.
    cached = {**cached, "_review_item": get_review_item(npi)}

    # Assemble the structured packet (reuses signals/exclusions/network/narrative).
    packet = await build_referral_packet(npi, provider=cached)

    # HCPCS descriptions for the code table.
    codes = [h.get("hcpcs_code", "") for h in (packet.get("hcpcs") or []) if h.get("hcpcs_code")][:15]
    if not codes and (packet.get("hcpcs_summary") or {}).get("top_hcpcs"):
        codes = [packet["hcpcs_summary"]["top_hcpcs"]]
    hcpcs_descriptions = await fetch_hcpcs_descriptions(codes) if codes else {}

    return render_referral_html(packet, hcpcs_descriptions=hcpcs_descriptions, slim_note=slim_note)
