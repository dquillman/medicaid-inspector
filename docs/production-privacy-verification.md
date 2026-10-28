# Production privacy repair: read-only verification

Prepared helper: `backend/scripts/verify_production_privacy.py`. Preparation and
tests sent no production request. Root controls IAM changes and one-service-at-a-time
cutovers; this helper does not deploy, prewarm a revision, modify IAM, log in,
create sessions, submit cases or retrieve private operational object contents.
A production process startup can write state, so no no-traffic prewarm is assumed.

The private approved resources JSON must contain:

- approved_production_privacy_readonly: true
- services: exactly the names medicaid-inspector-api and medicaid-inspector,
  each with its exact HTTPS Cloud Run URL and optional expected revision.
- public_source_bucket: the separately approved dataset-only bucket.
- public_source_url: its exact medicaid-provider-spending.parquet public URL.

The old operational bucket medicaid-inspector-data cannot be selected as a public
source. URLs with credentials, queries, ports or redirect destinations are refused.
No authentication token or production admin secret is requested by this helper.

Plan only (default, no requests):

```
G:/Python311/python.exe backend/scripts/verify_production_privacy.py PRIVATE_RESOURCES.json
```

After root explicitly authorizes each verification step, run against the service
that has just completed its controlled source-URL cutover:

```
G:/Python311/python.exe backend/scripts/verify_production_privacy.py PRIVATE_RESOURCES.json --execute --service medicaid-inspector-api --source-query --raw-aggregate --output NEW_PRIVATE_REPORT.json
```

Repeat with --service medicaid-inspector only after its approved cutover. Do not
start both cutovers or background warmup tasks together. Preserve the before/after
revision metadata and the effective PARQUET_URL separately, extracted from Cloud
Run service/revision metadata without dumping other environment values or secrets.
The report's expected_revision is supplied evidence context, not live confirmation
that a given request reached that revision. Check traffic and effective environment
metadata directly before claiming the cutover completed.

## Checks and exact scope

The helper performs anonymous /health and /ready GETs, and unauthenticated admin
data-source/schema status GETs. Auth-protected routes must deny access. Their denial
is recorded as a limit: no authenticated data-source or case workflow was exercised.
/ready proves only what that endpoint implements (currently connection readiness),
not that the configured public Parquet URL has been read successfully.

The new approved public object gets HEAD and an explicit bytes=0-3 range request.
The response must be206 with PAR1 magic. Only size, ETag and generation metadata
are included. The optional DuckDB source check runs externally in an in-memory
connection against that exact public URL, reads schema/footer metadata, and verifies
required columns. No app imports or local production cache mutations occur.
--raw-aggregate additionally computes counts/payment/claim totals over at most the
first1000 rows. These are labeled sampled totals, not dataset-wide totals. Column
chunks/row-group transfer can exceed1000 rows; this remains a bounded result query,
not a guaranteed byte cap. No provider identifiers or example records are emitted.
DuckDB must already have httpfs available; auto-install is disabled. If unavailable,
report that check unavailable rather than silently claiming source verification.

After root removes the private bucket's public grant, the helper sends anonymous
HEAD only to the known operational objects users.json and app.db in
medicaid-inspector-data. No response body is read and no private GET/range request
exists. Exactly403 is required;404 does not establish denial of a known existing
object. No operational object listing, content retrieval or authenticated probe is
performed. Preserve root's IAM-policy metadata plus the denied HEAD statuses.

Check generation/CRC/size copy provenance separately using metadata-only evidence
from root's completed public dataset copy. Byte identity of the public dataset is
not inferred from a matching row count or sampled total alone. Record the original
and new generation/CRC evidence without retrieving private operational data.

## Reporting

New reports are exclusive-create JSON; existing evidence is never overwritten.
Report HTTP statuses, expected revisions, source schema/footer counts and optional
sampled aggregate totals. Never include provider identities, auth responses, secret
values, raw operational JSON or case data. Schema/read failures fail requested
checks; an HTTP-only success does not imply DuckDB success. The helper performs
no retries or writes beyond the chosen local report file. Production repair and
privacy claims require the actual revision, IAM and source-copy evidence alongside
these read-only probes.
