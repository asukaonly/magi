; Magi installer hooks
;
; Tauri's NSIS template handles the main Magi.exe, but the Python sidecar
; (magi-backend.exe) is a separate process tree that can hold locks on
; sidecar-dist\_internal\*.pyd and runtime data files.
;
; Kill the sidecar tree before install or uninstall file operations, then give
; Windows a moment to drop the file handles. /T tree-kills any plugin Python
; grandchildren spawned by the sidecar.

!macro MAGI_STOP_BACKGROUND_SERVICES
  DetailPrint "Stopping Magi background services..."
  nsExec::ExecToLog 'taskkill /F /T /IM "magi-backend.exe"'
  Pop $0
  ; taskkill returns 128 when no matching process exists — that's fine.
  Sleep 800
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro MAGI_STOP_BACKGROUND_SERVICES
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro MAGI_STOP_BACKGROUND_SERVICES
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Match Tauri's built-in delete-data guard and preserve data during updates.
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    DetailPrint "Removing Magi application data..."
    SetShellVarContext current
    RMDir /r "$PROFILE\.magi"
  ${EndIf}
!macroend
