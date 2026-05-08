param()

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RootDir "backend"
$SidecarStaging = Join-Path $RootDir "frontend/src-tauri/sidecar-dist"

# Prefer the project venv when present, but allow CI to use actions/setup-python.
$VenvPython = Join-Path $RootDir ".venv/Scripts/python.exe"
if (Test-Path $VenvPython) {
  $PythonExe = $VenvPython
  Write-Host "Using venv Python: $PythonExe"
} else {
  $PythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if (-not $PythonCmd) {
    throw "Python command not found. Install Python or create .venv first."
  }
  $PythonExe = $PythonCmd.Source
  Write-Host "Using Python from PATH: $PythonExe"
}

& $PythonExe -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller is required. Install with: $PythonExe -m pip install pyinstaller"
}

Push-Location $BackendDir
$OrigPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Join-Path $BackendDir "src") + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })

$BuildScript = @'
import subprocess
import sys

from magi.utils.sidecar_build import (
  build_pyinstaller_command,
  validate_sqlite_vec_runtime_support,
)

validate_sqlite_vec_runtime_support()
cmd = build_pyinstaller_command()
# Use the current venv interpreter instead of the bare "python" string.
cmd[0] = sys.executable
# Insert --noconsole for Windows so the sidecar does not spawn a console window.
if "--onefile" in cmd:
    idx = cmd.index("--onefile")
    cmd.insert(idx + 1, "--noconsole")

print("PyInstaller command:", " ".join(str(c) for c in cmd), flush=True)
subprocess.run(cmd, check=True)
'@

$BuildScript | & $PythonExe -
if ($LASTEXITCODE -ne 0) {
  $env:PYTHONPATH = $OrigPythonPath
  Pop-Location
  throw "Python build script failed with exit code $LASTEXITCODE"
}
$env:PYTHONPATH = $OrigPythonPath
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

