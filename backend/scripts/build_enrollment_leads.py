"""
Medicaid Provider Enrollment Segments -> backend/enrollment_leads.json.

HHS "Medicaid Provider Enrollment Segments" (T-MSIS, free, no DUA): one row per
NPI x state x enrollment period, with a status. Two things come out of it:

1. Per-se leads: the provider was ENROLLED, then terminated FOR CAUSE, and
   Medicaid still paid it for WHOLE months inside the termination while it had
   NO active enrollment in ANY state. The spend file has no billing state, so
   "any state" is the conservative test: a provider still enrolled somewhere
   else is never flagged.
2. backend/npi_states.json: enrolled state(s) per billing NPI, used offline by
   build_perse_sweep.py to fill the state the spend parquet lacks.

Kept strict on purpose, measured 2026-10-22:
  * "ACTIVE - ACTIVE DO NOT PAY" is a state coding habit, not a bar: 7,722
    "leads" / $2.6B, almost all CA, NY, WI and DE, paid every month for seven
    years (county agencies, fiscal intermediaries). Not used.
  * A termination with no ACTIVE enrollment before it (149 of 284) looks like
    incomplete state reporting. Not used. 135 remain.

Usage (from backend/):
    G:\\Python311\\python.exe -X utf8 scripts\\build_enrollment_leads.py
    then scripts\\build_perse_sweep.py (merges these leads in)
"""
import functools
import json
import pathlib
import sys
import time

print = functools.partial(print, flush=True)  # noqa: A001

_BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))
OUT = _BACKEND / "enrollment_leads.json"

SOURCE_URL = ("https://stopendataprod.blob.core.windows.net/datasets/"
              "medicaid-provider-enrollment-segments/2026-07-24/dataset/"
              "medicaid-provider-enrollment-segments.parquet")
LOCAL = pathlib.Path("G:/temp/hhs_enrollment/medicaid-provider-enrollment-segments.parquet")

# Terminations FOR CAUSE. Voluntary, no-claims-activity, license-expired and
# "other"/"unknown" terminations are administrative and left out.
FOR_CAUSE = (
    "TERM - ACTION TAKEN BY MEDICAID/CHIP",
    "TERM - MEDICARE/MEDICAID EXCLUSION",
    "TERM - STATE EXCLUSION/ DEBARMENT, ETC.",
    "TERM - FEDERAL EXCLUSION/ DEBARMENT, ETC.",
    "TERM - FELONY CONVICTION",
    "TERM - ABUSE OF BILLING PRIVILEGES",
    "TERM - MISUSE OF BILLING NUMBER",
    "TERM - FALSE OR MISLEADING INFORMATION",
    "TERM - LICENSE REVOKED",
    "TERM - LOSS OF LICENSE OR OTHER STATE ACTION",
    "TERM - MEDICARE TERMINATION",
    "TERM - ACTION TAKEN BY MEDICARE",
    "TERM - INVOLUNTARY TERMINATION",
    "TERM - ONSITE REVIEW/ PROVIDER IS NO LONGER OPERATIONAL",
)
DO_NOT_PAY = "ACTIVE - ACTIVE DO NOT PAY"
MIN_PAID = 1_000.0
STATES_OUT = _BACKEND / "npi_states.json"


def _sql_list(items) -> str:
    return ", ".join("'" + s.replace("'", "''") + "'" for s in items)


