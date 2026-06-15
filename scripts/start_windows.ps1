$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppDir = Join-Path $RootDir "hdu_library_autobook"
$WebDir = Join-Path $AppDir "web"
$SetupScript = Join-Path $RootDir "scripts\setup_windows.ps1"
$PythonExe = Join-Path $AppDir "venv\Scripts\python.exe"
$NodeModules = Join-Path $WebDir "node_modules"

if (-not (Test-Path $PythonExe) -or -not (Test-Path $NodeModules)) {
    & $SetupScript
}

$ApiCommand = "Set-Location '$RootDir'; & '$PythonExe' -m hdu_library_autobook.web_api"
Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $ApiCommand
) | Out-Null

Set-Location $WebDir
npm run dev -- --host 127.0.0.1 --open
