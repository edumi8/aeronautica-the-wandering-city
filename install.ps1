param(
    [Parameter(Mandatory = $true)]
    [string]$InstancePath,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $ScriptRoot 'install.py'

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    throw 'Python 3 was not found in PATH.'
}

$Arguments = @($Installer, $InstancePath)
if ($DryRun) {
    $Arguments += '--dry-run'
}

& $Python.Source @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Aeronautica installer failed with exit code $LASTEXITCODE."
}
