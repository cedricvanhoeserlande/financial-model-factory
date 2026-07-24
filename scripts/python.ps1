$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPYCACHEPREFIX = Join-Path $RepoRoot ".pycache"
if (-not $env:PYTHONIOENCODING) {
    $env:PYTHONIOENCODING = "utf-8"
}

$ConfiguredPython = $env:MODEL_FACTORY_PYTHON
if ($ConfiguredPython) {
    & $ConfiguredPython @args
} else {
    & python @args
}
exit $LASTEXITCODE
