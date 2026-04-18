param(
  [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RootDir "backend"
$TauriBinDir = Join-Path $RootDir "frontend/src-tauri/binaries"

# Use the project venv Python (3.12) — must match the backend runtime.
$VenvPython = Join-Path $RootDir ".venv/Scripts/python.exe"
if (-not (Test-Path $VenvPython)) {
  throw "Project venv not found at $VenvPython. Run 'python -m venv .venv && .venv/Scripts/pip install -e backend[dev]' first."
}
$PythonExe = $VenvPython
Write-Host "Using venv Python: $PythonExe"

& $PythonExe -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller is required. Install with: $PythonExe -m pip install pyinstaller"
}

New-Item -ItemType Directory -Force -Path $TauriBinDir | Out-Null

Push-Location $BackendDir
$OrigPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Join-Path $BackendDir "src") + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })

$BuildScript = @'
import subprocess
import sys

from magi.utils.sidecar_build import build_pyinstaller_command

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

$SourceBin = Join-Path $BackendDir "dist/magi-backend.exe"
$TargetBin = Join-Path $TauriBinDir ("magi-backend-{0}.exe" -f $TargetTriple)

if (-not (Test-Path $SourceBin)) {
  throw "Sidecar binary not found at $SourceBin"
}

Copy-Item -Force $SourceBin $TargetBin
Write-Host "Built sidecar: $TargetBin"

