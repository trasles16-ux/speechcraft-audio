# SpeechCraft Studio v1.1.4

Bug-fix release. One issue resolved, missed in the v1.1.3 sweep.

## What's fixed

### Recording dialog → "name 'sd' is not defined" (issue #16)
File → Record / Stop (Ctrl+R) → Recording dialog opens → auto-start of level monitor (when a default input device is selected) raised `NameError: name 'sd' is not defined` / `name 'np' is not defined`.

**Cause:** `dialogs/recording_dialogs.py:RecordingDialog.toggle_monitor` referenced `sd.InputStream(...)` and `np.sqrt(np.mean(...))` in its audio callback closure. Neither `sounddevice` nor `numpy` was imported at module level in this file — same class of bug as #14 and #15, but in a different file that the original fix missed.

**Fix:** Bind `sd` and `np` at module load via the same `safe_import` pattern used in `audio_editor.py`. On genuine missing dep, an inline `_MissingAudioModule` placeholder pops a friendly install-dialog instead of `NameError`. (Can't reuse `audio_editor.DummyModule` directly due to circular import.)

## For users upgrading from v1.1.3

Just re-run the installer (`SpeechCraft_Studio_Setup.exe`) — it will install over the previous version.

## Installation

Download `SpeechCraft_Studio_Setup.exe` below, run it, and choose either:
- **Core** — minimal install (no edge-tts Piper voice models). ~165 MB.
- **Full** — everything bundled (recommended for offline use). ~415 MB.

## Tests

128 tests passing in the project venv:
- 22 pure-logic tests (auto_ducker, breath_smoothing, word_alignment, config)
- 28 dialog smoke tests
- 14 build-artifact tests (regression gates for PyInstaller bundle)
- 64 other (transcription, splash, onboarding, ffmpeg-path)

1 new regression test added in v1.1.4.

## Credits

- Tracy Smith — bug report and diagnosis during own testing (2026-09-08)
