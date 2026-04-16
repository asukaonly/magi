param(
  [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RootDir "backend"
$TauriBinDir = Join-Path $RootDir "frontend/src-tauri/binaries"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "python command not found."
}

python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller is required. Install with: python -m pip install pyinstaller"
}

New-Item -ItemType Directory -Force -Path $TauriBinDir | Out-Null

Push-Location $BackendDir
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --noconsole `
  --name magi-backend `
  --hidden-import winrt.windows.media.control `
  run_server.py
Pop-Location

$SourceBin = Join-Path $BackendDir "dist/magi-backend.exe"
$TargetBin = Join-Path $TauriBinDir ("magi-backend-{0}.exe" -f $TargetTriple)

if (-not (Test-Path $SourceBin)) {
  throw "Sidecar binary not found at $SourceBin"
}

Copy-Item -Force $SourceBin $TargetBin
Write-Host "Built sidecar: $TargetBin"

