# SpeechCraft Audio

AI-powered desktop audio editing suite built with wxPython. Features speech-to-text transcription with word-level alignment, breath smoothing, studio recording, and real-time voice actor monitoring.

## Features

- **Transcription**: Faster Whisper (local, offline) with Google Speech Recognition fallback
- **Breath Smoothing**: Automatic breath detection and reduction
- **Studio Recording**: Real-time transcription during recording with line-by-line placement
- **Voice Actor Monitor**: Network-based remote recording for voice talent
- **Multi-track editing**: Layer and mix multiple audio tracks
- **Destructive editing**: Edit transcript text and sync audio automatically
- **TTS Engines**: Edge TTS (Microsoft, free, online), Piper (on-device neural, offline)
- **Effects**: Compressor, De-esser, EQ, Noise Gate, Normaliser, Room Remover, Auto-ducker

## Requirements

- Windows 10/11
- Python 3.11+
- FFmpeg (auto-downloaded on first run if missing)
- For Piper TTS: `piper.exe` plus its DLL bundle (`piper_phonemize.dll`, `onnxruntime*.dll`, `libtashkeel_model.ort`, `espeak-ng.dll`, `espeak-ng-data/`) — place `piper.exe` and the DLLs in the project root or somewhere on `PATH`. See [Piper setup notes](#piper-setup) below.
- For screen-reader use: NVDA 2024.1 or later, JAWS 2024 or later, or Narrator on Windows 11.

## Quick Start

```bash
pip install -r requirements.txt
python run_speechcraft.py
```

## Building

```bash
pip install pyinstaller
pyinstaller SpeechCraft_Studio.spec
```

## Piper setup

The Piper TTS engine expects to find `piper.exe` somewhere it can execute. The Python wrapper (`piper_tts_engine.py`) searches in this order:

1. The current working directory
2. Anywhere on `PATH`

If you do not have Piper installed yet, download the Windows release from <https://github.com/rhasspy/piper/releases> and extract it so `piper.exe` and the bundled DLLs sit either in this project folder or in a directory on your `PATH`.

When the Piper TTS dialog cannot find `piper.exe`, it shows a clear "Setup Error" message instead of crashing.

## How to report a bug

The fastest path is **Help → Report a Bug** inside the app. The dialog asks a few short questions (what you were doing, what you expected, steps to reproduce), auto-attaches the last lines of the local error log, and opens the GitHub issues page in your browser with everything pre-filled. The pre-filled URL is also copied to your clipboard so you can paste it into an email if you cannot open a browser right now.

If the app has crashed and you cannot reach the menu, relaunch `run_speechcraft.py` — the error log at `speechcraft_error.log` in the project folder will be picked up automatically.

You can also file issues directly at <https://github.com/trasles16-ux/speechcraft-audio/issues>.

## Testing with NVDA

Every dialog, combobox, and wxPython widget in this app should announce a meaningful name with NVDA — not "unknown", not "button", not blank. Before filing a bug, please confirm the control announces something useful when you Tab to it. If it does not, that is a real bug and worth reporting.

If you are contributing code (see [CONTRIBUTING.md](CONTRIBUTING.md)), every PR that adds or modifies a dialog must be tested with NVDA before merge.

## Known limitations

- **No automated test suite yet.** We rely on beta-tester reports and manual NVDA testing.
- **Piper voices** are community-trained; quality varies by voice.
- **Edge TTS** requires an internet connection.
- **The release workflow** bundles `piper_models/` and `espeak-ng-data/` only when they exist locally. A fresh CI build produces a "core" EXE without the Piper data folders.
- **Python 3.11** is the supported runtime. Python 3.12+ may work but is not tested.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and the PR process.

## Security

To report a vulnerability privately, email <tracy@tracysmith.co.za>. See [SECURITY.md](SECURITY.md) for the full disclosure policy.

## License

MIT — see [LICENSE](LICENSE).
