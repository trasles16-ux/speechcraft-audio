# Changelog

All notable changes to SpeechCraft Audio are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/) as far as a single-developer desktop app can.

## [Unreleased]

### Added
- **In-app bug reporting**: Help → Report a Bug now opens a dialog that collects a description, expected behaviour, and reproduction steps; pre-fills the GitHub issues URL with those answers plus environment info; and copies the URL to the clipboard as a fallback. See [README § How to report a bug](README.md#how-to-report-a-bug).
- **Crash hook**: an uncaught exception now writes a redacted traceback to `speechcraft_error.log` and offers to open the bug-report dialog with the log tail pre-attached.
- **Piper "unknown" combobox fix**: the Piper TTS dialog now announces the voice list with a proper name to NVDA, and a missing `piper.exe` surfaces as a clear "Setup Error" message instead of a silent crash.
- **NVDA accessibility**: every TTS dialog's voice combobox now has an accessible name via `wx.Choice.SetName`.

### Removed
- **Masakhane TTS engine**: the engine, its menu item, dialog method, and PyInstaller spec entry were removed. The engine had no external callers and was the smallest of the three engines.

### Documentation
- README rewritten with NVDA testing guidance, Piper setup notes, known limitations, and a "How to report a bug" section.
- New: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`.
- New issue templates: bug report, feature request, accessibility issue.

## [3.0.2] — 2026

Initial public release on GitHub.
