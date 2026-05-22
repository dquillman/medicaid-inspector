"""
Backfill provider_name/state/city into prescan_cache.json from the slim cache.

Why: the rebuilt prescan_cache.json (after the bulk recovery) doesn't carry
provider identity data, so the NPPES enrichment startup check sees all 106k
providers as needing re-enrichment. Adding the basic identity fields lets
the _needs_nppes filter short-circuit on the next startup.

Usage: python backend/scripts/backfill_names_from_slim.py
"""
import json
import pathlib
import sys
import time

_BACKEND = pathlib.Path(__file__).parent.parent

print = __builtins__.print if isinstance(__builtins__, dict) else print  # noqa
import functools
print = functools.partial(print, flush=True)  # noqa


def main():
    slim_path = _BACKEND / "prescan_slim.json"
    full_path = _BACKEND / "prescan_cache.json"
    tmp_path = _BACKEND / "prescan_cache.json.backfill"

    print(f"Reading slim cache: {slim_path}")
    t0 = time.time()
    slim = json.loads(slim_path.read_text(encoding="utf-8"))
    slim_by_npi = {
        p["npi"]: p for p in slim.get("providers", []) if p.get("npi")
    }
    print(f"  {len(slim_by_npi):,} providers in slim cache (loaded in {time.time() - t0:.1f}s)")

    print(f"Reading full cache: {full_path}")
    t0 = time.time()
    full = json.loads(full_path.read_text(encoding="utf-8"))
    full_providers = full.get("providers", [])
    print(f"  {len(full_providers):,} providers in full cache (loaded in {time.time() - t0:.1f}s)")

    print("Merging identity fields…")
    t0 = time.time()
    backfilled = 0
    already_set = 0
    no_slim_match = 0
    for p in full_providers:
        if p.get("provider_name") or p.get("state") or p.get("city"):
            already_set += 1
            continue
        slim_p = slim_by_npi.get(p["npi"])
        if not slim_p:
            no_slim_match += 1
            continue
        if slim_p.get("provider_name"):
            p["provider_name"] = slim_p["provider_name"]
        if slim_p.get("state"):
            p["state"] = slim_p["state"]
        if slim_p.get("city"):
            p["city"] = slim_p["city"]
        if slim_p.get("specialty"):
            p["specialty"] = slim_p["specialty"]
        backfilled += 1
    print(f"  backfilled: {backfilled:,}")
    print(f"  already had identity: {already_set:,}")
    print(f"  no slim match: {no_slim_match:,}")
    print(f"  merge time: {time.time() - t0:.1f}s")

    print(f"Writing updated full cache atomically…")
    t0 = time.time()
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(full, f, default=str)
    tmp_path.replace(full_path)
    print(f"  wrote {full_path.stat().st_size / 1_048_576:.1f} MB in {time.time() - t0:.1f}s")

    print("DONE")


if __name__ == "__main__":
    main()
