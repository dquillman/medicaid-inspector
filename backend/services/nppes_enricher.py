"""
Background NPPES enrichment: after each scan batch, fetch provider identity
data (name, state, city) from NPPES and store it in the prescan cache.
Runs concurrently up to 15 requests at a time so it doesn't bottleneck scans.
Saves to disk every SAVE_CHUNK providers so names appear progressively.
"""
import asyncio
import logging

log = logging.getLogger(__name__)

SAVE_CHUNK = 200  # write to disk after every N providers enriched


async def enrich_batch_with_nppes(npis: list[str]) -> None:
    """Fetch NPPES for a list of NPIs and update their prescan cache entries.

    Works in sub-batches of SAVE_CHUNK so names/state/city appear progressively
    rather than waiting for the entire list to complete before saving anything.
    """
    from data.nppes_client import get_provider
    from core.store import get_prescanned, append_prescanned

    if not npis:
        return

    sem = asyncio.Semaphore(15)

    async def fetch_one(npi: str):
        async with sem:
            try:
                return npi, await get_provider(npi)
            except Exception as e:
                log.warning("NPPES fetch failed for %s: %s", npi, e)
                return npi, {}

    total = len(npis)
    log.info("NPPES enrichment: fetching %d providers (saving every %d)…", total, SAVE_CHUNK)
    saved_count = 0

    # Process in chunks so we can save progressively
    for chunk_start in range(0, total, SAVE_CHUNK):
        chunk = npis[chunk_start : chunk_start + SAVE_CHUNK]
        pairs = await asyncio.gather(*[fetch_one(npi) for npi in chunk])

        by_npi = {p["npi"]: p for p in get_prescanned()}
        updated = []
        for npi, nppes_data in pairs:
            if npi not in by_npi or not nppes_data:
                continue
            entry = dict(by_npi[npi])
            entry["nppes"] = nppes_data
            addr = nppes_data.get("address", {})
            entry["state"] = addr.get("state", "")
            entry["city"] = addr.get("city", "")
            entry["provider_name"] = nppes_data.get("name", "")
            updated.append(entry)

        if updated:
            append_prescanned(updated)
            saved_count += len(updated)

        done = min(chunk_start + SAVE_CHUNK, total)
        log.info(
            "NPPES enrichment: %d/%d fetched, %d saved to cache",
            done, total, saved_count,
        )

    log.info("NPPES enrichment complete — %d/%d providers updated with name/state/city", saved_count, total)
