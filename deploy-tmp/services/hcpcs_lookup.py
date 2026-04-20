"""
Shared HCPCS / CPT code description lookup.

Provides a cached lookup that checks a registered CPT dictionary first,
then falls back to the NLM Clinical Tables API for HCPCS Level II codes.

Call ``register_cpt_descriptions()`` at startup to populate the dictionary
(e.g. from ``data.cpt_descriptions.CPT_DESCRIPTIONS``).
"""
import logging
import httpx as _httpx

logger = logging.getLogger(__name__)

# Module-level client reused across calls (avoids per-request TLS handshake)
_http_client = _httpx.AsyncClient(timeout=8.0)

# Populated at startup via register_cpt_descriptions()
_CPT_DESCRIPTIONS: dict[str, str] = {}


def get_cpt_descriptions() -> dict[str, str]:
    """Return the built-in CPT description dictionary (read-only reference)."""
    return _CPT_DESCRIPTIONS


def register_cpt_descriptions(extra: dict[str, str]) -> None:
    """Merge additional CPT descriptions into the shared dictionary.

    Call this at module init time to populate from
    ``data.cpt_descriptions.CPT_DESCRIPTIONS``.
    """
    _CPT_DESCRIPTIONS.update(extra)


async def fetch_hcpcs_descriptions(codes: list[str]) -> dict[str, str]:
    """Return descriptions for a list of HCPCS/CPT codes.

    Strategy:
      1. Numeric codes (CPT / HCPCS Level I) -- look up in built-in dictionary.
      2. Alphanumeric codes (HCPCS Level II, e.g. S5125) -- query NLM API.
    """
    import asyncio as _asyncio

    results: dict[str, str] = {}
    nlm_codes: list[str] = []

    for code in codes:
        if code.isdigit():
            desc = _CPT_DESCRIPTIONS.get(code, "")
            if desc:
                results[code] = desc
        else:
            nlm_codes.append(code)

    if not nlm_codes:
        return results

    async def fetch_one(client, code: str) -> tuple[str, str]:
        try:
            url = (
                f"https://clinicaltables.nlm.nih.gov/api/hcpcs/v3/search"
                f"?terms={code}&maxList=10"
            )
            r = await client.get(url)
            d = r.json()
            if d[3]:
                for item in d[3]:
                    if len(item) >= 2 and str(item[0]).upper() == code.upper():
                        return code, item[1]
            return code, ""
        except Exception:
            logger.warning("Failed to fetch HCPCS description for code %s", code)
            return code, ""

    try:
        pairs = await _asyncio.gather(*[fetch_one(_http_client, c) for c in nlm_codes])
        for code, desc in pairs:
            if desc:
                results[code] = desc
    except Exception:
        logger.warning("Failed to connect to NLM HCPCS API for codes: %s", nlm_codes)

    return results
