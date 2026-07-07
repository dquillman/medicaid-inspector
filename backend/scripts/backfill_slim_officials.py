"""
Backfill authorized officials into prescan_slim.json.

The slim cache (used on Cloud Run) is flat — no nppes sub-dict at all — so
shared-official ownership matching (services/ownership_tracer.py) had zero
data to compare in production: every provider reported 0 connections with no
error. The full cache carries nppes.authorized_official as {name, title} for
~98k of 106k providers.

This script copies just the authorized_official (and nothing else — keeps the
slim cache slim) from prescan_cache.json into prescan_slim.json, under the
same nppes.authorized_official path the tracer reads.

Run from backend/:  python scripts/backfill_slim_officials.py
Then upload the new slim to GCS (startup restores slim FROM the bucket):
  gcloud storage cp prescan_slim.json gs://medicaid-inspector-data/prescan_slim.json
"""
import json
import pathlib
import sys

_BACKEND = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    full_path = _BACKEND / "prescan_cache.json"
    slim_path = _BACKEND / "prescan_slim.json"
    if not full_path.exists() or not slim_path.exists():
        print("need both prescan_cache.json and prescan_slim.json in backend/")
        return 1

    print("loading full cache…")
    full = json.load(open(full_path, encoding="utf-8"))
    full_provs = full if isinstance(full, list) else full.get("providers", [])
    ao_by_npi: dict[str, dict] = {}
    for p in full_provs:
        ao = (p.get("nppes") or {}).get("authorized_official") or {}
        name = (ao.get("name") or "").strip()
        if p.get("npi") and name:
            ao_by_npi[p["npi"]] = {"name": name, "title": (ao.get("title") or "").strip()}
    print(f"full cache: {len(full_provs)} providers, {len(ao_by_npi)} with an authorized official")

    print("loading slim cache…")
    slim = json.load(open(slim_path, encoding="utf-8"))
    slim_provs = slim if isinstance(slim, list) else slim.get("providers", [])
    before = slim_path.stat().st_size

    added = 0
    for sp in slim_provs:
        ao = ao_by_npi.get(sp.get("npi"))
        if not ao:
            continue
        nppes = sp.setdefault("nppes", {})
        if not (nppes.get("authorized_official") or {}).get("name"):
            nppes["authorized_official"] = ao
            added += 1

    tmp = slim_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(slim, f, separators=(",", ":"), default=str)
    tmp.replace(slim_path)
    after = slim_path.stat().st_size
    print(f"backfilled {added} authorized officials; "
          f"slim size {before/1048576:.1f}MB -> {after/1048576:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
