; NSIS installer script for SpeechCraft Studio
; Produces: SpeechCraft_Studio_Setup.exe
;
; Flow:
;   1. Welcome page
;   2. License page (MIT)
;   3. Custom edition-choice page (Core vs Full)
;   4. InstallFiles (extracts ONLY the chosen edition to $INSTDIR)
;   5. Finish page
;
; Only the chosen EXE is installed - a Full install physically contains
; only the Full binary and a Core install only the Core binary. The
; choice is persisted to %APPDATA%\SpeechCraft\PreferredBundle.txt and
; an edition-specific ReadMe.txt is generated that describes the edition
; actually installed. The app ingests the sidecar on first launch
; (prefs.merge_installer_edition).

; ==================== CONFIG ====================
Unicode True
RequestExecutionLevel admin
InstallDir "$PROGRAMFILES64\SpeechCraft Studio"
InstallDirRegKey HKLM "Software\SpeechCraft\Studio" "InstallDir"
SetCompressor /SOLID lzma
SetOverwrite on
VIProductVersion "1.3.3.0"
VIAddVersionKey "ProductName" "SpeechCraft Studio"
VIAddVersionKey "CompanyName" "Tracy Smith Consulting"
VIAddVersionKey "LegalCopyright" "Tracy Smith 2026 (MIT)"
VIAddVersionKey "FileDescription" "Accessible Audio Editor"
VIAddVersionKey "FileVersion" "1.3.3"

Name "SpeechCraft Studio"

; Output location - use absolute path to ensure it writes to the right place
!define OUTPUT_DIR "C:/Users/trace/Documents/AppProjects/speechcraft-audio/dist"
OutFile "${OUTPUT_DIR}/SpeechCraft_Studio_Setup.exe"

; ==================== VARS (must be declared BEFORE page macros) ====================
Var BundleChoice
Var Dialog
Var CoreRadio
Var FullRadio
Var HndSidecar

; ==================== INCLUDES ====================
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

; ==================== PAGE SEQUENCE ====================
!define MUI_WELCOMEPAGE_TITLE "Welcome to SpeechCraft Studio 1.3.3"
!define MUI_WELCOMEPAGE_TEXT "This wizard installs SpeechCraft Studio v1.3.3 on your computer. SpeechCraft Studio is an accessible audio editor. You'll be asked to pick an edition on the next page: Core (small install, models downloaded on demand) or Full (all models bundled, works offline out of the box). Click Next to continue."
!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"

Page custom BundlePage_Create BundlePage_Leave

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "Installation complete"
!define MUI_FINISHPAGE_TEXT "SpeechCraft Studio 1.3.3 is now installed. Tick the checkboxes below to open the install folder and/or launch SpeechCraft Studio."
; "Launch" button on finish page - points at the single installed EXE.
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Launch SpeechCraft Studio"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchSpeechCraft"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\ReadMe.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open the SpeechCraft Read Me"

!insertmacro MUI_PAGE_FINISH

; ==================== LAUNCH AFTER INSTALL ====================
; Both editions install to the same filename, so the launcher is
; always $INSTDIR\SpeechCraft_Studio.exe.
Function LaunchSpeechCraft
    Exec '"$INSTDIR\SpeechCraft_Studio.exe"'
FunctionEnd

; ==================== UNINSTALLER ====================
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ==================== SECTION (where File actually works) ====================
Section "SpeechCraft Studio" SecMain
    SectionIn RO

    ; Install ONLY the chosen edition. The other EXE is bundled in the
    ; installer but NOT extracted, so a Core install contains only the
    ; Core binary and a Full install only the Full binary. Both ship
    ; under the name SpeechCraft_Studio.exe in $INSTDIR:
    ;   dist/SpeechCraft_Studio_Core.exe  (lean, no pedalboard/whisper)
    ;   dist/SpeechCraft_Studio.exe       (full, all heavy deps)
    SetOutPath "$INSTDIR"

    ${If} $BundleChoice == "Full"
        File "..\dist\SpeechCraft_Studio.exe"
    ${Else}
        File "..\dist\SpeechCraft_Studio_Core.exe"
        Rename "$INSTDIR\SpeechCraft_Studio_Core.exe" "$INSTDIR\SpeechCraft_Studio.exe"
    ${EndIf}

    ; Create Start Menu folder
    CreateDirectory "$SMPROGRAMS\SpeechCraft Studio"

    ; One shortcut for the installed edition, plus Uninstall.
    CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\SpeechCraft Studio.lnk" "$INSTDIR\SpeechCraft_Studio.exe"
    CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

    ; Write uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; --- Edition-specific ReadMe.txt (describes the edition ACTUALLY
    ;     installed). Two static files are bundled; the installer copies
    ;     the one matching the user's choice, then renames it to ReadMe.
    ${If} $BundleChoice == "Full"
        File "ReadMe_Full.txt"
        Rename "$INSTDIR\ReadMe_Full.txt" "$INSTDIR\ReadMe.txt"
    ${Else}
        File "ReadMe_Core.txt"
        Rename "$INSTDIR\ReadMe_Core.txt" "$INSTDIR\ReadMe.txt"
    ${EndIf}

    ; --- Persist the edition choice to the user's home ----------------
    ; The app's prefs.py can't be called from NSIS, so the choice is
    ; dropped in a one-line sidecar that run_speechcraft.py ingests on
    ; first launch (prefs.merge_installer_edition merges it into
    ; setup.json as preferred_bundle, then deletes the sidecar).
    CreateDirectory "$APPDATA\SpeechCraft"
    ${If} $BundleChoice == "Full"
        StrCpy $0 "Full"
    ${Else}
        StrCpy $0 "Core"
    ${EndIf}
    FileOpen $HndSidecar "$APPDATA\SpeechCraft\PreferredBundle.txt" w
    FileWrite $HndSidecar "$0"
    FileClose $HndSidecar

    ; Registry entries - standard Add/Remove Programs keys.
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "DisplayName" "SpeechCraft Studio"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "DisplayVersion" "1.3.3"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "Publisher" "Tracy Smith Consulting"
    WriteRegStr HKLM "Software\SpeechCraft\Studio" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\SpeechCraft\Studio" "Edition" "$BundleChoice"

