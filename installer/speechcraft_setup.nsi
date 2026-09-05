; NSIS installer script for SpeechCraft Studio
; Produces: SpeechCraft_Studio_Setup.exe

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

; Output location (can be overridden with /DSTAGING=...)
!ifdef STAGING
  !define OUTPUT_DIR "${STAGING}"
!else
  !define OUTPUT_DIR "..\dist"
!endif

OutFile "${OUTPUT_DIR}\SpeechCraft_Studio_Setup.exe"

; ==================== LANGUAGES ====================
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

; ==================== PAGE SEQUENCE ====================
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE.txt"
Page custom BundlePage_Create BundlePage_Leave
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; ==================== UNINSTALLER ====================
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ==================== LANGUAGES ====================
!insertmacro MUI_LANGUAGE "English"

; ==================== VARS ====================
Var BundleChoice
Var Dialog
Var CoreRadio
Var FullRadio

; ==================== SECTION ====================
Section "SpeechCraft Studio" SecMain
    ; The actual install logic runs in .onInstSuccess
    ; This section is required by NSIS but minimal
SectionEnd

; ==================== BUNDLE PAGE ====================
Function BundlePage_Create
    nsDialogs::Create 1018
    Pop $Dialog
    
    ${If} $Dialog == error
        Abort
    ${EndIf}
    
    ; Title label
    nsDialogs::CreateControl STATIC $0 0x80000000 0 0 100% 20u "Choose your edition:"
    Pop $0
    
    ; Core radio
    nsDialogs::CreateControl BUTTON $CoreRadio 0x80000004 20 50 100% 12u "Core — recommended (172 MB)"
    Pop $CoreRadio
    SendMessage $CoreRadio ${BM_SETCHECK} ${BST_CHECKED} 0
    
    ; Core description
    nsDialogs::CreateControl STATIC $0 0x80000000 35 65 100% 30u "Recording, transcription via cloud, TTS, basic effects, breath smoothing. Great starting point."
    Pop $0
    
    ; Full radio
    nsDialogs::CreateControl BUTTON $FullRadio 0x80000004 20 105 100% 12u "Full — all features (435 MB)"
    Pop $FullRadio
    
    ; Full description
    nsDialogs::CreateControl STATIC $0 0x80000000 35 120 100% 30u "Everything in Core, plus local Whisper transcription and advanced effects (pedalboard)."
    Pop $0
    
    ; Footer note
    nsDialogs::CreateControl STATIC $0 0x80000000 20 160 100% 16u "You can switch editions later from the Help menu."
    Pop $0
    
    nsDialogs::Show
FunctionEnd

Function BundlePage_Leave
    ${If} $BundleChoice == ""
        StrCpy $BundleChoice "Core"
    ${EndIf}
FunctionEnd

; ==================== .onInstSuccess ====================
Function .onInstSuccess
    ; Determine which bundle to install
    ; Read the choice from the custom page
    
    ; Install Core always
    SetOutPath "$INSTDIR"
    File "/oname=SpeechCraft_Studio_Core.exe" "${OUTPUT_DIR}\SpeechCraft_Studio_Core.exe"
    
    ; Install Full if selected
    ${If} $BundleChoice == "Full"
        File "/oname=SpeechCraft_Studio_Full.exe" "${OUTPUT_DIR}\SpeechCraft_Studio.exe"
    ${EndIf}
    
    ; Create shortcuts
    CreateDirectory "$SMPROGRAMS\SpeechCraft Studio"
    CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\SpeechCraft Studio.lnk" "$INSTDIR\SpeechCraft_Studio_Core.exe"
    
    ${If} $BundleChoice == "Full"
        CreateShortcut "$SMPROGRAMS\SpeechCraft Studio\SpeechCraft Studio (Full).lnk" "$INSTDIR\SpeechCraft_Studio_Full.exe"
    ${EndIf}
    
    ; Write uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    ; Write registry
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "DisplayName" "SpeechCraft Studio"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKLM "Software\SpeechCraft\Studio" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\SpeechCraft\Studio" "BundleChoice" "$BundleChoice"
    
    ; Open README if Full was selected (optional)
FunctionEnd

; ==================== UNINSTALLER ====================
Function un.onUninstSuccess
    HideWindow
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
