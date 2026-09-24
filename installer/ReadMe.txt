SpeechCraft Studio 1.3.6
========================

Welcome to SpeechCraft Studio — an accessible audio editor for
recording, transcription, breath smoothing, and audio description
work.

What this installer does
------------------------
This wizard installs ONE file: SpeechCraft_Studio.exe. That EXE
includes every Python dependency the app can use (pedalboard,
librosa, scipy, faster_whisper, torch). It does NOT include any
large model files.

After install:
  1. Launch SpeechCraft Studio from the Start Menu.
  2. On first launch, a setup wizard appears and walks you through:
       - Welcome
       - Editing features (basic editing, advanced effects,
         destructive editing, line placing)
       - TTS engines (Edge TTS, Piper TTS)
       - Download ready — for each feature you enabled, the
         wizard downloads and verifies the model files it needs
         (Piper voices, Whisper model, piper.exe for Core-style
         installs). SHA-256 verified.
       - Data location
       - Summary
  3. Re-run the wizard any time from:
         Help → Personalise SpeechCraft…

If the installer is upgrading an existing install, your
personalisation (%APPDATA%\SpeechCraft\setup.json) is kept, so
your previously-chosen features stay selected. The wizard only
re-shows on first run.

Where things live
-----------------
  Install files:        C:\Program Files\SpeechCraft Studio\
  Personalisation:       %APPDATA%\SpeechCraft\setup.json
  Downloaded models:     %APPDATA%\SpeechCraft\feature_assets\

Auto-update
-----------
Help → Check for updates hits the GitHub Releases API. If a newer
version is published, the app downloads and SHA-256 verifies the
new installer, then prompts to run it. The download dialog announces
its progress as a live region so screen readers hear
"Connecting to GitHub…", "Downloading… N percent", "Verifying
checksum…", "Done".

Uninstall
---------
Start Menu → SpeechCraft Studio → Uninstall, or Add/Remove
Programs → SpeechCraft Studio → Uninstall.

The uninstaller removes the install folder, shortcuts, and the
downloaded models, but KEEPS your setup.json personalisation so a
reinstall inherits your feature choices.
