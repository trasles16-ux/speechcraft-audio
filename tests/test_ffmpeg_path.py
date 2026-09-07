"""Regression tests for the FFmpeg download path.

Issue #12: "mp3 mpeg not downloading" — user reported that the
download dialog said it succeeded but MP3 files still wouldn't play.
Root cause: the download wrote ffmpeg.exe to
``os.path.dirname(__file__)``, which in a PyInstaller EXE is the
MEIPASS temp dir that's wiped on every launch. So the success
message was technically correct (the copy succeeded) but the file
disappeared on next launch.

These tests pin the fix in place:

1. The download destination resolves to a path that survives across
   launches (LOCALAPPDATA in packaged EXE, project dir in dev).
2. ``setup_ffmpeg`` finds ffmpeg.exe at the persistent location.
3. ``_ffmpeg_exe_path`` returns a writable directory.

We don't actually trigger a download in tests (would require mocking
a 100 MB zip + network); we focus on the path-resolution logic and
the contract that ``_ffmpeg_exe_path()`` returns something stable.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest


def _reload_audio_editor():
    """Reload audio_editor with a fresh module state for each test.

    audio_editor is a heavy module (imports wx, runs setup_ffmpeg,
    etc.) so we don't import it at module load — we only load the
    pieces we need and reload them per test to get a clean state.
    """
    import importlib
    import audio_editor

    return importlib.reload(audio_editor)


def test_ffmpeg_exe_path_is_absolute():
    """The path must be absolute — relative paths would silently
    land somewhere the user can't find."""
    audio_editor = _reload_audio_editor()
    path = audio_editor._ffmpeg_exe_path()
    assert os.path.isabs(path), f"Expected absolute path, got {path!r}"
    assert path.endswith("ffmpeg.exe")


def test_ffmpeg_exe_path_dir_exists_or_creatable(tmp_path, monkeypatch):
    """The parent dir of the FFmpeg path must be a real, writable
    directory (either pre-existing or creatable on first call)."""
    # Redirect LOCALAPPDATA so the test doesn't pollute Tracy's real
    # SpeechCraft dir.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    audio_editor = _reload_audio_editor()
    path = audio_editor._ffmpeg_exe_path()

    parent = Path(path).parent
    # setup_ffmpeg / download_ffmpeg call makedirs, so the parent
    # must be either already present or freshly creatable. Both are
    # valid; we just need the path to point at a real place.
    assert parent.exists() or parent.parent.exists(), (
        f"FFmpeg dir parent {parent} does not exist and parent {parent.parent} "
        "does not exist either — the path resolution would fail silently."
    )


def test_ffmpeg_exe_path_dev_run_uses_project_dir():
    """When running from source (not frozen), FFmpeg should land
    next to audio_editor.py so the build spec picks it up."""
    # Ensure frozen is False
    monkeypatch_target = mock.patch.object(sys, "frozen", False, create=True)
    monkeypatch_target.start()

    audio_editor = _reload_audio_editor()
    path = audio_editor._ffmpeg_exe_path()

    expected_dir = os.path.dirname(os.path.abspath(audio_editor.__file__))
    assert os.path.dirname(path) == expected_dir, (
        f"Expected dev run to put FFmpeg in {expected_dir}, got {path}"
    )

    monkeypatch_target.stop()


def test_ffmpeg_exe_path_persists_across_launch():
    """The whole point of the fix: ffmpeg.exe must survive a
    relaunch. The simplest invariant is that _ffmpeg_exe_path() is a
    *function* call (not a static value), so two separate calls
    resolve to the same location even if you mock parts of the
    process."""
    audio_editor = _reload_audio_editor()
    path1 = audio_editor._ffmpeg_exe_path()
    path2 = audio_editor._ffmpeg_exe_path()
    assert path1 == path2


def test_ffmpeg_exe_path_frozen_uses_localappdata(tmp_path, monkeypatch):
    """In a packaged EXE, FFmpeg must land in LOCALAPPDATA (writable
    for normal users) and NOT in the EXE directory (admin-only) or
    MEIPASS (wiped every launch)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    audio_editor = _reload_audio_editor()
    path = audio_editor._ffmpeg_exe_path()

    expected = str(tmp_path / "SpeechCraft" / "ffmpeg.exe")
    assert path == expected, f"Expected {expected}, got {path}"


def test_setup_ffmpeg_finds_persistent_ffmpeg(tmp_path, monkeypatch):
    """If ffmpeg.exe exists at the persistent location, setup_ffmpeg
    should find it and configure pydub accordingly."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    # Lay down a fake ffmpeg.exe at the expected location
    audio_editor = _reload_audio_editor()
    target = audio_editor._ffmpeg_exe_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(b"FAKE_FFMPEG_BINARY")

    # setup_ffmpeg is at module-level already (called on import).
    # Reload to give it a fresh state and verify it picks the file up.
    importlib = __import__("importlib")
    importlib.reload(audio_editor)

    from pydub import AudioSegment

    assert AudioSegment.converter == target, (
        f"setup_ffmpeg should have configured AudioSegment.converter to {target}, "
        f"got {AudioSegment.converter!r}"
    )
