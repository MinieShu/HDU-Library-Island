$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppDir = Join-Path $RootDir "hdu_library_autobook"
$WebDir = Join-Path $AppDir "web"
$SetupScript = Join-Path $RootDir "scripts\setup_windows.ps1"
$PythonExe = Join-Path $AppDir "venv\Scripts\python.exe"
$NodeModules = Join-Path $WebDir "node_modules"

function Test-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        return $false
    }

    & node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-PythonDeps {
    if (-not (Test-Path $PythonExe)) {
        return $false
    }

    & $PythonExe -c "import fastapi, uvicorn, PyQt6, requests" 2>$null
    return $LASTEXITCODE -eq 0
}

try {
    if (-not (Test-Path $PythonExe) -or -not (Test-Path $NodeModules) -or -not (Test-Node) -or -not (Test-PythonDeps)) {
        Write-Host "检测到环境未配置或依赖不完整，正在自动配置..."
        $env:HDU_NO_PAUSE = "1"
        & $SetupScript
        Remove-Item Env:\HDU_NO_PAUSE -ErrorAction SilentlyContinue
    }

    $ApiCommand = "Set-Location '$RootDir'; & '$PythonExe' -m hdu_library_autobook.web_api"
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $ApiCommand
    ) | Out-Null

    Set-Location $WebDir
    npm run dev -- --host 127.0.0.1 --open
}
catch {
    Write-Host ""
    Write-Host "启动失败：$($_.Exception.Message)"
    Read-Host "按回车键退出"
    exit 1
}
