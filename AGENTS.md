# SpeechCraft Studio

wxPython desktop app for accessible audio editing and audio-description production.
Tracy Smith's personal project — MIT licensed, single maintainer.

## Project structure

```
speechcraft-audio/
├── audio_editor.py          # Main frame (2730 lines after PR #5 decomposition)
├── main_frame_tts.py        # TTS menu handlers (extracted, PR #5)
├── dialogs/
│   ├── effects_dialogs.py   # 6 effect/preset/batch dialogs (extracted, PR #3)
│   └── recording_dialogs.py # Recording + studio dialogs (extracted, PR #4)
├── auto_ducker.py           # Voice-activity-based ducking
├── breath_smoothing.py      # RMS-based breath detection + attenuation
├── word_alignment.py        # Word-level audio editing
├── config.py                # EQ/compressor/breath presets
├── preset_manager.py        # Custom preset save/load (wx-dependent)
├── tests/
│   ├── test_dialog_smoke.py # 27 tests: imports, mixin wiring, dialog constructs
│   ├── test_pure_logic.py   # 21 tests: auto_ducker, breath_smoothing, word_alignment, config
│   └── conftest.py          # Session-scoped wx_app fixture
```

## Dev environment

```bash
cd C:/Users/trace/Documents/AppProjects/speechcraft-audio
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_speechcraft.py      # Launch app
```

wxPython 4.x required. Python 3.11.

## Build & test

```bash
pytest tests/                      # All tests (unit + smoke)
pytest tests/test_pure_logic.py    # Pure logic (no wx needed)
pytest tests/test_dialog_smoke.py  # Dialog imports + constructs
pytest tests/test_pure_logic.py -v --tb=short
```

CI runs on GitHub Actions:
- **Smoke** (Linux, no wx): import tests + pure-logic tests pass
- **Full** (Windows, wx installed): all 48 tests pass
- **Build**: PyInstaller produces `SpeechCraft-Windows.zip`

## Test commands

```bash
# Run all tests
pytest tests/ -v

# Run only pure-logic tests (Linux-compatible)
pytest tests/test_pure_logic.py -v

# Run only dialog tests
pytest tests/test_dialog_smoke.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

## Decomposition history

| PR | Change | Lines moved |
|----|--------|-------------|
| #3 | Extract effects dialogs → `dialogs/effects_dialogs.py` | 83→1660 |
| #4 | Extract recording dialogs → `dialogs/recording_dialogs.py` | 2956→3499 |
| #5 | Extract TTS handlers → `main_frame_tts.py` (mixin) | 240 |
| #6 | Functional dialog tests + bug fixes | — |
| #7 | Pure-logic module tests | — |

`audio_editor.py` reduced from 5091 → 2730 lines (−46%).

## Conventions

- wxPython 4.x; `wx.App` singleton — use session-scoped fixture in tests
- Module-level docstrings explain the **contract** (what `self` methods are called)
- Mixins document their frame dependencies in the class docstring
- Tests use `needs_wx` / `needs_sounddevice` skip markers for CI portability
- No hard-coded paths — use `Path(__file__).resolve().parent` for project-root-relative paths
- Error dialogs: use `wx.MessageBox` with `wx.ICON_WARNING` / `wx.ICON_ERROR`
- NVDA accessibility: all `wx.Choice`/`wx.TextCtrl` get `.SetName()` for screen-reader announcements

## Pitfalls

- **sounddevice missing on Linux**: `dialogs.effects_dialogs` imports it at module load. Gate AudioClipboard tests with `needs_sounddevice`.
- **wx.App singleton**: create once per test session via `conftest.py` `wx_app` fixture. Don't create per-test.
- **GetSizerAndFit() doesn't exist**: use `sizer.Layout(); sizer.Fit(panel)` instead.
- **LB_READONLY invalid**: wxPython 4.x uses `LBS_READONLY` for listbox styles, but this constant doesn't exist — use `wx.LB_SINGLE` only.
- **parent=None in tests**: dialogs that call `GetParent().GetSizer().Fit()` crash. Guard with `if parent is not None`.
- **GitHub PAT**: repo is public (MIT), no PAT needed. Use `gh` CLI with `trasles16-ux` token from `Documents/Personal/AppProjects/describeAT Dev PAT.txt`.
- **Force push after rebase**: test branches get rebased onto main frequently. Use `--force-with-lease` not `--force`.
