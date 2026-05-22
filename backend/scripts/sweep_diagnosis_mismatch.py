"""
One-shot sweep: run diagnosis_procedure_mismatch over every cached provider
that has Medicare data (MUP) and matching condition-specific HCPCS billing.
Surfaces NPIs that would newly flag if the prescan were re-run today.

Usage: python backend/scripts/sweep_diagnosis_mismatch.py [--top 25]
"""
import argparse
import ijson
import pathlib
import sys
import time

_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from services import mup_cache
from services.anomaly_detector import (
    diagnosis_procedure_mismatch,
    _HCPCS_CONDITION_MAP,
)


def stream_providers(path: pathlib.Path):
    """Stream the providers[] array from prescan_cache.json without loading all of it."""
    with open(path, "rb") as f:
        for obj in ijson.items(f, "providers.item"):
            yield obj


def sweep(top_n: int) -> None:
    if not mup_cache.is_local():
        print("ERROR: local MUP cache not present", file=sys.stderr)
        sys.exit(1)

    print(f"MUP rows: {mup_cache.row_count():,}")
    print(f"HCPCS condition map covers {len(_HCPCS_CONDITION_MAP)} codes")
    print()

    cache_path = _BACKEND / "prescan_cache.json"
    print(f"Streaming {cache_path}…")

    started = time.time()
    candidates: list[tuple[float, str, str, str]] = []  # (score, npi, top_code, reason)
    scanned = 0
    with_top_in_map = 0
    with_mup = 0

    for p in stream_providers(cache_path):
        scanned += 1
        top_code = (p.get("top_hcpcs") or "").upper()
        if top_code not in _HCPCS_CONDITION_MAP:
            continue
        with_top_in_map += 1

        npi = p.get("npi")
        mup_row = mup_cache.lookup(npi)
        if mup_row is None:
            continue
        with_mup += 1

        # We don't have the full HCPCS breakdown cached; reconstruct a single
        # dominant row using the cached top_hcpcs + total_paid.
        # ijson returns numerics as Decimal — cast to float to match detector types.
        hcpcs_rows = [{
            "hcpcs_code": top_code,
            "total_paid": float(p.get("total_paid", 0) or 0),
        }]
        result = diagnosis_procedure_mismatch({"npi": npi}, hcpcs_rows, mup_row)
        if result["flagged"]:
            candidates.append((result["score"], npi, top_code, result["reason"]))

        if scanned % 10000 == 0:
            print(f"  scanned={scanned:,}  in-map={with_top_in_map:,}  "
                  f"in-mup={with_mup:,}  flagged={len(candidates):,}  "
                  f"elapsed={time.time() - started:.0f}s")

    print()
    print(f"Total scanned:                {scanned:,}")
    print(f"  with top HCPCS in our map:  {with_top_in_map:,}")
    print(f"  also present in Medicare:   {with_mup:,}")
    print(f"  flagged by mismatch signal: {len(candidates):,}")
    print(f"Elapsed:                      {time.time() - started:.0f}s")
    print()

    if not candidates:
        print("No new mismatches found. All providers with condition-specific top codes "
              "have plausible Medicare diagnosis prevalence for that condition.")
        return

    candidates.sort(reverse=True)
    print(f"Top {min(top_n, len(candidates))} new mismatch flags:")
    print("-" * 100)
    for score, npi, code, reason in candidates[:top_n]:
        print(f"  score={score:.2f}  NPI={npi}  top={code}")
        print(f"    {reason}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    sweep(args.top)
