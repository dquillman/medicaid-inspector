"""
Precompute the heavy claim-level analyses from the FULL prescan cache and
write backend/precomputed_analyses.json (a few MB).

Why: Cloud Run runs on the slim cache (no per-HCPCS detail) inside a 2 GiB
container — it can neither load the 1.4 GB full cache nor query the remote
parquet within the request timeout. So the analyses run here, on a machine
with the full cache, and prod serves the stored results.

Run after every full scan / dataset refresh — use an interpreter that has the
backend deps installed (duckdb etc.); on Dave's machine that's G:\Python311:
    G:\Python311\python.exe backend/scripts/precompute_analyses.py
Then upload to GCS (or let the next deploy pick it up):
    gcloud storage cp backend/precomputed_analyses.json gs://medicaid-inspector-data/

Sections: claim_patterns, pharmacy_high_risk, dme_high_risk, doctor_shopping.
"""
import asyncio
import datetime
import functools
import json
import logging
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")

_OUT = _BACKEND / "precomputed_analyses.json"
_LIMIT = 500  # matches the max limit the API routes accept


def main() -> int:
    from core.store import load_prescanned_from_disk, get_prescanned

    print("Loading full prescan cache (this parses ~1.4 GB of JSON; takes a few minutes)…")
    t0 = time.time()
    if not load_prescanned_from_disk():
        print("ERROR: could not load prescan_cache.json — run a full scan first.")
        return 1
    providers = get_prescanned()
    print(f"Loaded {len(providers):,} providers in {time.time() - t0:.0f}s")

    from services.slim_cache_enricher import has_hcpcs_detail
    if not has_hcpcs_detail():
        print("ERROR: loaded cache has no per-HCPCS detail (slim cache?). "
              "Precompute needs the FULL cache.")
        return 1

    out: dict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "provider_count": len(providers),
        "limit": _LIMIT,
    }

    print("Computing claim patterns…")
    t = time.time()
    from services.claim_patterns import _compute_all_from_cache
    out["claim_patterns"] = _compute_all_from_cache(limit=_LIMIT)
    print(f"  done in {time.time() - t:.0f}s "
          f"({sum(len(v) for v in out['claim_patterns'].values() if isinstance(v, list))} findings)")

    print("Computing pharmacy high-risk…")
    t = time.time()
    from services.pharmacy_analyzer import get_high_risk_providers as pharm_high_risk
    out["pharmacy_high_risk"] = asyncio.run(pharm_high_risk(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s ({out['pharmacy_high_risk'].get('total', 0)} providers)")

    print("Computing DME high-risk…")
    t = time.time()
    from services.dme_analyzer import get_high_risk_providers as dme_high_risk
    out["dme_high_risk"] = asyncio.run(dme_high_risk(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s ({out['dme_high_risk'].get('total', 0)} providers)")

    print("Computing doctor shopping…")
    t = time.time()
    from services.beneficiary_analyzer import detect_doctor_shopping
    out["doctor_shopping"] = asyncio.run(detect_doctor_shopping(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s "
          f"({out['doctor_shopping'].get('total_flagged', 0)} flagged)")

    print("Computing billing top codes…")
    t = time.time()
    from routes.billing_codes import top_codes, diagnosis_flags
    out["billing_top_codes"] = asyncio.run(top_codes(limit=200, min_providers=1))
    print(f"  done in {time.time() - t:.0f}s ({out['billing_top_codes'].get('total_codes', 0)} codes)")

    print("Computing diagnosis flags…")
    t = time.time()
    out["billing_diagnosis_flags"] = asyncio.run(diagnosis_flags(limit=_LIMIT))
    print(f"  done in {time.time() - t:.0f}s ({out['billing_diagnosis_flags'].get('total', 0)} flagged)")

    print("Computing state billing trends…")
    t = time.time()
    from services.trend_divergence import _aggregate_billing_by_state_year
    out["billing_by_state_year"] = _aggregate_billing_by_state_year()
    print(f"  done in {time.time() - t:.0f}s ({len(out['billing_by_state_year'])} states)")

    tmp = _OUT.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), default=str)
    tmp.replace(_OUT)
    size_mb = _OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote {_OUT} ({size_mb:.1f} MB)")
    print("Next: upload to GCS ->")
    print('  gcloud storage cp backend/precomputed_analyses.json gs://medicaid-inspector-data/')
    return 0


if __name__ == "__main__":
    sys.exit(main())
