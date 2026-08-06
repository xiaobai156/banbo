$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Resolve-PythonCommand {
    foreach ($candidate in @("py", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            & $candidate --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
    }
    throw "Cannot find a usable Python."
}

$python = Resolve-PythonCommand
$period = Read-Host "Enter period, for example 211. Press Enter to use the default prompt"
if ([string]::IsNullOrWhiteSpace($period)) {
    & $python -m banbo.cli
} else {
    & $python -m banbo.cli --period $period.Trim()
}
exit $LASTEXITCODE
