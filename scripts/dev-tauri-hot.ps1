#Requires -Version 5.1
<#
.SYNOPSIS
  Start Tauri desktop dev environment on Windows with hot reload.
.DESCRIPTION
  Windows equivalent of dev-tauri-hot.sh.
  Cleans up stale backend processes, ensures sidecar placeholder exists,
  then launches Tauri dev with Vite HMR.
#>

param(
  [int]$FrontendPort = $( if ($env:MAGI_FRONTEND_PORT) { $env:MAGI_FRONTEND_PORT } else { 5173 } )
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FrontendDir = Join-Path $RootDir "frontend"
$TauriBinDir = Join-Path $RootDir "frontend\src-tauri\binaries"

function Stop-ListenersOnPort {
  param([int]$Port)

  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if (-not $connections) { return }

  $procIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
  Write-Host "Port $Port is in use, stopping existing listener(s): $($procIds -join ', ')"

  foreach ($p in $procIds) {
    try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch {}
  }

  Start-Sleep -Seconds 1

  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($connections) {
    $procIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    Write-Host "Port $Port listener(s) still active after stop, forcing: $($procIds -join ', ')"
    foreach ($p in $procIds) {
      try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch {}
    }
  }
}

function Stop-StaleDevBackends {
  $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match "python" -and
    (($_.CommandLine -match "run_server\.py") -or ($_.Path -and (& {
      try {
        $wmi = Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue
        $wmi.CommandLine -match "run_server\.py"
      } catch { $false }
    })))
  }

  if (-not $procs) { return }

  Write-Host "Stopping stale Magi backend process(es): $($procs.Id -join ', ')"
  foreach ($p in $procs) {
    try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
  }

  Start-Sleep -Seconds 2

  # Re-check
  $remaining = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Id -in $procs.Id
  }
  if ($remaining) {
    Write-Host "Force stopping remaining backend process(es): $($remaining.Id -join ', ')"
    foreach ($p in $remaining) {
      try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
  }
}

function Ensure-SidecarPlaceholder {
  if (-not (Test-Path $TauriBinDir)) {
    New-Item -ItemType Directory -Force -Path $TauriBinDir | Out-Null
  }

  $triple = $null

  # Try rustc in PATH first, then common install locations
  $rustcCmd = Get-Command rustc -ErrorAction SilentlyContinue
  if (-not $rustcCmd) {
    $candidatePaths = @(
      "$env:USERPROFILE\.cargo\bin\rustc.exe",
      "$env:CARGO_HOME\bin\rustc.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    if ($candidatePaths) { $rustcCmd = $candidatePaths[0] }
  }

  if ($rustcCmd) {
    try {
      $rustInfo = & $rustcCmd -vV 2>&1
      $hostLine = $rustInfo | Select-String -Pattern "^host:\s+(.+)$"
      if ($hostLine) {
        $triple = $hostLine.Matches[0].Groups[1].Value.Trim()
      }
    } catch {}
  }

  if (-not $triple) {
    $triple = "x86_64-pc-windows-msvc"
    Write-Host "rustc not found, using default target triple: $triple"
  }

  $sidecarPath = Join-Path $TauriBinDir "magi-backend-${triple}.exe"
  if (Test-Path $sidecarPath) { return }

  # Create a minimal placeholder executable (batch wrapper)
  $batContent = @"
@echo off
echo Magi sidecar placeholder (debug fallback mode).
exit /b 0
"@
  # Write a .cmd placeholder that Tauri can execute
  $sidecarCmd = Join-Path $TauriBinDir "magi-backend-${triple}.exe"

  # For dev mode we create a tiny valid PE — simplest approach: copy cmd.exe as placeholder
  Copy-Item -Path "$env:SystemRoot\System32\cmd.exe" -Destination $sidecarPath -Force
  Write-Host "Created sidecar placeholder for dev: $sidecarPath"
}

# --- Main ---

Ensure-SidecarPlaceholder
Stop-StaleDevBackends
Stop-ListenersOnPort -Port $FrontendPort

# Register cleanup on script exit
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
  Write-Host ""
  Write-Host "dev-tauri-hot.ps1 shutting down..."
  Stop-StaleDevBackends
  Write-Host "Cleanup complete."
}

Write-Host "Starting Tauri desktop window (frontend HMR enabled by Vite)..."
Write-Host "Backend lifecycle is owned by Tauri in debug mode."

Push-Location $FrontendDir
try {
  $env:VITE_DEV_SERVER_PORT = $FrontendPort
  npm run tauri:dev
} finally {
  Pop-Location
  Write-Host ""
  Write-Host "dev-tauri-hot.ps1 shutting down..."
  Stop-StaleDevBackends
  Write-Host "Cleanup complete."
}
