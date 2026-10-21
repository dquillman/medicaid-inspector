"""
Medicare revocation list -> backend/medicare_revocations.json.

A provider whose Medicare enrollment CMS has REVOKED must also be terminated by
every state Medicaid program (42 CFR 455.416(c)). Medicaid billing after the
revocation is therefore a per-se lead, checkable with nothing but set
membership and a billing month — the same shape as the LEIE and deactivated-NPI
checks in build_perse_sweep.py.

Sources (both free, no DUA, no login):
  * CMS Revocation Extract, updated quarterly — the fresh list.
  * HHS Open Data snapshot (2026-02-14) — older, but it flattens the companion
    NPIs of multi-NPI enrollments into their own rows, which the CMS extract
    does not. Union of the two, keyed by NPI.

Output: {"generated_at", "sources": [...], "revocations": {npi: [record, ...]}}
One NPI can carry several revoked enrollments (different states / enrollment
IDs), so the value is a list. Each record:
  {enrollment_id, revocation_date (YYYY-MM-DD), reenrollment_bar_until,
   reason, state, provider_type, name}

Usage (from backend/):
    G:\\Python311\\python.exe -X utf8 scripts\\build_revocations.py
    then scripts\\build_perse_sweep.py
"""
import csv
import datetime as _dt
import io
import json
import pathlib
import re
import sys
import time
import urllib.request

_BACKEND = pathlib.Path(__file__).parent.parent
OUT = _BACKEND / "medicare_revocations.json"

CMS_URL = ("https://data.cms.gov/sites/default/files/2026-08/"
           "371a1652-c72d-4779-ad46-c733851aea67/Revocation_Extract_2026.07.30.csv")
HHS_URL = ("https://stopendataprod.blob.core.windows.net/datasets/"
           "medicare-revoked-providers-and-suppliers/2026-03-02/dataset/"
           "medicare-revoked-providers-and-suppliers.parquet")

_NPI_RE = re.compile(r"^[12]\d{9}$")


def _iso(s) -> str | None:
    """MM/DD/YYYY, YYYY-MM-DD or a date object -> YYYY-MM-DD."""
    if s is None or s == "":
        return None
    if isinstance(s, (_dt.date, _dt.datetime)):
        return s.strftime("%Y-%m-%d")
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _name(r: dict) -> str:
    org = (r.get("ORG_NAME") or "").strip()
    if org:
        return org
    return " ".join(p for p in ((r.get("FIRST_NAME") or "").strip(),
                                (r.get("LAST_NAME") or "").strip()) if p)


def _record(r: dict) -> dict:
    return {
        "enrollment_id": (r.get("ENRLMT_ID") or "").strip(),
        "revocation_date": _iso(r.get("REVOCATION_EFCTV_DT")),
        "reenrollment_bar_until": _iso(r.get("REENROLLMENT_BAR_EXPRTN_DT")),
        "reason": (r.get("REVOCATION_RSN") or "").strip(),
        "state": (r.get("STATE_CD") or "").strip(),
        "provider_type": (r.get("PROVIDER_TYPE_DESC") or "").strip(),
        "name": _name(r),
    }


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "medicaid-inspector/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def main() -> int:
    started = time.time()
    by_npi: dict[str, dict[tuple, dict]] = {}
    sources = []

    def add(r: dict, src: str) -> None:
        npi = (r.get("NPI") or "").strip()
        if not _NPI_RE.match(npi):
            return
        rec = _record(r)
        if not rec["revocation_date"]:
            return
        key = (rec["enrollment_id"], rec["revocation_date"])
        slot = by_npi.setdefault(npi, {})
        # The CMS extract is fresher, so it wins a tie with the HHS snapshot.
        if key not in slot or src == "cms":
            slot[key] = rec

    print("downloading CMS revocation extract…", flush=True)
    raw = _fetch(CMS_URL).decode("utf-8-sig", errors="replace")
    n = 0
    for r in csv.DictReader(io.StringIO(raw)):
        add(r, "cms"); n += 1
    sources.append({"name": "CMS Revocation Extract", "url": CMS_URL, "rows": n})
    print(f"  {n:,} rows", flush=True)

    try:
        import duckdb
        print("reading HHS snapshot (companion NPIs)…", flush=True)
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        cur = con.execute(f"SELECT * FROM read_parquet('{HHS_URL}')")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        for row in rows:
            add(dict(zip(cols, row)), "hhs")
        sources.append({"name": "HHS Open Data snapshot", "url": HHS_URL, "rows": len(rows)})
        print(f"  {len(rows):,} rows", flush=True)
    except Exception as e:  # noqa: BLE001 — the CMS list alone is still valid
        print(f"WARN: HHS snapshot skipped ({e})", flush=True)

    if not by_npi:
        print("ERROR: no revocations parsed — refusing to write an empty file.")
        return 1

    revs = {npi: sorted(slot.values(), key=lambda x: x["revocation_date"])
            for npi, slot in by_npi.items()}
    OUT.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": sources,
        "revocations": revs,
    }, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(revs):,} revoked NPIs -> {OUT.name} "
          f"({OUT.stat().st_size / 1024:.0f} KB, {time.time() - started:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
