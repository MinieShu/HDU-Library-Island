$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppDir = Join-Path $RootDir "hdu_library_autobook"
$WebDir = Join-Path $AppDir "web"
$VenvDir = Join-Path $AppDir "venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Pause-IfNeeded {
    if ($env:HDU_NO_PAUSE -eq "1") {
        return
    }

    if ($Host.Name -eq "ConsoleHost") {
        Write-Host ""
        Read-Host "按回车键退出"
    }
}

function Test-PythonCommand {
    param([string]$Command, [string[]]$Arguments)

    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        return $false
    }

    & $Command @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        return $false
    }

    & node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Install-WithWinget {
    param([string]$PackageId, [string]$Name)

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        return $false
    }

    Write-Step "正在通过 winget 安装/更新 $Name"
    winget install --id $PackageId --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        winget upgrade --id $PackageId --source winget --accept-package-agreements --accept-source-agreements
    }
    return $true
}

function Ensure-SystemTools {
    if (-not (Test-PythonCommand -Command "py" -Arguments @("-3")) -and -not (Test-PythonCommand -Command "python" -Arguments @())) {
        if (-not (Install-WithWinget -PackageId "Python.Python.3.13" -Name "Python 3")) {
            Write-Host "未找到 Python 3.10+，也没有检测到 winget。"
            Write-Host "请安装 Python 3.10+，安装时勾选 Add python.exe to PATH。"
            Start-Process "https://www.python.org/downloads/windows/"
            throw "Python 3.10+ 不可用。"
        }
    }

    if (-not (Test-Node)) {
        if (-not (Install-WithWinget -PackageId "OpenJS.NodeJS.LTS" -Name "Node.js LTS")) {
            Write-Host "未找到 Node.js 18+ / npm，也没有检测到 winget。"
            Write-Host "请安装 Node.js LTS 后重新运行 setup.bat。"
            Start-Process "https://nodejs.org/"
            throw "Node.js 18+ / npm 不可用。"
        }
    }
}

function New-Venv {
    param([string]$TargetDir)

    if (Test-PythonCommand -Command "py" -Arguments @("-3")) {
        & py -3 -m venv $TargetDir
        return
    }

    if (Test-PythonCommand -Command "python" -Arguments @()) {
        & python -m venv $TargetDir
        return
    }

    throw "未找到 Python 3.10+。请先安装 Python，并勾选 Add python.exe to PATH。"
}

try {
    Ensure-SystemTools

    if (-not (Test-PythonCommand -Command "py" -Arguments @("-3")) -and -not (Test-PythonCommand -Command "python" -Arguments @())) {
        throw "Python 3.10+ 安装后仍不可用。请重新打开此脚本或检查 PATH。"
    }

    if (-not (Test-Node)) {
        throw "Node.js 18+ / npm 安装后仍不可用。请重新打开此脚本或检查 PATH。"
    }

    Write-Step "使用 Python 和 Node.js 环境"
    if (Get-Command node -ErrorAction SilentlyContinue) {
        Write-Host "Node.js $(node --version) / npm $(npm --version)"
    }

    Set-Location $AppDir

    if ((Test-Path $PythonExe)) {
        & $PythonExe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Step "现有虚拟环境 Python 版本过低，正在重建"
            Remove-Item -Recurse -Force $VenvDir
        }
    }

    if (-not (Test-Path $PythonExe)) {
        Write-Step "创建 Python 虚拟环境"
        New-Venv -TargetDir $VenvDir
    }

    Write-Step "安装/更新 Python 依赖"
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r requirements.txt

    Set-Location $WebDir
    Write-Step "安装/更新 Web 依赖"
    npm install

    Write-Host ""
    Write-Host "Windows 配置完成。现在可以双击 start.bat 启动。"
}
catch {
    Write-Host ""
    Write-Host "配置失败：$($_.Exception.Message)"
    Pause-IfNeeded
    exit 1
}

Pause-IfNeeded
