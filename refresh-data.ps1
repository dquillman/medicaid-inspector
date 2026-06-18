<#
.SYNOPSIS
  Medicaid Inspector — one-button data refresh + freshness check.

.DESCRIPTION
  -Smart                 : THE one button. Checks what's needed and does ONLY that —
                           says "already up to date" (fast, no work) or downloads +
                           rebuilds + publishes the update. Used by "Update App Data.cmd".
  No args                : show the data-freshness table (local vs GCS, what's stale).
  -CheckSource           : ask HHS (Hugging Face) whether a newer dataset release exists.
  -Ingest                : download the latest HHS source parquet + normalize it locally.
  -Update                : rebuild full cache -> indexes -> prod slim cache -> upload to GCS.
  -Update -Deploy        : also ship a fresh Cloud Run revision so prod re-downloads now.
  Extra flags:
    -Force               : (with -Ingest) re-ingest even if the source SHA is unchanged.
    -Download            : (with -Update) first mirror the parquet from GCS to local.
    -UploadParquet       : (with -Update) also upload the local parquet (implied after -Ingest).
    -WithDeactivations   : (with -Update) also rebuild the NPPES deactivated-NPI lookup.

  -Ingest, -Update, and -Deploy chain in that order, so the full hands-off update is:
    .\refresh-data.ps1 -Ingest -Update -Deploy
  (-Ingest needs a free Hugging Face token in $env:HF_TOKEN — see ingest_source_parquet.py.)

.EXAMPLE
  .\refresh-data.ps1
  .\refresh-data.ps1 -CheckSource
  .\refresh-data.ps1 -Ingest -Update -Deploy
#>
[CmdletBinding()]
param(
  [switch]$Smart,
  [switch]$CheckSource,
  [switch]$Ingest,
  [switch]$Update,
  [switch]$Deploy,
  [switch]$Force,
  [switch]$Download,
  [switch]$UploadParquet,
  [switch]$WithDeactivations
)

# NOT 'Stop': under Stop, a native command (python/gcloud) writing ANY line to
# stderr — e.g. a non-fatal "[gcs_sync] Failed to upload" warning — is turned
# into a terminating NativeCommandError and aborts the whole run even though the
# command exited 0. We gate on explicit $LASTEXITCODE checks + throws instead.
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot

# G:\Python311 is the only interpreter with the full backend deps (duckdb,
# sklearn, google-cloud-storage) AND working application-default credentials.
$py = 'G:\Python311\python.exe'
if (-not (Test-Path $py)) { throw "Python interpreter not found at $py" }

$script = Join-Path $root 'backend\scripts\refresh_data.py'
$ingestScript = Join-Path $root 'backend\scripts\ingest_source_parquet.py'

function Invoke-Deploy {
  Write-Host "==> Publishing a fresh backend revision..." -ForegroundColor Cyan
  # gcloud on this box must use the SDK's bundled python (the store python 3.13
  # is missing cryptography), and ADMIN_PASSWORD comes from Secret Manager.
  $env:CLOUDSDK_PYTHON = 'G:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\platform\bundledpython\python.exe'
  $env:TMP = 'G:\temp'; $env:TMPDIR = 'G:\temp'; $env:TEMP = 'G:\temp'
  $env:ADMIN_PASSWORD = (& gcloud secrets versions access latest --secret=admin-password --project=medicaid-inspector)
  if ([string]::IsNullOrWhiteSpace($env:ADMIN_PASSWORD)) { throw "ADMIN_PASSWORD came back empty - check gcloud/CLOUDSDK_PYTHON" }
  & bash deploy-backend.sh
  if ($LASTEXITCODE -ne 0) { throw "Backend deploy failed (exit $LASTEXITCODE)" }
  Write-Host "==> Deploy complete." -ForegroundColor Green
}

# -Smart: THE one-button path (used by the "Update App Data" desktop button).
# Checks what's needed, does only that, and deploys iff it actually rebuilt
# something. Exit codes are interpreted by the caller:
#   10 = already up to date (no work, no deploy)    2 = token setup needed
#    0 = work done + deployed                      else = error
if ($Smart) {
  & $py -X utf8 $script smart
  $rc = $LASTEXITCODE
  if ($rc -eq 10) { exit 10 }
  if ($rc -eq 2)  { exit 2 }
  if ($rc -ne 0)  { throw "Update failed (exit $rc)" }
  Invoke-Deploy
  Write-Host "==> Done - your data is updated and live." -ForegroundColor Green
  exit 0
}

# -CheckSource: just ask HHS whether a newer release exists, then stop.
if ($CheckSource -and -not ($Ingest -or $Update)) {
  & $py -X utf8 $ingestScript check
  exit $LASTEXITCODE
}

# Default (no action switch): show the freshness table.
if (-not ($Ingest -or $Update -or $Deploy)) {
  & $py -X utf8 $script status
  exit $LASTEXITCODE
}

# -Ingest: pull + normalize the latest HHS source parquet. A successful ingest
# means the local parquet is new, so the subsequent -Update must upload it.
if ($Ingest) {
  Write-Host "==> Ingesting latest HHS source parquet..." -ForegroundColor Cyan
  $ingestArgs = @('ingest')
  if ($Force) { $ingestArgs += '--force' }
  & $py -X utf8 $ingestScript @ingestArgs
  if ($LASTEXITCODE -ne 0) { throw "Source ingest failed (exit $LASTEXITCODE)" }
  $UploadParquet = $true
}

if ($Update) {
  # Build the update arg list from the switches.
  $updateArgs = @('update', '--yes')
  if ($Download)          { $updateArgs += '--download' }
  if ($UploadParquet)     { $updateArgs += '--upload-parquet' }
  if ($WithDeactivations) { $updateArgs += '--with-deactivations' }

  Write-Host "==> Running data rebuild + upload..." -ForegroundColor Cyan
  & $py -X utf8 $script @updateArgs
  if ($LASTEXITCODE -ne 0) { throw "Data refresh failed (exit $LASTEXITCODE)" }
}

if ($Deploy) {
  Invoke-Deploy
}

Write-Host "==> Refresh complete. Run '.\refresh-data.ps1' to see the new freshness table." -ForegroundColor Green