SectionEnd

; ==================== BUNDLE CHOICE PAGE ====================
Function BundlePage_Create
    nsDialogs::Create 1018
    Pop $Dialog

    ${If} $Dialog == error
        Abort
    ${EndIf}

    ; Title
    ${NSD_CreateLabel} 0 0 100% 20u "Choose your edition:"
    Pop $0

    ; Core radio. WS_GROUP (added by NSD_CreateFirstRadioButton) marks
    ; this as the start of a new radio-button group so Tab and arrow
    ; keys navigate between Core and Full only.
    ${NSD_CreateFirstRadioButton} 20 35 100% 12u "Core - on-demand feature downloads (172 MB)"
    Pop $CoreRadio
    SendMessage $CoreRadio ${BM_SETCHECK} ${BST_CHECKED} 0

    ; Core description
    ${NSD_CreateLabel} 35 50 100% 30u "The lean install: recording, editing, effects, and TTS. Feature models (Whisper transcription, Piper voices) download on demand when you enable them in the setup wizard. Smaller install, works right away for everyday audio work."
    Pop $0

    ; Full radio - NSD_CreateRadioButton (no WS_GROUP), so it's part
    ; of the same group as Core. Tab/arrow keys will toggle between them.
    ${NSD_CreateRadioButton} 20 90 100% 12u "Full - all feature models pre-bundled (435 MB)"
    Pop $FullRadio

    ; Full description
    ${NSD_CreateLabel} 35 105 100% 30u "Everything in Core, with the local Whisper transcription and Piper TTS models already bundled. Works fully offline out of the box - no download step, no first-run waiting. Best if you know you'll use the AI features."
    Pop $0

    ; Footer note
    ${NSD_CreateLabel} 20 150 100% 20u "Tip: you can switch editions later by running this installer again."
    Pop $0

    nsDialogs::Show
FunctionEnd

Function BundlePage_Leave
    ; Read which radio is selected
    SendMessage $CoreRadio ${BM_GETCHECK} 0 $0
    ${If} $0 == ${BST_CHECKED}
        StrCpy $BundleChoice "Core"
    ${Else}
        SendMessage $FullRadio ${BM_GETCHECK} 0 $0
        ${If} $0 == ${BST_CHECKED}
            StrCpy $BundleChoice "Full"
        ${Else}
            ; Default to Core if nothing is selected
            StrCpy $BundleChoice "Core"
        ${EndIf}
    ${EndIf}
FunctionEnd

; ==================== POST-INSTALL FINISH ====================
Function .onInstSuccess
    ; Nothing extra to do - Section already wrote registry + shortcuts.
    ; Don't pop a MessageBox here: the MUI finish page already shows
    ; the "Installation Complete" message and Finish button. Adding a
    ; second modal blocks the finish page from advancing and causes
    ; "not responding" on close.
FunctionEnd

Function .onInstFailed
    MessageBox MB_ICONSTOP|MB_OK "Installation failed. Please try again or contact support."
FunctionEnd

; ==================== UNINSTALLER ====================
; un.onUninstSuccess runs AFTER the Uninstall Section has completed,
; so the registry keys are already removed there. We keep a minimal
; success message here for user feedback; no file/registry work.
Function un.onUninstSuccess
    MessageBox MB_ICONINFORMATION|MB_OK "SpeechCraft Studio has been removed. Your personalisation settings were kept in %APPDATA%\SpeechCraft."
FunctionEnd

Function un.onInit
FunctionEnd

Section "Uninstall"
    ; Remove the installed EXE, generated ReadMe and uninstaller
    Delete "$INSTDIR\SpeechCraft_Studio.exe"
    Delete "$INSTDIR\ReadMe.txt"
    Delete "$INSTDIR\Uninstall.exe"

    ; Remove Start Menu shortcuts
    Delete "$SMPROGRAMS\SpeechCraft Studio\*.lnk"
    RMDir "$SMPROGRAMS\SpeechCraft Studio"

    ; Remove the install directory
    RMDir "$INSTDIR"

    ; Remove the user's downloaded feature models (Piper voices,
    ; Whisper ASR) stored under %APPDATA%\SpeechCraft\feature_assets.
    ; The setup.json and other user prefs in %APPDATA%\SpeechCraft are
    ; deliberately NOT removed - the user may want to keep their
    ; personalisation and just reinstall with a different edition.
    RMDir /R "$APPDATA\SpeechCraft\feature_assets"
    Delete "$APPDATA\SpeechCraft\PreferredBundle.txt"

    ; Remove registry keys
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio"
    DeleteRegKey HKLM "Software\SpeechCraft\Studio"

SectionEnd
