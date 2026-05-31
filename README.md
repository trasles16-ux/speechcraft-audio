# SpeechCraft Audio

AI-powered desktop audio editing suite built with wxPython. Features speech-to-text transcription with word-level alignment, breath smoothing, studio recording, and real-time voice actor monitoring.

## Features

- **Transcription**: Faster Whisper (local, offline) with Google Speech Recognition fallback
- **Breath Smoothing**: Automatic breath detection and reduction
- **Studio Recording**: Real-time transcription during recording with line-by-line placement
- **Voice Actor Monitor**: Network-based remote recording for voice talent
- **Multi-track editing**: Layer and mix multiple audio tracks
- **Destructive editing**: Edit transcript text and sync audio automatically
- **TTS Engines**: Edge TTS, Piper (on-device neural), Masakhane (African languages)
- **Effects**: Compressor, De-esser, EQ, Noise Gate, Normaliser, Room Remover, Auto-ducker

## Requirements

- Windows 10/11
- Python 3.11+
- FFmpeg (auto-downloaded on first run if missing)

## Quick Start

```bash
pip install -r requirements.txt
python run_speechcraft.py
```

## Building

```bash
pip install pyinstaller
pyinstaller SpeechCraft.spec
```

## License

MIT
