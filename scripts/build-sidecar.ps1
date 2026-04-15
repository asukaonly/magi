param()

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RootDir "backend"
$SidecarStaging = Join-Path $RootDir "frontend/src-tauri/sidecar-dist"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "python command not found."
}

python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller is required. Install with: python -m pip install pyinstaller"
}

Push-Location $BackendDir
$env:PYTHONPATH = (Join-Path $BackendDir "src")
python -c @"
import subprocess
from magi.utils.sidecar_build import build_pyinstaller_command
subprocess.run(build_pyinstaller_command(), check=True)
"@
Pop-Location

$SourceDir = Join-Path $BackendDir "dist/magi-backend"
$SourceBin = Join-Path $SourceDir "magi-backend.exe"

if (-not (Test-Path $SourceBin)) {
  throw "Sidecar binary not found at $SourceBin"
}

# Copy entire --onedir output to Tauri resource staging
if (Test-Path $SidecarStaging) { Remove-Item -Recurse -Force $SidecarStaging }
Copy-Item -Recurse -Force $SourceDir $SidecarStaging

Write-Host "Built sidecar (onedir): $SidecarStaging"

