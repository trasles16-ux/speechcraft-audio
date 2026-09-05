# -*- mode: python ; coding: utf-8 -*-
"""SpeechCraft Studio — Core build spec.

Builds without ``pedalboard``, ``librosa``, ``scipy``, ``faster_whisper``,
or ``torch``. The user can transcribe via Edge TTS, record, edit audio,
apply breath smoothing, compressor, de-esser, EQ, noise gate, normaliser,
and room tone match — but NOT advanced effects (which need pedalboard) and
NOT local Whisper transcription (which needs faster_whisper + torch).

Build with::

    pyinstaller SpeechCraft_Studio_Core.spec --noconfirm

Produces ``dist/SpeechCraft_Studio_Core.exe`` — ~150 MB instead of 435 MB.
Launches in roughly a third of the time because Defender has less to scan.
"""

from PyInstaller.utils.hooks import collect_all
import os

here = os.path.dirname(os.path.abspath(SPEC))

datas = []
for src, dst in [
    ('help', 'help'),
    ('piper_models', 'piper_models'),
    ('espeak-ng-data', 'espeak-ng-data'),
]:
    if os.path.exists(os.path.join(here, src)):
        datas.append((src, dst))

binaries = []
hiddenimports = [
    'wx',
    # Audio I/O
    'pyttsx3.drivers',
    'pyttsx3.drivers.sapi5',
    'sounddevice',
    'pyaudio',
    # Core numerical stuff
    'numpy',
    'numpy.core._multiarray_umath',
    'numpy.linalg._umath_linalg',
    # Speech engines — Edge + Piper stay in Core
    'speech_recognition',
    'edge_tts',
    'edge_tts_engine',
    'piper_tts_engine',
    # Project & UI modules
    'audio_tracks',
    'project_handler',
    'config',
    'preset_manager',
    'breath_smoothing',  # breath smoothing is core
    'auto_ducker',       # auto-ducker is core
    'line_placer',       # line placement is core
    'script_handler',
    'word_alignment',
    'audio_recorder',
    'studio_recorder',
    'braille_support',
    'accessibility_scan',
    'network_monitor',
    'custom_asio',
    # dialogs (Pure-Python classes; pyinst-x handles the heavy deps inside)
    # bundled inside dialogs/ package
    # Windows
    'win32api',
    'win32process',
    'win32con',
    'win32gui',
    'win32file',
    # EXPLICITLY EXCLUDED in Core: pedalboard, librosa, scipy, faster_whisper,
    # torch, batch_processor (which pulls in audio_effects → pedalboard),
    # audio_effects, transcription.

    # Available as lazy imports if user enables Full features later (see
    # onboarding_dialog.py)
]

# Bundled data for the included packages only — pedalboard / librosa / scipy
# are skipped so the bundle doesn't drag them in.
for pkg in ['pydub', 'wx', 'numpy', 'edge_tts']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

local_ffmpeg = os.path.join(here, 'ffmpeg.exe')
if os.path.exists(local_ffmpeg):
    datas.append(('ffmpeg.exe', '.'))

a = Analysis(
    ['audio_editor.py'],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Force PyInstaller to skip these even if something imports them
        # transitively. Saves ~280 MB.
        'pedalboard',
        'pedalboard._pedalboard',
        'pedalboard_native',
        'librosa',
        'librosa.core',
        'librosa.display',
        'scipy',
        'scipy.signal',
        'faster_whisper',
        'torch',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SpeechCraft_Studio_Core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
