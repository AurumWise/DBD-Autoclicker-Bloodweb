$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

& .venv\Scripts\python.exe -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install PyInstaller."
}

& npx.cmd install-electron --no
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Electron runtime."
}

Write-Host "Release build tools are ready."
