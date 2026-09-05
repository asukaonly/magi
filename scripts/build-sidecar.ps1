param()

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RootDir "backend"
$SidecarStaging = Join-Path $RootDir "frontend/src-tauri/sidecar-dist"
$PluginPythonStaging = Join-Path $RootDir "frontend/src-tauri/plugin-python"

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

function Stage-PluginPython {
  if (Test-Path $PluginPythonStaging) { Remove-Item -Recurse -Force $PluginPythonStaging }

  if ($env:MAGI_PLUGIN_PYTHON_SOURCE) {
    if (-not (Test-Path $env:MAGI_PLUGIN_PYTHON_SOURCE)) {
      throw "MAGI_PLUGIN_PYTHON_SOURCE does not exist: $env:MAGI_PLUGIN_PYTHON_SOURCE"
    }
    $SourceRoot = $env:MAGI_PLUGIN_PYTHON_SOURCE
    $NestedInstall = Join-Path $SourceRoot "python/install"
    if (Test-Path $NestedInstall) { $SourceRoot = $NestedInstall }
    New-Item -ItemType Directory -Force -Path $PluginPythonStaging | Out-Null
    Copy-Item -Recurse -Force (Join-Path $SourceRoot "*") $PluginPythonStaging
  } else {
    if (($env:GITHUB_ACTIONS -eq "true") -or ($env:MAGI_REQUIRE_RELOCATABLE_PLUGIN_PYTHON -eq "1")) {
      throw "MAGI_PLUGIN_PYTHON_SOURCE is required for CI/release builds. Use scripts/prepare-plugin-python-runtime.py to provide a relocatable Python runtime."
    }
    Write-Host "MAGI_PLUGIN_PYTHON_SOURCE not set; creating development plugin-python venv from build Python."
    Write-Host "For release builds, provide a relocatable Python runtime via MAGI_PLUGIN_PYTHON_SOURCE."
    & $PythonExe -m venv --copies $PluginPythonStaging
    if ($LASTEXITCODE -ne 0) { throw "Failed to create plugin-python venv." }
  }

  $PluginPythonCandidates = @(
    (Join-Path $PluginPythonStaging "python.exe"),
    (Join-Path $PluginPythonStaging "Scripts/python.exe")
  )
  $PluginPython = $PluginPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $PluginPython) {
    throw "Plugin Python executable not found at $PluginPython"
  }
  & $PluginPython -m pip --version *> $null
  if ($LASTEXITCODE -ne 0) { throw "Plugin Python pip check failed." }
  & $PythonExe (Join-Path $RootDir "scripts/install-plugin-worker-runtime.py") --python $PluginPython --sdk (Join-Path $RootDir "sdk")
  if ($LASTEXITCODE -ne 0) { throw "Plugin worker SDK installation failed." }
  Write-Host "Staged plugin Python runtime: $PluginPythonStaging"
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
for bundle_flag in ("--onedir", "--onefile"):
  if bundle_flag in cmd:
    idx = cmd.index(bundle_flag)
    cmd.insert(idx + 1, "--noconsole")
    break
else:
  cmd.insert(1, "--noconsole")

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
Stage-PluginPython

Write-Host "Built sidecar (onedir): $SidecarStaging"

