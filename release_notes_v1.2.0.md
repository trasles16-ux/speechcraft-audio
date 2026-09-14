# SpeechCraft Studio v1.2.0

Feature release. m4a import/export and full in-app auto-update.

## What's new

### m4a (AAC) audio support
File → Open Audio and File → Export Audio now support `.m4a` files in addition to `.wav` and `.mp3`. M4A is the format used by iPhone Voice Memos and many podcast tools, and gives higher quality at smaller file sizes than MP3.

FFmpeg is still required for non-WAV formats. If FFmpeg is missing, the existing error dialog now mentions M4A alongside MP3.

### In-app auto-update
Two seconds after SpeechCraft launches, it checks GitHub for a newer release. If one exists, an accessible prompt dialog appears with three choices:

- **Download and install vX.Y.Z** — starts the download immediately, verifies the installer against its published SHA-256, and runs it (SpeechCraft closes during install).
- **Skip version vX.Y.Z** — never remind about this version again.
- **Remind me next launch** — the default. Pressing Enter picks this, so a stray Enter never silently starts an installer.

The progress dialog shows a percentage gauge and a live status label with bytes downloaded, so NVDA users can track progress. The download can be cancelled mid-flight.

### Help → Check for updates…
The same flow is available any time from the Help menu, for users who'd rather check on demand than at launch.

### Security
Every installer download is verified against its published SHA-256 digest before it is launched. If GitHub publishes the digest on the asset itself we use that; otherwise we fetch a sibling `.sha256` file uploaded alongside it. A mismatch discards the file and surfaces a clear error dialog — SpeechCraft never runs an installer it hasn't verified.

## For users upgrading from v1.1.4

Just re-run the installer (`SpeechCraft_Studio_Setup.exe`) — it will install over the previous version.

## Tests

143 tests passing in the project venv (Linux smoke CI + Windows full CI):
- 36 pure-logic tests (22 existing + 14 new in `test_updater.py`)
- 30 dialog smoke tests (28 existing + 2 new for update + download dialogs)
- 14 build-artifact tests
- 63 other

## Credits

- Tracy Smith — feature design and implementation