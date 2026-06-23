param(
    [switch]$AllowCachedElectronFallback
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$package = Get-Content -LiteralPath "package.json" -Encoding UTF8 | ConvertFrom-Json
$version = [string]$package.version
$appId = "DBD-Autoclicker-Bloodweb"
$releaseRoot = Join-Path $root "release"
$portableName = "$appId-v$version-win-x64"
if ($AllowCachedElectronFallback) {
    $portableName = "$portableName-preview"
}
$portableDir = Join-Path $releaseRoot $portableName
$zipPath = Join-Path $releaseRoot "$portableName.zip"
$electronDist = Join-Path $root "node_modules\electron\dist"
$runtimeVersion = ""

function Remove-PathIfExists($path) {
    if (-not (Test-Path -LiteralPath $path)) {
        return
    }
    $resolved = Resolve-Path -LiteralPath $path
    $releaseResolved = if (Test-Path -LiteralPath $releaseRoot) { Resolve-Path -LiteralPath $releaseRoot } else { $null }
    if ($releaseResolved -and -not $resolved.Path.StartsWith($releaseResolved.Path, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove outside release directory: $($resolved.Path)"
    }
    Remove-Item -LiteralPath $resolved.Path -Recurse -Force
}

function Copy-Directory($source, $destination, [string[]]$excludeNames = @()) {
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Missing directory: $source"
    }
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
        if ($excludeNames -contains $_.Name) {
            return
        }
        $target = Join-Path $destination $_.Name
        if ($_.PSIsContainer) {
            Copy-Directory $_.FullName $target $excludeNames
        } else {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}

function Ensure-ElectronRuntime {
    $script:runtimeVersion = ""
    $electronExe = Join-Path $electronDist "electron.exe"
    if (Test-Path -LiteralPath $electronExe) {
        $script:runtimeVersion = "package"
        return
    }

    $electronVersion = [string]$package.devDependencies.electron
    $electronVersion = $electronVersion.TrimStart("^", "~", "=")
    $cacheZip = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "electron\Cache") -Recurse -File -Filter "electron-v$electronVersion-win32-x64.zip" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cacheZip) {
        New-Item -ItemType Directory -Force -Path $electronDist | Out-Null
        Expand-Archive -LiteralPath $cacheZip.FullName -DestinationPath $electronDist -Force
    }

    if (Test-Path -LiteralPath $electronExe) {
        $script:runtimeVersion = $electronVersion
        return
    }

    Write-Host "Electron runtime is missing. Trying to download Electron $electronVersion..."
    & npx.cmd install-electron --no
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $electronExe)) {
        if (-not $AllowCachedElectronFallback) {
            throw "Electron runtime is missing. Connect to the internet and run: npx.cmd install-electron --no"
        }
        $fallbackZip = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "electron\Cache") -Recurse -File -Filter "electron-v*-win32-x64.zip" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if (-not $fallbackZip) {
            throw "Electron runtime is missing and no cached fallback runtime was found."
        }
        $fallbackDist = Join-Path $releaseRoot "_electron_runtime_fallback"
        Remove-PathIfExists $fallbackDist
        New-Item -ItemType Directory -Force -Path $fallbackDist | Out-Null
        Expand-Archive -LiteralPath $fallbackZip.FullName -DestinationPath $fallbackDist -Force
        $script:electronDist = $fallbackDist
        $script:runtimeVersion = [System.IO.Path]::GetFileNameWithoutExtension($fallbackZip.Name)
        Write-Warning "Using cached fallback runtime $($fallbackZip.Name). This build is for local preview, not final public release."
        return
    }
    $script:runtimeVersion = $electronVersion
}

function Ensure-PyInstaller {
    & .venv\Scripts\python.exe -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is missing. Connect to the internet and run: .venv\Scripts\python.exe -m pip install pyinstaller"
    }
}

