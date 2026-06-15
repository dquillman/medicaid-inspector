<#
.SYNOPSIS
  Medicaid Inspector — one-button data refresh + freshness check.

.DESCRIPTION
  No args                : show the data-freshness table (local vs GCS, what's stale).
  -Update                : rebuild full cache -> indexes -> prod slim cache -> upload to GCS.
  -Update -Deploy        : also ship a fresh Cloud Run revision so prod re-downloads now.
  Extra rebuild flags (with -Update):
    -Download            : first mirror the latest parquet from GCS to local.
    -UploadParquet       : also upload the local parquet (use when you supplied new source data).
    -WithDeactivations   : also rebuild the NPPES deactivated-NPI lookup.

.EXAMPLE
  .\refresh-data.ps1
  .\refresh-data.ps1 -Update
  .\refresh-data.ps1 -Update -UploadParquet -Deploy
#>
[CmdletBinding()]
param(
  [switch]$Update,
  [switch]$Deploy,
  [switch]$Download,
  [switch]$UploadParquet,
  [switch]$WithDeactivations
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# G:\Python311 is the only interpreter with the full backend deps (duckdb,
# sklearn, google-cloud-storage) AND working application-default credentials.
$py = 'G:\Python311\python.exe'
if (-not (Test-Path $py)) { throw "Python interpreter not found at $py" }

$script = Join-Path $root 'backend\scripts\refresh_data.py'

if (-not $Update) {
  & $py -X utf8 $script status
  exit $LASTEXITCODE
}

# Build the update arg list from the switches.
$updateArgs = @('update', '--yes')
if ($Download)          { $updateArgs += '--download' }
if ($UploadParquet)     { $updateArgs += '--upload-parquet' }
if ($WithDeactivations) { $updateArgs += '--with-deactivations' }

Write-Host "==> Running data rebuild + upload..." -ForegroundColor Cyan
& $py -X utf8 $script @updateArgs
if ($LASTEXITCODE -ne 0) { throw "Data refresh failed (exit $LASTEXITCODE)" }

if ($Deploy) {
  Write-Host "==> Deploying a fresh backend revision so prod re-downloads the artifacts..." -ForegroundColor Cyan
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

Write-Host "==> Refresh complete. Run '.\refresh-data.ps1' to see the new freshness table." -ForegroundColor Green
