$ErrorActionPreference = 'Stop'
$taskHere = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskRoot = [IO.Path]::GetFullPath((Join-Path $taskHere '..\..'))
$taskPython = Join-Path $taskHere '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & py -3.12 -m venv (Join-Path $taskHere '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 first.' }
}
& $taskPython -m pip install --extra-index-url https://download.pytorch.org/whl/cu128 -r (Join-Path $taskHere 'requirements-runtime-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependency installation failed.' }
Push-Location $taskRoot
try {
    & $taskPython -m pip install -e '.[recording]'
    if ($LASTEXITCODE -ne 0) { throw 'Recording dependencies failed.' }
} finally { Pop-Location }
Write-Host 'Environment installed. Game has not been launched. Re-export TensorRT on a different GPU/runtime.'