function Build-PythonBackend($destinationDir) {
    Ensure-PyInstaller
    $distPath = Join-Path $releaseRoot "_pyinstaller_dist"
    $buildPath = Join-Path $releaseRoot "_pyinstaller_build"
    $specPath = Join-Path $releaseRoot "_pyinstaller_spec"
    Remove-PathIfExists $distPath
    Remove-PathIfExists $buildPath
    Remove-PathIfExists $specPath
    New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null

    & .venv\Scripts\python.exe -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name electron_backend `
        --distpath $distPath `
        --workpath $buildPath `
        --specpath $specPath `
        --paths $root `
        app\electron_backend.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller backend build failed."
    }

    $backendExe = Join-Path $distPath "electron_backend.exe"
    if (-not (Test-Path -LiteralPath $backendExe)) {
        throw "PyInstaller did not produce electron_backend.exe."
    }
    Copy-Item -LiteralPath $backendExe -Destination (Join-Path $destinationDir "electron_backend.exe") -Force
}

function New-ReleaseReadme($path) {
    $content = @"
DBD Autoclicker Bloodweb v$version

Start:
1. Unpack the ZIP archive.
2. Run "DBD Autoclicker Bloodweb.exe".
3. Read the safety warning in the app before pressing Start.

The app stores user templates and settings locally inside this folder.
Do not run it unattended. F8 stops the autoclicker.

Official repository:
https://github.com/AurumWise/DBD-Autoclicker-Bloodweb
"@
    Set-Content -LiteralPath $path -Value $content -Encoding UTF8
}

& powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\check_release_files.ps1"
& .venv\Scripts\python.exe -B -m py_compile main.py app/runtime_config.py app/version.py app/vision/snippet_matcher.py app/data/search_template_repository.py app/electron_backend.py app/safety/center_anchor.py app/logging_setup.py app/grid/geometry.py
& npm.cmd run build:electron

Ensure-ElectronRuntime
Ensure-PyInstaller

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
Remove-PathIfExists $portableDir
Remove-PathIfExists $zipPath

Copy-Directory $electronDist $portableDir @()

$exe = Join-Path $portableDir "electron.exe"
$appExe = Join-Path $portableDir "DBD Autoclicker Bloodweb.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Electron executable was not found after copying runtime."
}
Rename-Item -LiteralPath $exe -NewName "DBD Autoclicker Bloodweb.exe"

$appDir = Join-Path $portableDir "resources\app"
New-Item -ItemType Directory -Force -Path $appDir | Out-Null

Copy-Directory (Join-Path $root "app") (Join-Path $appDir "app") @("__pycache__")
Copy-Directory (Join-Path $root "electron\dist") (Join-Path $appDir "electron\dist") @()
Copy-Directory (Join-Path $root "electron\renderer") (Join-Path $appDir "electron\renderer") @()
Build-PythonBackend (Join-Path $appDir "backend")
if (Test-Path -LiteralPath (Join-Path $root "gif")) {
    Copy-Directory (Join-Path $root "gif") (Join-Path $appDir "gif") @()
}

New-Item -ItemType Directory -Force -Path (Join-Path $appDir "db") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $appDir "logs") | Out-Null

Copy-Item -LiteralPath "package.json" -Destination (Join-Path $appDir "package.json") -Force
Copy-Item -LiteralPath "requirements.txt" -Destination (Join-Path $appDir "requirements.txt") -Force
Copy-Item -LiteralPath "README.md" -Destination (Join-Path $appDir "README.md") -Force
Copy-Item -LiteralPath "LICENSE.md" -Destination (Join-Path $appDir "LICENSE.md") -Force
Copy-Item -LiteralPath "DISCLAIMER.md" -Destination (Join-Path $appDir "DISCLAIMER.md") -Force
New-ReleaseReadme (Join-Path $portableDir "START_HERE.txt")
Set-Content -LiteralPath (Join-Path $portableDir "RUNTIME_VERSION.txt") -Value "Electron runtime: $runtimeVersion" -Encoding UTF8

Compress-Archive -LiteralPath $portableDir -DestinationPath $zipPath -Force

Remove-PathIfExists (Join-Path $releaseRoot "_pyinstaller_dist")
Remove-PathIfExists (Join-Path $releaseRoot "_pyinstaller_build")
Remove-PathIfExists (Join-Path $releaseRoot "_pyinstaller_spec")
Remove-PathIfExists (Join-Path $releaseRoot "_electron_runtime_fallback")

Write-Host "Release portable folder:"
Write-Host "  $portableDir"
Write-Host "Release ZIP:"
Write-Host "  $zipPath"
