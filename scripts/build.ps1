param()

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Validator = Join-Path $ScriptRoot 'validate.py'

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    throw 'Python 3 was not found in PATH.'
}

& $Python.Source $Validator --build --verify-downloads
if ($LASTEXITCODE -ne 0) {
    throw "Aeronautica build failed with exit code $LASTEXITCODE."
}