def main() -> int:
    import duckdb
    from data.duckdb_client import get_parquet_path

    started = time.time()
    src = str(LOCAL) if LOCAL.exists() else SOURCE_URL
    spend = get_parquet_path()
    print(f"enrollment: {src}\nspend:      {spend}")

    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET threads=4;")

    # Segments, with open/garbage dates clamped. NPI must be a real NPI.
    con.execute(f"""
        CREATE TEMP TABLE seg AS
        SELECT NPI AS npi, STATE_CD AS state, ENRL_STATUS_DESC AS status,
               GREATEST(COALESCE(ENRL_START_DT, DATE '2000-01-01'), DATE '2000-01-01') AS s,
               LEAST(COALESCE(ENRL_END_DT, DATE '2099-12-31'), DATE '2099-12-31') AS e
        FROM read_parquet('{src}')
        WHERE regexp_matches(NPI, '^[12][0-9]{{9}}$')
    """)
    con.execute(f"""
        CREATE TEMP TABLE act AS
        SELECT npi, s, e FROM seg
        WHERE status LIKE 'ACTIVE%' AND status <> '{DO_NOT_PAY}'
    """)
    # For-cause terminations that FOLLOW an active enrollment of the same NPI.
    con.execute(f"""
        CREATE TEMP TABLE bad AS
        SELECT t.* FROM seg t
        WHERE t.status IN ({_sql_list(FOR_CAUSE)})
          AND EXISTS (SELECT 1 FROM act a WHERE a.npi = t.npi AND a.s < t.s)
    """)
    n_bad = con.execute("SELECT count(DISTINCT npi) FROM bad").fetchone()[0]
    print(f"NPIs enrolled and then terminated for cause: {n_bad:,}")

    # Monthly billing for just those NPIs.
    con.execute(f"""
        CREATE TEMP TABLE bill AS
        SELECT p.BILLING_PROVIDER_NPI_NUM AS npi,
               CAST(strptime(p.CLAIM_FROM_MONTH || '-01', '%Y-%m-%d') AS DATE) AS ms,
               SUM(p.TOTAL_PAID) AS paid
        FROM read_parquet('{spend}') p
        WHERE p.BILLING_PROVIDER_NPI_NUM IN (SELECT DISTINCT npi FROM bad)
        GROUP BY 1, 2
    """)

    # A month counts only if a bad period covers ALL of it and no active
    # period touches ANY of it, in any state.
    rows = con.execute("""
        WITH m AS (
            SELECT npi, ms, (ms + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE AS me, paid FROM bill
        ),
        hit AS (
            SELECT m.npi, m.ms, m.paid,
                   arg_min(b.status, b.s) AS status, min(b.s) AS bad_since,
                   arg_min(b.state, b.s) AS bad_state
            FROM m JOIN bad b ON b.npi = m.npi AND b.s <= m.ms AND b.e >= m.me
            WHERE NOT EXISTS (SELECT 1 FROM act a WHERE a.npi = m.npi AND a.s <= m.me AND a.e >= m.ms)
            GROUP BY m.npi, m.ms, m.paid
        )
        SELECT npi, sum(paid) AS paid, count(*) AS months, min(ms), max(ms),
               arg_min(status, ms), min(bad_since), arg_min(bad_state, ms)
        FROM hit GROUP BY npi
    """).fetchall()

    # Where each billing NPI was enrolled (most segment-days first): the spend
    # file has no state, and per-se leads otherwise lose it.
    states = dict(con.execute(f"""
        SELECT npi, list(state ORDER BY days DESC) FROM (
            SELECT npi, state, sum(date_diff('day', s, LEAST(e, DATE '2024-12-31'))) AS days
            FROM seg
            WHERE npi IN (SELECT DISTINCT BILLING_PROVIDER_NPI_NUM FROM read_parquet('{spend}'))
            GROUP BY 1, 2
        ) GROUP BY npi
    """).fetchall())
    STATES_OUT.write_text(json.dumps(states, separators=(",", ":")), encoding="utf-8")
    print(f"enrolled states for {len(states):,} billing NPIs -> {STATES_OUT.name}")

    totals = dict(con.execute("SELECT npi, sum(paid) FROM bill GROUP BY 1").fetchall())

    # Audit 2026-10-28: the agents that re-checked the 109 strongest leads found
    # two ways this test lies, both fixable from the same file.
    #  * REINSTATED: a termination that a state later reversed (an ACTIVE
    #    enrollment starts after it) is a suspension that ended, not a provider
    #    kept on the payroll. 11 of 109 leads were exactly that.
    #  * BLIND STATES: some states (NM, OR) carry NO usable NPI in this file. A
    #    provider enrolled there looks "not enrolled anywhere", so the any-state
    #    test cannot be trusted for providers who practice in those states.
    reinstated = {r[0] for r in con.execute(
        "SELECT DISTINCT b.npi FROM bad b WHERE EXISTS "
        "(SELECT 1 FROM act a WHERE a.npi = b.npi AND a.s > b.s)").fetchall()}
    blind_states = sorted(r[0] for r in con.execute(f"""
        SELECT STATE_CD FROM read_parquet('{src}')
        GROUP BY 1 HAVING count(*) FILTER (WHERE regexp_matches(NPI, '^[12][0-9]{{9}}$'))
                          < 0.01 * count(*)
    """).fetchall() if r[0])
    print(f"states with (almost) no usable NPIs: {blind_states}")
    con.close()

    leads = {}
    for npi, paid, months, first, last, status, since, bad_state in rows:
        if (paid or 0) < MIN_PAID:
            continue
        leads[npi] = {
            "npi": npi,
            "kind": "paid_while_terminated",
            "enrollment_status": status,
            "terminated_since": since.isoformat() if since else None,
            "terminated_state": bad_state,
            "paid_while_terminated": round(float(paid), 2),
            "months_while_terminated": int(months),
            "first_month_while_terminated": first.strftime("%Y-%m"),
            "last_month_while_terminated": last.strftime("%Y-%m"),
            "total_paid": round(float(totals.get(npi) or 0), 2),
            "states": list(states.get(npi) or []),
            "reinstated_after": npi in reinstated,
            "caveat": ("Check that the state did not re-enroll this provider under another "
                       "Medicaid ID before filing."),
        }

    OUT.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": SOURCE_URL,
        "blind_states": blind_states,
        "leads": leads,
    }, separators=(",", ":")), encoding="utf-8")

    by_status: dict[str, list] = {}
    for r in leads.values():
        by_status.setdefault(r["enrollment_status"], []).append(r)
    print(f"\nwrote {len(leads):,} leads -> {OUT.name} ({time.time() - started:.0f}s)")
    for st, rs in sorted(by_status.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(rs):5,}  ${sum(r['paid_while_terminated'] for r in rs):>14,.0f}  {st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
