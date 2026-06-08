# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

here = os.path.dirname(os.path.abspath(SPEC))

datas = [
    ('help', 'help'),
    ('piper_models', 'piper_models'),
    ('espeak-ng-data', 'espeak-ng-data'),
]
binaries = []
hiddenimports = [
    # Core
    'wx',
    # Audio — standard Python
    'pyttsx3.drivers',
    'pyttsx3.drivers.sapi5',
    'sounddevice',
    'pyaudio',
    # Audio — compiled/native extensions (explicit so PyInstaller doesn't miss them)
    'pedalboard',
    'pedalboard._pedalboard',
    'pedalboard_native',
    'librosa',
    'librosa.core',
    'librosa.display',
    'scipy',
    'scipy.signal',
    'numpy',
    'numpy.core._multiarray_umath',
    'numpy.linalg._umath_linalg',
    # Speech engines
    'speech_recognition',
    'edge_tts',
    'edge_tts_engine',
    'masakhane_tts_engine',
    'piper_tts_engine',
    # Logic modules (safe_import in audio_editor.py)
    'audio_tracks',
    'project_handler',
    'config',
    'preset_manager',
    'batch_processor',
    'transcription',
    'breath_smoothing',
    'auto_ducker',
    'audio_effects',
    'line_placer',
    'script_handler',
    'word_alignment',
    'audio_recorder',
    'studio_recorder',
    'braille_support',
    'accessibility_scan',
    'network_monitor',
    'custom_asio',
    # Windows
    'win32api',
    'win32process',
    'win32con',
    'win32gui',
    'win32file',
]
# Collect all complex package dependencies
for pkg in ['pydub', 'wx', 'numpy', 'edge_tts', 'librosa', 'pedalboard', 'scipy']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

# Include FFmpeg if present locally
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
    excludes=[],
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
    name='SpeechCraft_Studio',
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
