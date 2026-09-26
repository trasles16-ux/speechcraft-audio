; NSIS installer script for SpeechCraft Studio
; Produces: SpeechCraft_Studio_Setup.exe
;
; Flow (v1.3.7 - single-EXE):
;   1. Welcome page
;   2. License page (MIT)
;   3. InstallFiles (extracts the single bundled EXE to $INSTDIR)
;   4. Finish page
;
; One bundled EXE ships every Python dep (pedalboard, librosa, scipy,
; faster_whisper, torch). Model files (Piper voices, Whisper models,
; piper.exe) are NOT bundled - they download on first use via the
; in-app setup wizard (Help -> Personalise SpeechCraft) or the
; lazy-install prompt the first time a feature is used.
;
; No edition choice page here. The wizard is the single source of
; truth for which features the user wants; the installer just puts
; one EXE on disk and lets the wizard drive the rest.
;
; v1.3.7 build contract (passed by build_all.py and by CI):
;   /DAPP_VERSION=x.y.z   dotted app version, 3 segments (e.g. 1.3.7).
;                         VIProductVersion needs 4 segments, so .0 is
;                         appended here - v1.3.6.2.0 hardcoded a
;                         5-segment literal that makensis rejects.
;   /DSTAGING=<dir>       folder containing SpeechCraft_Studio.exe and
;                         ReadMe.txt (built by build_all.py stage step;
;                         also where CI stages it). Defaults to
;                         ..\build\staging relative to this script.
;   /DOUT_DIR=<dir>       where the Setup exe is written. Defaults to
;                         ..\dist (v1.3.6 hardcoded an absolute
;                         C:\Users\trace\... path that could never work
;                         on CI or any other machine).

; ==================== CONFIG ====================
!ifndef APP_VERSION
  !error "APP_VERSION not defined. Build via build_all.py or pass /DAPP_VERSION=x.y.z"
!endif

Unicode True
RequestExecutionLevel admin
InstallDir "$PROGRAMFILES64\SpeechCraft Studio"
InstallDirRegKey HKLM "Software\SpeechCraft\Studio" "InstallDir"
SetCompressor /SOLID lzma
SetOverwrite on

; ==================== STAGING / OUTPUT ====================
!ifndef STAGING
  !define STAGING "..\build\staging"
!endif
!ifndef OUT_DIR
  !define OUT_DIR "..\dist"
!endif
OutFile "${OUT_DIR}\SpeechCraft_Studio_Setup.exe"

!ifndef EXE_SOURCE
  !define EXE_SOURCE "${STAGING}\SpeechCraft_Studio.exe"
!endif
!ifndef README_SOURCE
  !define README_SOURCE "${STAGING}\ReadMe.txt"
!endif

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "SpeechCraft Studio"
VIAddVersionKey "CompanyName" "Tracy Smith Consulting"
VIAddVersionKey "LegalCopyright" "Tracy Smith 2026 (MIT)"
VIAddVersionKey "FileDescription" "Accessible Audio Editor"
VIAddVersionKey "FileVersion" "${APP_VERSION}"

Name "SpeechCraft Studio"

; ==================== INCLUDES ====================
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

; ==================== PAGE SEQUENCE ====================
!define MUI_WELCOMEPAGE_TITLE "Welcome to SpeechCraft Studio ${APP_VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This wizard installs SpeechCraft Studio v${APP_VERSION} on your computer. SpeechCraft Studio is an accessible audio editor. After install, the app opens a setup wizard that walks you through picking features (Piper TTS, local transcription, advanced effects) and downloads the model files they need. Click Next to continue."
!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "Installation complete"
!define MUI_FINISHPAGE_TEXT "SpeechCraft Studio ${APP_VERSION} is now installed. Tick the checkboxes below to open the install folder and/or launch SpeechCraft Studio."
; "Launch" button on finish page - points at the single installed EXE.
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Launch SpeechCraft Studio"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchSpeechCraft"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\ReadMe.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open the SpeechCraft Read Me"

!insertmacro MUI_PAGE_FINISH

