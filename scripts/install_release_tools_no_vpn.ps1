$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python venv was not found: $python"
}

function Test-PyInstaller {
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $python -m PyInstaller --version 1>$null 2>$null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
}

function Test-ElectronRuntime {
    $electronExe = Join-Path $root "node_modules\electron\dist\electron.exe"
    return Test-Path -LiteralPath $electronExe
}

function Install-PyInstaller {
    if (Test-PyInstaller) {
        Write-Host "PyInstaller is already installed."
        return
    }

    $indexes = @(
        @{ Url = "https://pypi.org/simple"; Host = "pypi.org files.pythonhosted.org" },
        @{ Url = "https://pypi.tuna.tsinghua.edu.cn/simple"; Host = "pypi.tuna.tsinghua.edu.cn" },
        @{ Url = "https://mirrors.aliyun.com/pypi/simple"; Host = "mirrors.aliyun.com" },
        @{ Url = "https://pypi.mirrors.ustc.edu.cn/simple"; Host = "pypi.mirrors.ustc.edu.cn" }
    )

    foreach ($index in $indexes) {
        Write-Host "Trying PyInstaller from $($index.Url)..."
        $trustedArgs = @()
        foreach ($hostName in $index.Host.Split(" ")) {
            if ($hostName.Trim()) {
                $trustedArgs += @("--trusted-host", $hostName.Trim())
            }
        }
        & $python -m pip install --upgrade pyinstaller --index-url $index.Url @trustedArgs
        if ($LASTEXITCODE -eq 0 -and (Test-PyInstaller)) {
            Write-Host "PyInstaller installed."
            return
        }
    }

    throw "Failed to install PyInstaller from all configured indexes."
}

function Install-ElectronRuntime {
    if (Test-ElectronRuntime) {
        Write-Host "Electron runtime is already installed."
        return
    }

    $mirrors = @(
        "",
        "https://npmmirror.com/mirrors/electron/",
        "https://registry.npmmirror.com/-/binary/electron/"
    )

    foreach ($mirror in $mirrors) {
        if ($mirror) {
            Write-Host "Trying Electron runtime from $mirror..."
            $env:ELECTRON_MIRROR = $mirror
            $env:npm_config_electron_mirror = $mirror
        } else {
            Write-Host "Trying Electron runtime from the default source..."
            Remove-Item Env:\ELECTRON_MIRROR -ErrorAction SilentlyContinue
            Remove-Item Env:\npm_config_electron_mirror -ErrorAction SilentlyContinue
        }

        & npx.cmd install-electron --no
        if ($LASTEXITCODE -eq 0 -and (Test-ElectronRuntime)) {
            Write-Host "Electron runtime installed."
            Remove-Item Env:\ELECTRON_MIRROR -ErrorAction SilentlyContinue
            Remove-Item Env:\npm_config_electron_mirror -ErrorAction SilentlyContinue
            return
        }
    }

    Remove-Item Env:\ELECTRON_MIRROR -ErrorAction SilentlyContinue
    Remove-Item Env:\npm_config_electron_mirror -ErrorAction SilentlyContinue
    throw "Failed to install Electron runtime from all configured mirrors."
}

Install-PyInstaller
Install-ElectronRuntime

Write-Host ""
Write-Host "Release tools are ready."
Write-Host "Now run:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release.ps1"
