param()

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FrontendDir = Join-Path $RootDir "frontend"
$BackendDir = Join-Path $RootDir "backend"
$SdkDir = Join-Path $RootDir "sdk"

Write-Host "==> Installing frontend dependencies..."
Push-Location $FrontendDir
try {
  npm install
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "==> Installing backend dependencies..."

$VenvPython = Join-Path $RootDir ".venv/Scripts/python.exe"
if (Test-Path $VenvPython) {
  $PythonExe = $VenvPython
  Write-Host "    using $PythonExe"
}
else {
  $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if ($null -eq $PythonCommand) {
    throw "Python was not found on PATH, and project venv is missing at $VenvPython"
  }
  $PythonExe = $PythonCommand.Source
  Write-Host "    no $VenvPython found, using $PythonExe from PATH"
}

Push-Location $BackendDir
try {
  & $PythonExe -m pip install --upgrade setuptools wheel
  & $PythonExe -m pip install --no-build-isolation -e $SdkDir
  & $PythonExe -m pip install -e ".[dev]"
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "==> Building Rust workspace (Tauri + gateway)..."
Push-Location $RootDir
try {
  cargo build
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "All dependencies installed successfully."