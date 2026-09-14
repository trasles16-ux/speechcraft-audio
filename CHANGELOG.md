# Changelog

All notable changes to SpeechCraft Audio are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/) as far as a single-developer desktop app can.

## [Unreleased]

## [1.3.0] — 2026-09-14

### Added
- **Modular setup wizard** (`setup_wizard.py` + `setup_wizard_pages.py`). Five pages: Welcome → Editing features → TTS engines → Data location → Summary. Replaces the v1.2.0 Core/Full onboarding dialog with a per-feature choice story. Each toggleable feature has a checkbox plus a one-line description; the Summary page lists every flag and its current state before the user clicks Finish.
- **Help → Personalise SpeechCraft…** menu item. Re-runnable any time; lets the user toggle any feature on or off and persist the choice to `setup.json`.
- **`feature_flags.py`** — pure-logic module with the data layer for every v1.3.0 PR. Exposes a frozen `FeatureFlags` dataclass (8 fields), `load_feature_flags`, `save_feature_flags`, `set_feature_flag`, plus `mark_wizard_completed` / `is_wizard_completed`. Permissive read: missing/empty/corrupt `setup.json` returns defaults, never raises. Unknown feature name in `set_feature_flag` raises `KeyError` (typos fail loud).
- **`prefs.py`** — shared read/write of `~/.speechcraft/setup.json`. Single source of truth for the prefs file path; `onboarding_dialog` and the auto-update wrappers in `audio_editor` now use it. Onboarding/auto-update/feature_flags all preserve each other's top-level keys via read-modify-write.

### Changed
- First-launch onboarding now uses the wizard (auto-shows when `wizard_completed=False`). The v1.2.0 `OnboardingDialog` and its `Core` / `Full` choice are removed.
- Help menu: **Switch Edition (Core / Full)** is gone; **Personalise SpeechCraft…** replaces it.

### Tests
- 30 new tests: `tests/test_feature_flags.py` (20 pure-logic), `tests/test_prefs.py` (10 pure-logic), `tests/test_setup_wizard.py` (16 — 6 pure-logic, 10 wx-dependent).
- Total: **186 passing**.

## [1.2.0] — 2026-09-14

### Added
- **m4a (AAC) audio support** in File → Open Audio and File → Export Audio. M4A is the format used by iPhone Voice Memos and many podcast tools. FFmpeg is still required; the ffmpeg-missing dialog now mentions M4A alongside MP3. `project_handler.export_mixdown` maps user-facing `"m4a"` to pydub's `"mp4"` container format.
- **In-app auto-update**. Two seconds after SpeechCraft launches, it checks GitHub for a newer release. If one exists, an accessible prompt dialog appears with three choices: Download and install, Skip this version permanently, or Remind me next launch (the default — Enter never silently installs). If the user picks Download, the installer is streamed to `%LOCALAPPDATA%\SpeechCraft\updates\SpeechCraft-Setup-<version>.exe` with a percentage progress dialog and a live NVDA-readable status label. The download is verified against its SHA-256 digest before launching, then SpeechCraft quits and the installer runs to replace it.
- **Help → Check for updates…** as a manual entry point to the same flow.
- **`updater.py`** — new pure-logic module: `UpdateInfo`, `AssetInfo`, `compare_versions`, `parse_release`, `fetch_latest_release`, `download_with_progress`, `verify_asset_sha256`, `fetch_expected_sha256`, `launch_installer`. Stdlib only (`urllib.request`, `hashlib`); no new dependencies.
- **`dialogs/update_dialog.py`** — accessible prompt dialog (Install / Skip / Remind).
- **`dialogs/download_progress_dialog.py`** — accessible progress dialog with `wx.Gauge` + live-region status label + Cancel button.

### Security
- Every installer download is SHA-256 verified before launching. Mismatches discard the file and surface a clear error dialog. Verified via the asset's `digest` field when GitHub provides one, otherwise via a sibling `.sha256` sidecar uploaded with the release.

### Changed
- Centralised `__version__ = "1.2.0"` at the top of `audio_editor.py` (was a buried `"3.0.2"` literal in the bug-report dialog). Bump in lockstep with the NSIS installer version and the GitHub release tag.

### Tests
- 16 new tests across `tests/test_updater.py` (14 pure-logic, Linux CI) and `tests/test_dialog_smoke.py` (2 new dialog tests).

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
