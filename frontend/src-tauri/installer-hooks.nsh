; Magi installer hooks
;
; Tauri's NSIS template already terminates the main Magi.exe before extracting
; files, but the Python sidecar (magi-backend.exe) is a separate process tree
; that holds locks on sidecar-dist\_internal\*.pyd. If it survives into the
; extraction phase the installer fails with "Error opening file for writing".
;
; Kill the sidecar tree before extraction, then give Windows a moment to drop
; the file handles. /T tree-kills any plugin python grandchildren spawned by
; the sidecar.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping Magi background services..."
  nsExec::ExecToLog 'taskkill /F /T /IM "magi-backend.exe"'
  Pop $0
  ; taskkill returns 128 when no matching process exists — that's fine.
  Sleep 800
!macroend
