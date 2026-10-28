"""Synthetic billing relationships never infer links from unavailable identity."""
import asyncio
import pytest
from core.identity_contract import is_valid_npi, valid_npi_sql


def _synthetic(prefix):
    return next(prefix + str(digit) for digit in range(10) if is_valid_npi(prefix + str(digit)))


@pytest.fixture
def dataset(tmp_path):
    import duckdb
    con = duckdb.connect(":memory:", config={"autoinstall_known_extensions": "false", "autoload_known_extensions": "false"})
    a, b = _synthetic("123456789"), _synthetic("111111111")
    con.execute("CREATE TABLE fixture(BILLING_PROVIDER_NPI_NUM VARCHAR, SERVICING_PROVIDER_NPI_NUM VARCHAR, TOTAL_PAID DOUBLE, TOTAL_CLAIMS BIGINT)")
    con.executemany("INSERT INTO fixture VALUES (?, ?, ?, ?)", [
        (a, b, 10, 1), (a, None, 20, 2), (a, "null", 30, 3),
        (a, "1234567890", 40, 4), ("1234567890", b, 50, 5), (b, b, 60, 6)])
    source = tmp_path / "synthetic.parquet"
    con.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(source)])
    yield con, source, a, b
    con.close()


def test_sql_and_python_identity_checks_agree(dataset):
    con, _, a, b = dataset
    for value in (a, b, "1234567890", "null", "", "0", "9999999999", None, "１２３４５６７８９３"):
        observed = con.execute("SELECT " + valid_npi_sql("npi") + " FROM (SELECT ? AS npi)", [value]).fetchone()[0]
        assert observed == is_valid_npi(value)
    with pytest.raises(ValueError):
        valid_npi_sql("npi); DROP TABLE fixture")


def test_index_excludes_invalid_edges_but_keeps_billing_self_totals(dataset, tmp_path):
    from scripts.build_network_index import build_network_index
    con, source, a, b = dataset
    output = tmp_path / "index.parquet"
    count = build_network_index(source, output)
    rows = con.execute("SELECT * FROM read_parquet(?)", [str(output)]).fetchall()
    assert count == 4
    assert all(is_valid_npi(row[0]) and is_valid_npi(row[1]) for row in rows)
    center = next(row for row in rows if row[0] == a and row[2] == "__center__")
    assert center[3:] == (100, 10)  # missing/malformed servicer does not erase legitimate billing total
    assert next(row for row in rows if row[0] == a and row[2] == "billing_to_servicing")[3] == 10


def test_live_network_and_legacy_index_revalidate_endpoints(dataset, monkeypatch):
    from routes import network
    con, source, a, b = dataset
    async def query(sql):
        cursor = con.execute(sql)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    monkeypatch.setattr(network, "query_async", query)
    monkeypatch.setattr(network, "get_parquet_path", lambda: source.as_posix())
    monkeypatch.setattr(network, "_index_available", lambda: False)
    live = asyncio.run(network.get_network(a))
    assert {node["id"] for node in live["nodes"]} == {a, b}
    assert live["nodes"][0]["total_paid"] == 100
    assert len(live["edges"]) == 1 and live["edges"][0]["weight"] == 10
    async def legacy_rows(sql):
        return [{"neighbor_npi": a, "edge_type": "__center__", "edge_weight": 100, "claim_count": 10},
                {"neighbor_npi": "null", "edge_type": "billing_to_servicing", "edge_weight": 30, "claim_count": 3},
                {"neighbor_npi": "1234567890", "edge_type": "billing_to_servicing", "edge_weight": 40, "claim_count": 4},
                {"neighbor_npi": b, "edge_type": "billing_to_servicing", "edge_weight": 10, "claim_count": 1}]
    monkeypatch.setattr(network, "_index_available", lambda: True)
    monkeypatch.setattr(network, "query_async", legacy_rows)
    cached = asyncio.run(network.get_network(a))
    assert {node["id"] for node in cached["nodes"]} == {a, b}
    assert len(cached["edges"]) == 1
    assert "no verified lineage manifest" in cached["coverage_caveat"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(network.get_network("1234567890"))
    assert rejected.value.status_code == 400
