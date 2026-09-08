# Changelog

All notable changes to SpeechCraft Audio are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/) as far as a single-developer desktop app can.

## [Unreleased]

### Fixed (1.1.4)
- **Recording dialog → "name 'sd' is not defined"** when opening File → Record with a default input device (issue #16): `dialogs/recording_dialogs.py` referenced `sd` and `np` in `RecordingDialog.toggle_monitor`'s audio callback without importing either at module level. Same class of bug as #14 and #15, but in a different file that the original fix missed. Now bound at module load via the same `safe_import` pattern used in `audio_editor.py`, with an inline `_MissingAudioModule` placeholder (mirrors `audio_editor.DummyModule`; can't reuse directly due to circular import). On genuine missing dep, the placeholder pops a friendly install-dialog instead of `NameError`. (#16)
- Added regression test in `test_dialog_smoke.py` asserting module-level `sd`/`np` bindings in `recording_dialogs` and that opening `RecordingDialog` with `input_device_id` set does not raise on construction.

## [1.1.3] — 2026-09-08
- **`load_audio` silently did nothing on non-WAV files** (issue #13, reported by PaulDrake777): `AudioSegment.from_file()` raises `CouldntEncodeError`/`CouldntDecodeError` when ffmpeg is missing — subclasses of `Exception`, not `FileNotFoundError`, so the existing `except` clause never fired. The exception bubbled up uncaught and wxPython swallowed it silently. `load_audio` now catches any exception, distinguishes ffmpeg-missing from generic decode errors, falls back to `wave.open` for WAV files, and always surfaces a user-facing dialog. (#13)
- **"Error enumerating devices" + "Output test failed: name 'np' is not defined"** in Advanced Audio Setup (issue #14, #15): `sd`, `pyaudio`, and `np` are now bound at module load via `safe_import()` so the device dialog, level monitor, and test-tone code can always reference them. A nested `import sounddevice as sd` inside `populate_devices()` (and a `global sd; import sounddevice as sd` inside `__init__`) was causing `UnboundLocalError` instead of `NameError` — both removed. AST-scan regression test added: it fails the build if anyone reintroduces function-scope `import sounddevice as sd`. (#14)
- **Test Input recorded silence on the wrong output device**: `sd.play(test_data, 44100)` used the system default output, ignoring the user's selection in the Output combobox. Now plays on the selected output, and surfaces the recorded peak in the status bar so a dead mic is distinguishable from a broken output path. (#15)
- Added 5 regression tests covering the broadened `except` clause, the module-level `sd`/`pyaudio`/`np` bindings, and the AST guard against function-scope sounddevice imports.

## [1.1.2] — 2026-09-07

### Fixed
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
