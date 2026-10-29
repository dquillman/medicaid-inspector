"""
Practice (NPPES) state + name for per-se lead NPIs -> backend/perse_practice_states.json.

The spend file has no billing state, and the Medicaid enrollment file only says
where a provider was ENROLLED. Re-checking the 109 strongest per-se leads
(2026-10-28) showed the biggest false leads were a provider terminated in one
state but practising in another (a $46M Washington "termination" for an Oregon
nonprofit; Connecticut "license revoked" for doctors now in CA/NY/VA). The
practice state from NPPES is what lets build_perse_sweep.py and the DOJ
shortlist notice that.

Read-only against the public NPPES registry. Deactivated NPIs return nothing and
are recorded as unknown (state null), never guessed.

Usage (from backend/):
    G:\\Python311\\python.exe -X utf8 scripts\\fetch_practice_states.py
"""
import json
import pathlib
import sys
import time
import urllib.request

_BACKEND = pathlib.Path(__file__).parent.parent
OUT = _BACKEND / "perse_practice_states.json"
API = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}"


def lookup(npi: str) -> dict:
    """One NPPES lookup. Returns {state, name, address_state_source} or state=None."""
    try:
        with urllib.request.urlopen(API.format(npi=npi), timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # network/parse: leave unknown, retry next run
        return {"state": None, "error": str(e)[:80]}
    results = data.get("results") or []
    if not results:
        return {"state": None, "not_found": True}
    rec = results[0]
    addrs = rec.get("addresses") or []
    loc = next((a for a in addrs if a.get("address_purpose") == "LOCATION"), addrs[0] if addrs else {})
    basic = rec.get("basic") or {}
    name = basic.get("organization_name") or " ".join(
        x for x in (basic.get("first_name"), basic.get("last_name")) if x)
    return {"state": loc.get("state") or None, "name": name}


def main() -> int:
    npis: set[str] = set()
    for fname, key in (("enrollment_leads.json", "leads"), ("perse_leads.json", "leads")):
        try:
            blob = json.loads((_BACKEND / fname).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = blob.get(key) or []
        rows = rows.values() if isinstance(rows, dict) else rows
        npis |= {r["npi"] for r in rows if r.get("npi") and r.get("kind") in
                 ("paid_while_terminated", "medicare_revoked_billing", "active_exclusion")}
    try:
        cache = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    todo = sorted(n for n in npis if n not in cache or cache[n].get("error"))
    print(f"{len(npis):,} lead NPIs, {len(todo):,} to look up")
    for i, npi in enumerate(todo, 1):
        cache[npi] = lookup(npi)
        if i % 25 == 0:
            OUT.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
            print(f"  {i}/{len(todo)}")
        time.sleep(0.25)
    OUT.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    known = sum(1 for v in cache.values() if v.get("state"))
    print(f"wrote {len(cache):,} entries ({known:,} with a practice state) -> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