; ==================== LAUNCH AFTER INSTALL ====================
; Set PYINSTALLER_RESET_ENVIRONMENT=1 for the launched process. The
; app is a PyInstaller onefile; when the installer is itself launched
; by a running PyInstaller app (the in-app auto-update flow), the
; installer process inherits that app's internal _PYI_* environment
; variables. Our RequestExecutionLevel admin makes the launch
; elevated, and PyInstaller >= 6.22.1 enforces its onefile
; security check in elevated mode: the new app's bootloader walks
; the inherited "originating parent" PID, finds a dead/recycled
; process, and dies with "Security validation failure: parent
; process has different executable!". The reset variable tells the
; bootloader to treat this launch as a fresh top-level process
; (PyInstaller's documented "application restart scenario" hook).
Function LaunchSpeechCraft
    System::Call 'kernel32::SetEnvironmentVariableW(w "PYINSTALLER_RESET_ENVIRONMENT", w "1")'
    Exec '"$INSTDIR\SpeechCraft_Studio.exe"'
FunctionEnd

; ==================== UNINSTALLER ====================
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ==================== SECTION (where File actually works) ====================
Section "SpeechCraft Studio" SecMain
    SectionIn RO

    SetOutPath "$INSTDIR"

    ; --- Clean up legacy artefacts BEFORE writing. NSIS File silently
    ;     no-ops when the target exists, so upgrading over a v1.3.4 or
    ;     earlier install would leave stale binaries / ReadMes / scratch
    ;     WAVs in the folder. We sweep known stale names so an upgrade
    ;     from an old release doesn't leak gigabytes into Program Files.
    Delete "$INSTDIR\SpeechCraft_Studio.exe"
    Delete "$INSTDIR\ReadMe.txt"
    Delete "$INSTDIR\Uninstall.exe"
    Delete "$INSTDIR\temp_original.wav"
    Delete "$INSTDIR\temp_playback.wav"
    Delete "$INSTDIR\temp_processed.wav"

    ; --- Upgrade debris sweep (v1.3.7): same list the uninstaller
    ;     sweeps, so upgrading over a v1.3.6.1 install immediately
    ;     clears the CWD-download leftovers (0-byte piper.exe etc.)
    ;     instead of leaving them until the next uninstall. Feature
    ;     assets are self-healing: feature_state.json points at the
    ;     removed paths, is_ready fails, and the lazy-install prompt
    ;     re-downloads into the correct feature_assets location.
    Delete "$INSTDIR\piper.exe"
    RMDir /R "$INSTDIR\piper_tts"
    RMDir /R "$INSTDIR\local_transcription"
    RMDir /R "$INSTDIR\models"

    ; --- Install the single bundled EXE + ReadMe (both from STAGING).
    File "${EXE_SOURCE}"
    File "${README_SOURCE}"

    ; Create Start Menu folder
    CreateDirectory "$SMPROGRAMS\SpeechCraft Studio"

    ; Shortcut + uninstaller
    CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\SpeechCraft Studio.lnk" "$INSTDIR\SpeechCraft_Studio.exe"
    CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; Registry entries - standard Add/Remove Programs keys.
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "DisplayName" "SpeechCraft Studio"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "Publisher" "Tracy Smith Consulting"
    WriteRegStr HKLM "Software\SpeechCraft\Studio" "InstallDir" "$INSTDIR"

SectionEnd

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
    ; Remove the installed EXE, bundled ReadMe and uninstaller. Legacy
    ; scratch WAVs are swept too, so the final RMDir below can
    ; actually remove the folder instead of leaving it behind (RMDir
    ; fails on a non-empty dir).
    Delete "$INSTDIR\SpeechCraft_Studio.exe"
    Delete "$INSTDIR\ReadMe.txt"
    Delete "$INSTDIR\temp_original.wav"
    Delete "$INSTDIR\temp_playback.wav"
    Delete "$INSTDIR\temp_processed.wav"
    Delete "$INSTDIR\Uninstall.exe"

    ; --- Debris sweep (v1.3.7): the v1.3.6 lazy-install bug downloaded
    ;     feature assets into the process CWD, which for a shortcut
    ;     launch was this install directory. That left partial asset
    ;     trees here (e.g. a 0-byte piper_tts\executable\piper.exe)
    ;     that kept RMDir $INSTDIR from ever succeeding - a v1.3.6.1
    ;     machine still carries 500+ MB in Program Files after
    ;     "uninstall". Sweep the known buggy destinations so the
    ;     final RMDir can actually remove the folder.
    Delete "$INSTDIR\piper.exe"
    RMDir /R "$INSTDIR\piper_tts"
    RMDir /R "$INSTDIR\local_transcription"
    RMDir /R "$INSTDIR\models"

    ; Remove Start Menu shortcuts
    Delete "$SMPROGRAMS\SpeechCraft Studio\*.lnk"
    RMDir "$SMPROGRAMS\SpeechCraft Studio"

    ; Remove the install directory
    RMDir "$INSTDIR"

    ; Remove the user's downloaded feature models (Piper voices,
    ; Whisper ASR) stored under %APPDATA%\SpeechCraft\feature_assets.
    ; The setup.json and other user prefs in %APPDATA%\SpeechCraft are
    ; deliberately NOT removed - the user may want to keep their
    ; personalisation and just reinstall.
    RMDir /R "$APPDATA\SpeechCraft\feature_assets"

    ; Remove registry keys
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio"
    DeleteRegKey HKLM "Software\SpeechCraft\Studio"

SectionEnd
