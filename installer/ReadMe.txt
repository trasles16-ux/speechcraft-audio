SpeechCraft Studio 1.3.2 — Installed Edition
============================================

You have installed one of two editions:

Core
  - The lean install. Feature models (local Whisper transcription,
    Piper TTS voices) are NOT bundled. When you enable a feature in
    the setup wizard, the model downloads on demand and verifies
    against a SHA-256 checksum before it's used.
  - Good for: quick install, everyday audio work, first-time use.

Full
  - Everything in Core, with the local Whisper (tiny.en / base.en)
    and Piper TTS (en_GB.cori / en_GB.alan) models pre-bundled.
  - Works fully offline out of the box — no download step.
  - Good for: users who know they'll use the AI features, or who
    install on machines with limited/restricted internet access.

After install:
  1. Launch SpeechCraft Studio from the Start Menu.
  2. On first launch, the setup wizard appears. Pick your features.
     - If you installed Core and want a model, tick it and click
       the download button on the download page.
     - If you installed Full, every model is already ready; the
       download page will just show "All models ready".
  3. Re-run the wizard any time from:
        Help → Personalise SpeechCraft…

Where things live:
  - Install files:      C:\Program Files\SpeechCraft Studio\
  - Your personalisation: %APPDATA%\SpeechCraft\setup.json
  - Downloaded models:   %APPDATA%\SpeechCraft\feature_assets\

Uninstall:
  Start Menu → SpeechCraft Studio → Uninstall, or
  Add/Remove Programs → SpeechCraft Studio → Uninstall.
  The uninstaller removes the install folder, shortcuts, and the
  downloaded models, but KEEPS your setup.json personalisation so
  a reinstall inherits your feature choices.
