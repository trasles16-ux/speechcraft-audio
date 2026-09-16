"""Regression tests: temp WAVs go to the user temp dir (v1.3.4).

Pre-v1.3.4, scratch WAVs were written CWD-relative. A Start-Menu
launch (CWD = install dir) dumped ~1.6 GB into C:\\Program Files,
and would have failed outright for a standard user. _temp_wav()
routes every call site to tempfile.gettempdir() instead.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile

import pytest

needs_wx = pytest.mark.skipif(
    not importlib.util.find_spec("wx"),
    reason="wxPython not installed",
)


@needs_wx
def test_temp_wav_lives_in_user_temp_dir():
    import audio_editor

    path = audio_editor._temp_wav("temp_playback.wav")
    assert path.startswith(tempfile.gettempdir())
    assert os.path.isabs(path)
    assert path.endswith("temp_playback.wav")


@needs_wx
def test_temp_wav_is_deterministic_per_name():
    """Every call site that asks for the same name gets the same file."""
    import audio_editor

    a = audio_editor._temp_wav("temp_playback.wav")
    b = audio_editor._temp_wav("temp_playback.wav")
    assert a == b
    c = audio_editor._temp_wav("temp_original.wav")
    assert a != c


def test_no_bare_cwd_temp_wav_references_in_editor():
    """The editor must not reference CWD-relative scratch WAV names.

    Source-scan: any leftover '"temp_*.wav"' string literal (that is
    NOT wrapped in _temp_wav(...)) would mean a call site that still
    writes to the CWD.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "audio_editor.py").read_text(
        encoding="utf-8"
    )
    # Every occurrence of the three scratch names must be inside a
    # _temp_wav(...) call (or inside the helper's own docstring).
    bare = []
    for line in src.splitlines():
        if re.search(r'["\']temp_(playback|original|processed)\.wav["\']', line):
            if "_temp_wav(" in line or "used to be CWD-relative" in line or "_temp_wav(name)" in line:
                continue
            if "def _temp_wav" in line or "speechcraft_{name}" in line:
                continue
            bare.append(line.strip())
    assert not bare, f"CWD-relative temp WAV references remain: {bare}"


def test_temp_wav_not_writable_to_program_files():
    """Sanity: the helper never produces a path under Program Files."""
    import audio_editor

    path = audio_editor._temp_wav("temp_playback.wav")
    assert "Program Files" not in path
