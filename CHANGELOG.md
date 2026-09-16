# Changelog

All notable changes to SpeechCraft Audio are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/) as far as a single-developer desktop app can.

## [Unreleased]

## [1.3.2] — 2026-09-15

### Fixed
- **m4a "File not found" with the wrong path**: opening an m4a produced a "File not found" dialog pointing at the audio file, when the real cause was a missing ffprobe/ffmpeg binary. pydub's `FileNotFoundError` carries `e.filename` pointing at the missing binary, not the audio; the dialog now distinguishes the two cases and surfaces a proper FFmpeg Missing diagnostic when ffprobe is missing.
- **Update silently fails when the download worker hits a non-UpdateCheckError exception**. The daemon thread in `_run_update_download` only caught `UpdateCheckError`; any other exception (network timeout, OSError, etc.) vanished into wx's event loop and the user saw the prompt dialog's "Update" button then nothing. The worker body is now wrapped in a top-level `try/except Exception` that surfaces unexpected errors via `_on_download_failed`.
- **Exit code `-22` after an update**. `_quit_for_update` was calling `os._exit(0)` which skips interpreter shutdown mid-operation; the spawned installer then failed with `STATUS_INVALID_PARAMETER` (exit -22). Switched to `wx.Exit()` which flushes the event loop first.

### Added
- **Pre-launch message box** before `launch_installer()`, telling the user an installer should appear in a few seconds — gives them a chance to notice if UAC/SmartScreen is blocking the spawn.

## [1.3.1] — 2026-09-15

### Fixed
- **Auto-update crashed on first run after install**: the installer staging folder (`%LOCALAPPDATA%\SpeechCraft\updates\`) doesn't exist on a fresh install, so the download raised `FileNotFoundError` (`[Errno 2] No such file or directory`). `download_with_progress` now creates the destination directory before writing.
- **Misleading "Update Error" dialog** when a release has no installer asset — the message now explains it's a release-ops gap and links to the GitHub release page for a manual download.

## [1.3.0] — 2026-09-14

### Added
- **Modular setup wizard** (`setup_wizard.py` + `setup_wizard_pages.py`). Six pages: Welcome → Editing features → TTS engines → **Download & ready** → Data location → Summary. Replaces the v1.2.0 Core/Full onboarding dialog with a per-feature choice story. Each toggleable feature has a checkbox plus a one-line description; the Download page lists every enabled-and-missing asset with a live gauge, Download + Cancel buttons, and a Download-all option; downloads run in daemon threads and verify SHA-256 before installing.
- **Help → Personalise SpeechCraft…** menu item. Re-runnable any time; lets the user toggle any feature on or off and persist the choice to `setup.json`, re-applies menu gates live so the menu bar updates without a relaunch.
- **`feature_flags.py`** — pure-logic module with the data layer for every v1.3.0 PR. Exposes a frozen `FeatureFlags` dataclass (8 fields), `load_feature_flags`, `save_feature_flags`, `set_feature_flag`, plus `mark_wizard_completed` / `is_wizard_completed`. Permissive read: missing/empty/corrupt `setup.json` returns defaults, never raises. Unknown feature name in `set_feature_flag` raises `KeyError` (typos fail loud).
- **`prefs.py`** — shared read/write of `~/.speechcraft/setup.json`. Single source of truth for the prefs file path; `onboarding_dialog` and the auto-update wrappers in `audio_editor` now use it. Onboarding/auto-update/feature_flags all preserve each other's top-level keys via read-modify-write.
- **`feature_manager.py`** — SHA-verified asset registry + download layer for feature models (Piper TTS voices, faster-whisper ASR models). Assets install to `PREFS_DIR/feature_assets/`, state lives in `PREFS_DIR/feature_state.json`, both written atomically with `.part` + `os.replace`. All Piper voices are `en_GB` (Cori/Alan) — the dead `en_ZA` URLs are gone.
- **`feature_toggling.py`** — pure gate-decision layer. Given `FeatureFlags` + feature state, decides per-feature "enabled / needs-download / not-downloadable" so the menu bar, wizard, and engines all agree.
- **Menu gating** — `create_menus` captures the feature-dependent items; `_apply_feature_gates()` disables (not hides) off-flag items so the layout stays stable and NVDA skips them cleanly.
- **Main-frame accessibility** — `audio_editor.py` gained `SetName()` on the frame, main panel, all three region labels, the tracks list, the transcript workspace, the log area, and every control in the inline Audio Setup dialog (engine/output/input comboboxes, level gauge, dB readout, monitor toggle, Test Output / Test Input / Apply buttons). NVDA now announces each control by a meaningful name instead of its wxPython default.

### Changed
- First-launch onboarding now uses the wizard (auto-shows when `wizard_completed=False`). The v1.2.0 `OnboardingDialog` and its `Core` / `Full` choice are removed.
- Help menu: **Switch Edition (Core / Full)** is gone; **Personalise SpeechCraft…** replaces it.
- **Piper engine** now reads `en_GB.cori` / `en_GB.alan` from the feature_manager install dir, downloading on demand when missing — replaces the hardcoded dead `en_ZA` URLs.
- **faster-whisper transcriber** prefers a locally installed `tiny.en` / `base.en` model from feature_manager, falling back to faster-whisper's built-in lookup when not on disk.
- **NSIS installer** — `DisplayVersion` corrected from `1.1.0` to `1.3.0`, edition-choice text reframed for v1.3.0 semantics (Core = on-demand model downloads, Full = all models pre-bundled), `ReadMe.txt` bundled and shown on the finish page, uninstaller now cleans `%APPDATA%\SpeechCraft\feature_assets` while keeping the user's `setup.json`.

### Tests
- 81 new tests across the v1.3.0 PRs: `tests/test_feature_flags.py` (20 pure-logic), `tests/test_prefs.py` (10 pure-logic), `tests/test_setup_wizard.py` (21 — incl. 6-page wizard + download-page smoke), `tests/test_feature_manager.py` (26 pure-logic), `tests/test_feature_toggling.py` (18 pure-logic), `tests/test_menu_gating.py` (7 wx), `tests/test_engine_wiring.py` (6 pure-logic), `tests/test_setup_wizard_download_page.py` (5 wx), `tests/test_a11y_main_frame.py` (2 wx — main-frame + audio-setup dialog names pinned).
- Total: **263 passing**.

### Installer
- `installer/speechcraft_setup.nsi` + `installer/ReadMe.txt` — v1.3.0 feature-flag installer (Core/Full edition choice, SHA-verified model downloads, clean uninstall of downloaded assets while preserving user prefs).

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
