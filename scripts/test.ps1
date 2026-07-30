param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('prereqs', 'fast', 'artifact', 'client', 'server', 'gametest', 'worldgen', 'full')]
    [string]$Suite,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pipeline = Join-Path $ScriptRoot 'test_pipeline.py'

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    throw 'Python 3.11+ was not found in PATH.'
}

$Arguments = @($Pipeline, $Suite) + $ExtraArgs

& $Python.Source @Arguments
exit $LASTEXITCODE
