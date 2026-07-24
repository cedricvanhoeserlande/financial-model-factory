$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "python.ps1") (Join-Path $RepoRoot "run_local.py") @args
exit $LASTEXITCODE
