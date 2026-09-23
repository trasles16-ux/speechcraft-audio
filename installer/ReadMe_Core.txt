SpeechCraft Studio 1.3.5 - Core Edition
=======================================

You installed the CORE edition: a lean, fast-starting build.

INCLUDED in Core
----------------
- Basic audio editing: cut, copy, paste, breath smoothing,
  silence trimming, normalize, denoise / noise gate
- Text-to-speech: Edge online TTS and Piper offline TTS
  (Piper voices are bundled with the app)
- The Personalise wizard (Help menu), including model downloads

NOT included in Core
--------------------
- Pedalboard advanced effects: Room Remover, Compressor,
  De-esser, Equalizer, Auto-Ducker. These menu items are
  greyed out in the Effects menu, with a one-time hint
  explaining why.
- Offline (local) Whisper transcription

When a pedalboard effect is greyed out, that is the Core build
telling you the pedalboard engine is not installed - it is not a
broken feature. If you need those effects, re-run the installer
and choose the Full edition. It installs over Core and keeps your
settings and projects.

LAZY INSTALL on first use (v1.3.5)
----------------------------------
Core does NOT bundle piper.exe. The first time you click
Speech > Piper TTS, SpeechCraft offers to download piper.exe from
the official rhasspy/piper GitHub release (~30 MB). The download
is SHA-256 verified and lands under %APPDATA%\SpeechCraft. You only
pay the cost once - the next click is instant.
