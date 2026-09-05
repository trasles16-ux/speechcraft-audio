; NSIS installer script for SpeechCraft Studio
; Produces: SpeechCraft_Studio_Setup.exe
;
; Flow:
;   1. Welcome page
;   2. License page (MIT)
;   3. Custom edition-choice page (Core vs Full)
;   4. InstallFiles (extracts Core + optionally Full to $INSTDIR)
;   5. Finish page
;
; Both EXEs are bundled into the installer at COMPILE time (inside the
; Section, where File directives are valid). At RUNTIME, the install
; just runs. The .onInstSuccess / .onInstFailed callbacks run AFTER
; install completes; they only do registry + shortcut bookkeeping.

; ==================== CONFIG ====================
Unicode True
RequestExecutionLevel admin
InstallDir "$PROGRAMFILES64\SpeechCraft Studio"
InstallDirRegKey HKLM "Software\SpeechCraft\Studio" "InstallDir"
SetCompressor /SOLID lzma
SetOverwrite on
VIProductVersion "1.1.0.0"
VIAddVersionKey "ProductName" "SpeechCraft Studio"
VIAddVersionKey "CompanyName" "Tracy Smith Consulting"
VIAddVersionKey "LegalCopyright" "Tracy Smith 2026 (MIT)"
VIAddVersionKey "FileDescription" "Accessible Audio Editor"
VIAddVersionKey "FileVersion" "1.1.0"

Name "SpeechCraft Studio"

; Output location - use absolute path to ensure it writes to the right place
!define OUTPUT_DIR "C:/Users/trace/Documents/AppProjects/speechcraft-audio/dist"
OutFile "${OUTPUT_DIR}/SpeechCraft_Studio_Setup.exe"

; ==================== INCLUDES ====================
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

; ==================== PAGE SEQUENCE ====================
!define MUI_WELCOMEPAGE_TITLE "Welcome to SpeechCraft Studio"
!define MUI_WELCOMEPAGE_TEXT "This wizard installs SpeechCraft Studio on your computer.$\r$\n$\r$\nSpeechCraft Studio is an accessible audio editor. It comes in two editions: Core (small download, recommended) and Full (everything). You'll be asked to pick one on the next page.$\r$\n$\r$\nYou can switch editions later from the Help menu inside the app.$\r$\nClick Next to continue."
!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"

Page custom BundlePage_Create BundlePage_Leave

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "Installation complete"
!define MUI_FINISHPAGE_TEXT "SpeechCraft Studio is now installed.$\r$\n$\r$\nChoose an edition below and click Finish to launch it, or click Finish without selecting anything to close the installer."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Launch SpeechCraft Studio"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "View README"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

; ==================== UNINSTALLER ====================
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ==================== VARS ====================
Var BundleChoice
Var Dialog
Var CoreRadio
Var FullRadio

; ==================== SECTION (where File actually works) ====================
Section "SpeechCraft Studio" SecMain
    SectionIn RO
    
    ; Both EXEs are bundled at compile time. We always install Core.
    ; Full is bundled too (the bundle is already huge, and it lets us
    ; support a "switch to Full" workflow later if we want).
    SetOutPath "$INSTDIR"
    
    ; Install Core always. NSIS File directive reads paths relative
    ; to the .nsi script's own directory, not the build working dir.
    File "..\dist\SpeechCraft_Studio_Core.exe"
    
    ; Install Full as well (so users who picked Core can switch later,
    ; and so the bundled installer always has both available). The
    ; Shortcut section only creates the menu shortcut for the chosen
    ; edition so the start menu doesn't show duplicates.
    File "..\dist\SpeechCraft_Studio.exe"
    Rename "$INSTDIR\SpeechCraft_Studio.exe" "$INSTDIR\SpeechCraft_Studio_Full.exe"
    
    ; Create Start Menu folder
    CreateDirectory "$SMPROGRAMS\SpeechCraft Studio"
    
    ; Create shortcuts based on what user picked
    ${If} $BundleChoice == "Full"
        CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\SpeechCraft Studio.lnk" "$INSTDIR\SpeechCraft_Studio_Full.exe"
    ${Else}
        CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\SpeechCraft Studio.lnk" "$INSTDIR\SpeechCraft_Studio_Core.exe"
    ${EndIf}
    
    ; Always create a (Full) shortcut so users can switch with one click
    CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\SpeechCraft Studio (Full).lnk" "$INSTDIR\SpeechCraft_Studio_Full.exe"
    
    CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
    
    ; Write uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    ; Write registry entries
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "DisplayName" "SpeechCraft Studio"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "DisplayVersion" "1.1.0"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "Publisher" "Tracy Smith"
    WriteRegStr HKLM "Software\SpeechCraft\Studio" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\SpeechCraft\Studio" "BundleChoice" "$BundleChoice"
SectionEnd

; ==================== BUNDLE CHOICE PAGE ====================
Function BundlePage_Create
    nsDialogs::Create 1018
    Pop $Dialog
    
    ${If} $Dialog == error
        Abort
    ${EndIf}
    
    ; Title
    nsDialogs::CreateControl STATIC $0 0x80000000 0 0 100% 20u "Choose your edition:"
    Pop $0
    
    ; Core radio
    nsDialogs::CreateControl BUTTON $CoreRadio 0x80000004 20 50 100% 12u "Core — recommended (172 MB)"
    Pop $CoreRadio
    SendMessage $CoreRadio ${BM_SETCHECK} ${BST_CHECKED} 0
    
    ; Core description
    nsDialogs::CreateControl STATIC $0 0x80000000 35 65 100% 40u "Recording, transcription via cloud account, TTS, basic effects, breath smoothing, room tone match. Great starting point for everyday audio work."
    Pop $0
    
    ; Full radio
    nsDialogs::CreateControl BUTTON $FullRadio 0x80000004 20 115 100% 12u "Full — all features (435 MB)"
    Pop $FullRadio
    
    ; Full description
    nsDialogs::CreateControl STATIC $0 0x80000000 35 130 100% 40u "Everything in Core, plus local Whisper transcription and advanced effects (pedalboard)."
    Pop $0
    
    ; Footer note
    nsDialogs::CreateControl STATIC $0 0x80000000 20 180 100% 20u "Tip: you can switch editions later from the Help menu inside the app."
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
    ; Nothing extra to do — Section already wrote registry + shortcuts.
    ; Don't pop a MessageBox here: the MUI finish page already shows
    ; the "Installation Complete" message and Finish button. Adding a
    ; second modal blocks the finish page from advancing and causes
    ; "not responding" on close.
FunctionEnd

Function .onInstFailed
    MessageBox MB_ICONSTOP|MB_OK "Installation failed. Please try again or contact support."
FunctionEnd

; ==================== UNINSTALLER ====================
Function un.onUninstSuccess
    MessageBox MB_ICONINFORMATION|MB_OK "SpeechCraft Studio has been removed."
    DeleteRegKey HKLM "Software\SpeechCraft\Studio"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio"
FunctionEnd

Function un.onInit
FunctionEnd

Section "Uninstall"
    ; Remove files
    Delete "$INSTDIR\SpeechCraft_Studio_Core.exe"
    Delete "$INSTDIR\SpeechCraft_Studio_Full.exe"
    Delete "$INSTDIR\Uninstall.exe"
    
    ; Remove shortcuts
    Delete "$SMPROGRAMS\SpeechCraft Studio\*.lnk"
    RMDir "$SMPROGRAMS\SpeechCraft Studio"
    
    ; Remove installation directory
    RMDir "$INSTDIR"
SectionEnd
