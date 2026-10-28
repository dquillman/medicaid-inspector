"""Create synthetic aggregate-only hosted-validation inputs, without cloud access.

Never reads auth, cases, outcomes, evidence or operator billing caches. Public
reference snapshots are copied byte-for-byte and checked for identity collision.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

_BACKEND = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://storage.googleapis.com/medicaid-inspector-staging-validation/medicaid-provider-spending.parquet"
PUBLIC_REFERENCES = ("oig_exclusions.json", "npi_deactivations.json", "medicare_revocations.json", "enrollment_cache.json")


def _write(path, value):
    path.write_text(json.dumps(value, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def _identifiers(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).isascii() and str(key).isdigit() and len(str(key)) == 10:
                yield str(key)
            yield from _identifiers(item)
    elif isinstance(value, list):
        for item in value:
            yield from _identifiers(item)
    elif isinstance(value, str) and value.isascii() and value.isdigit() and len(value) == 10:
        yield value


def build_fixture(output: Path, source_url: str = SOURCE_URL) -> dict:
    output = output.resolve()
    allowed = (_BACKEND / ".tmp").resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Fixture output must be a new directory beneath backend/.tmp")
    if output.exists():
        raise ValueError("Refusing to overwrite any existing fixture directory")
    if source_url != SOURCE_URL:
        raise ValueError("Only the named private staging-bucket source URI is permitted")
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))
    from core.identity_contract import is_valid_npi
    from services.artifact_provenance import build_manifest, file_sha256
    from services.claim_patterns import SPEC_VERSION
    from scripts.build_network_index import build_network_index
    import duckdb

    # Reserved-for-this-test 9-prefixed checksum-valid strings are synthetic
    # identifiers, never assertions that NPPES assigned these NPIs.
    ids = [next(f"9{ordinal:08d}{digit}" for digit in range(10)
                if is_valid_npi(f"9{ordinal:08d}{digit}")) for ordinal in range(256)]
    references = []
    for name in PUBLIC_REFERENCES:
        path = _BACKEND / name
        if path.exists():
            if set(ids).intersection(_identifiers(json.loads(path.read_text(encoding="utf-8")))):
                raise ValueError("Synthetic identifier collides with public reference snapshot")
            references.append(path)
    output.mkdir(parents=True)
    (output / "data").mkdir()
    for source in references:
        shutil.copy2(source, output / source.name)
        if file_sha256(source) != file_sha256(output / source.name):
            raise ValueError("Public reference copy differs from original")

    dataset = output / "data" / "medicaid-provider-spending.parquet"
    con = duckdb.connect(":memory:", config={"autoinstall_known_extensions": "false", "autoload_known_extensions": "false", "threads": "2"})
    con.execute("CREATE TABLE fixture_identifiers(i INTEGER, npi VARCHAR)")
    con.executemany("INSERT INTO fixture_identifiers VALUES (?, ?)", list(enumerate(ids)))
    con.execute("""CREATE TABLE synthetic_aggregates AS
        SELECT b.npi AS BILLING_PROVIDER_NPI_NUM,
               CASE WHEN hash(b.i,m.i,c.i,17)%17=0 THEN NULL
                    WHEN hash(b.i,m.i,c.i,19)%19=0 THEN 'null'
                    ELSE s.npi END AS SERVICING_PROVIDER_NPI_NUM,
               list_extract(['99213','99214','G0299','J0129','T1019','A0428'], c.i+1) AS HCPCS_CODE,
               strftime(DATE '2018-01-01' + CAST(m.i AS INTEGER)*INTERVAL '1 month','%Y-%m') AS CLAIM_FROM_MONTH,
               (100 + (hash(b.i,m.i,c.i,42)%100000000)/100.0)::DOUBLE AS TOTAL_PAID,
               ((12+hash(b.i,m.i,c.i,11)%89)*(1+hash(b.i,m.i,c.i,12)%4))::BIGINT AS TOTAL_CLAIMS,
               (12+hash(b.i,m.i,c.i,11)%89)::BIGINT AS TOTAL_UNIQUE_BENEFICIARIES
        FROM fixture_identifiers b CROSS JOIN range(84) m(i) CROSS JOIN range(6) c(i)
        JOIN fixture_identifiers s ON s.i=(b.i+1)%256
        """)
    con.execute("COPY synthetic_aggregates TO ? (FORMAT PARQUET, COMPRESSION UNCOMPRESSED)", [str(dataset)])
    if dataset.stat().st_size <= 1_000_000 or dataset.read_bytes()[:4] != b"PAR1":
        raise ValueError("Synthetic Parquet must satisfy the real local-loader size/magic guard")
    cursor = con.execute("""SELECT BILLING_PROVIDER_NPI_NUM AS npi, SUM(TOTAL_PAID) AS total_paid,
        SUM(TOTAL_CLAIMS) AS total_claims, SUM(TOTAL_UNIQUE_BENEFICIARIES) AS total_beneficiaries,
        COUNT(DISTINCT HCPCS_CODE) AS distinct_hcpcs, COUNT(DISTINCT CLAIM_FROM_MONTH) AS active_months,
        MIN(CLAIM_FROM_MONTH) AS first_month, MAX(CLAIM_FROM_MONTH) AS last_month
        FROM synthetic_aggregates GROUP BY 1 ORDER BY 1""")
    columns = [item[0] for item in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    positions = {identifier: index for index, identifier in enumerate(ids)}
    for row in rows:
        ordinal = positions[row["npi"]]
        name = f"SYNTHETIC STAGING FIXTURE {ordinal:03d} - NOT A REAL PROVIDER"
        row.update(provider_name=name, specialty="Synthetic aggregate test fixture", state="ZZ", city="SYNTHETIC", zip="00000",
                   risk_score=0, flags=[], flag_count=0, top_hcpcs="99213", synthetic_fixture=True,
                   summed_beneficiary_count=row["total_beneficiaries"],
                   beneficiary_count_semantics="provider_hcpcs_month_sum_not_unique_patients",
                   scoring_metadata={"status": "synthetic_fixture_unscored", "limitations": ["Zero is an unscored fixture placeholder, not a fraud judgment."]},
                   nppes={"name": name, "entity_type": "NPI-2", "status": "SYNTHETIC_UNVERIFIED",
                          "address": {"line1": "SYNTHETIC TEST ADDRESS", "city": "SYNTHETIC", "state": "ZZ", "zip": "00000"},
                          "taxonomy": {"description": "Synthetic aggregate test fixture", "code": ""},
                          "synthetic_fixture": True})
        row["claims_per_beneficiary"] = row["total_claims"] / row["total_beneficiaries"]
        row["revenue_per_beneficiary"] = row["total_paid"] / row["total_beneficiaries"]
    payload = {"providers": rows, "parquet_url": source_url, "synthetic_fixture": True,
               "scan_progress": {"offset": len(rows), "total_provider_count": len(rows), "batches_completed": 1}}
    for name in ("prescan_cache.json", "prescan_slim.json"):
        _write(output / name, payload)
    provenance = build_manifest(output / "prescan_cache.json", source_url, SPEC_VERSION,
                                {"start": "2018-01", "end": "2024-12", "basis": "synthetic generated fixture; not public billing evidence"},
                                output / "prescan_slim.json")
    provenance["synthetic_fixture"] = True
    provenance["limitations"].append("Entire billing and enrichment payload is synthetic, unscored, and unsuitable for investigation or effectiveness claims.")
    _write(output / "precomputed_analyses.json", {"generated_at": datetime.now(timezone.utc).isoformat(),
           "spec_version": SPEC_VERSION, "provider_count": len(rows), "provenance": provenance,
           "synthetic_fixture": True, "claim_patterns": {"unbundling": [], "duplicates": [], "pos": [], "modifiers": [], "impossible": []},
           "note": "Controlled synthetic fixture; no outcomes, external corroboration or clinical findings."})
    network_rows = build_network_index(dataset, output / "network_index.parquet")
    _write(output / "review_queue.json", {"items": []})
    _write(output / "referrals.json", {"referrals": [], "next_id": 1})
    _write(output / "oig_tips.json", {"tips": []})
    _write(output / "perse_leads.json", {"leads": [], "synthetic_fixture": True})
    _write(output / "evidence_metadata.json", {"evidence": {}})
    counts = {"providers": len(rows), "months": 84, "hcpcs_codes": 6,
              "aggregate_rows": con.execute("SELECT COUNT(*) FROM synthetic_aggregates").fetchone()[0],
              "network_index_rows": network_rows, "operator_cases": 0, "outcomes": 0}
    con.close()
    manifest = {"purpose": "synthetic-hosted-validation-fixture", "source_url": source_url,
                "counts": counts, "duckdb_version": duckdb.__version__, "synthetic_identity_registry_verified": False,
                "reference_collision_check": "No generated identifiers match copied public reference identifiers",
                "reference_files": [path.name for path in references],
                "model_state": "No trained models or supervised outcomes supplied",
                "limitations": ["Public reference snapshots are unchanged; all billing/enrichment is synthetic.",
                                "This fixture tests application functionality, not fraud validity or public dataset freshness."],
                "files": [{"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
                          for path in sorted(output.rglob("*")) if path.is_file()]}
    _write(output / "fixture_manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=_BACKEND / ".tmp" / "hosted-fixture-20261027")
    args = parser.parse_args()
    manifest = build_fixture(args.output)
    print(json.dumps({"status": "created", "counts": manifest["counts"], "files": manifest["files"]}, separators=(",", ":")))


if __name__ == "__main__":
    main()
