$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "python.ps1") -m unittest @args
exit $LASTEXITCODE
