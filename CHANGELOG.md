# Changelog

All notable changes to SpeechCraft Audio are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/) as far as a single-developer desktop app can.

## [Unreleased]

### Fixed (1.0.1)
- **`ModuleNotFoundError: No module named 'wx'` on first launch**: The v1.0.0 release was built from a partially-installed venv, so PyInstaller exits 0 but the bundled EXE was missing wxPython, pyttsx3, and a handful of other heavy deps. The user-visible effect was an immediate crash on every machine. This release ships the full bundle (435 MB) built from a clean venv.
- Added `tests/test_build_artifact.py` — a release-gate that inspects the PyInstaller CArchive TOC + PYZ archive and fails if wx, numpy, pydub, sounddevice, or pedalboard are missing. Also enforces a 50 MB minimum size. Will catch this class of bug on every future build.

### Added
- **In-app bug reporting**: Help → Report a Bug now opens a dialog that collects a description, expected behaviour, and reproduction steps; pre-fills the GitHub issues URL with those answers plus environment info; and copies the URL to the clipboard as a fallback. See [README § How to report a bug](README.md#how-to-report-a-bug).
- **Crash hook**: an uncaught exception now writes a redacted traceback to `speechcraft_error.log` and offers to open the bug-report dialog with the log tail pre-attached.
- **Piper "unknown" combobox fix**: the Piper TTS dialog now announces the voice list with a proper name to NVDA, and a missing `piper.exe` surfaces as a clear "Setup Error" message instead of a silent crash.
- **NVDA accessibility**: every TTS dialog's voice combobox now has an accessible name via `wx.Choice.SetName`.

### Removed
- **Masakhane TTS engine**: the engine, its menu item, dialog method, and PyInstaller spec entry were removed. The engine had no external callers and was the smallest of the three engines.

### Refactoring (decomposition)
- **PR #3**: Extracted 6 effect dialogs + `AudioClipboard` to `dialogs/effects_dialogs.py` (1624 lines). Fixed pre-existing bugs: invalid `GetSizerAndFit()` calls, `LB_READONLY` → `LB_SINGLE`, `get_values()` return types.
- **PR #4**: Extracted `RecordingDialog` + `StudioRecordingDialog` to `dialogs/recording_dialogs.py` (578 lines).
- **PR #5**: Extracted TTS menu handlers (`on_edge_tts`, `on_piper_tts`) to `main_frame_tts.py` as `TTSMenuMixin`. `SpeechCraftFrame` now inherits from it.
- **PR #6**: Added 27 functional dialog tests covering all extracted classes. Fixed 6 pre-existing bugs caught by tests.
- **PR #7**: Added 21 pure-logic module tests for `auto_ducker`, `breath_smoothing`, `word_alignment`, `config`.

`audio_editor.py` reduced from 5091 → 2730 lines (−46%).

### Documentation
- README rewritten with NVDA testing guidance, Piper setup notes, known limitations, and a "How to report a bug" section.
- New: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, `AGENTS.md`.
- New issue templates: bug report, feature request, accessibility issue.

## [3.0.2] — 2026

Initial public release on GitHub.
