param()

$ErrorActionPreference = "Stop"

# Windows PowerShell does not turn native nonzero exits into terminating errors.
function Invoke-Checked {
  param([string]$Executable, [string[]]$Arguments)
  & $Executable @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Executable failed with exit code $LASTEXITCODE"
  }
}

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FrontendDir = Join-Path $RootDir "frontend"
$BackendDir = Join-Path $RootDir "backend"
$SdkDir = Join-Path $RootDir "sdk"
$VenvDir = Join-Path $RootDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts/python.exe"

Write-Host "==> Installing frontend dependencies..."
Push-Location $FrontendDir
try {
  Invoke-Checked -Executable "npm" -Arguments @("ci")
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "==> Installing backend dependencies..."
if (-not (Test-Path $VenvDir)) {
  Invoke-Checked -Executable "python" -Arguments @("-m", "venv", $VenvDir)
}
if (-not (Test-Path $VenvPython -PathType Leaf)) {
  throw "Project environment is incomplete: $VenvPython. Recreate .venv and retry."
}
Write-Host "    using $VenvPython"

Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "setuptools", "wheel")
Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "--no-build-isolation", "-e", $SdkDir)
Invoke-Checked -Executable $VenvPython -Arguments @("-m", "pip", "install", "-e", "${BackendDir}[dev,speech]")

Write-Host ""
Write-Host "==> Checking local speech runtime..."
Invoke-Checked -Executable $VenvPython -Arguments @("-c", "import sherpa_onnx; from sherpa_onnx import OfflineRecognizer, OfflineTts; print(sherpa_onnx.__version__)")

Write-Host ""
Write-Host "==> Building Rust workspace (Tauri + gateway)..."
Push-Location $RootDir
try {
  Invoke-Checked -Executable "cargo" -Arguments @("build")
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "All dependencies installed successfully."
