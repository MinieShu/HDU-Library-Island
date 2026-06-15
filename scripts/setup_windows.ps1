$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppDir = Join-Path $RootDir "hdu_library_autobook"
$WebDir = Join-Path $AppDir "web"
$VenvDir = Join-Path $AppDir "venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

function New-Venv {
    param([string]$TargetDir)

    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & py -3 -m venv $TargetDir
            return
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & python -m venv $TargetDir
            return
        }
    }

    throw "未找到 Python 3.10+。请先安装 Python，并勾选 Add python.exe to PATH。"
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "未找到 npm。请先安装 Node.js 18 或更高版本。"
}

Set-Location $AppDir

if (-not (Test-Path $PythonExe)) {
    New-Venv -TargetDir $VenvDir
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r requirements.txt

Set-Location $WebDir
npm install

Write-Host "Windows 配置完成。"
