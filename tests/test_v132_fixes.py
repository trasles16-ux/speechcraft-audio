"""Regression tests for v1.3.2 fixes.

Covers:
- load_audio detects ffmpeg-missing vs audio-file-missing via e.filename
- _run_update_download wraps the worker thread so non-UpdateCheckError
  exceptions surface as a user-facing failure dialog instead of vanishing
- _quit_for_update uses wx.Exit (not os._exit) so the interpreter shuts
  down cleanly instead of producing exit code -22 (STATUS_INVALID_PARAMETER)
"""

from __future__ import annotations

import ast
import io
import sys
import unittest.mock as mock
from pathlib import Path

import pytest


# ── Static checks (no wx, run anywhere) ────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_load_audio_detects_ffmpeg_missing_via_e_filename():
    """Pin: load_audio must inspect e.filename to distinguish ffmpeg-missing
    (which Pydub presents as FileNotFoundError with filename=path/to/ffmpeg.exe)
    from audio-file-missing. The bug it regresses: the old code reported the
    audio path in the dialog, telling the user 'file not found' when the
    actual cause was a missing/bundled ffmpeg binary.
    """
    src = (PROJECT_ROOT / "audio_editor.py").read_text(encoding="utf-8")
    # The fix uses e.filename and looks for 'ffmpeg'/'ffprobe'
    assert "e.filename" in src
    assert "ffmpeg" in src and "ffprobe" in src
    # Find the load_audio function and verify the ffmpeg-missing dialog exists
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "load_audio"
    )
    src_func = ast.get_source_segment(src, func) or ""
    assert '"FFmpeg Missing"' in src_func
    # And the genuine 'file not found' dialog still exists
    assert '"Cannot Open Audio"' in src_func
    # Both checks should be inside FileNotFoundError except branch
    assert "FileNotFoundError" in src_func


def test_update_worker_wrapped_in_broad_except():
    """Pin: the daemon thread body in _run_update_download must catch a
    broad Exception (not just UpdateCheckError), because wxPython silently
    swallows thread exceptions, producing the 'clicked Update, nothing
    happens' bug class.
    """
    src = (PROJECT_ROOT / "audio_editor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_run_update_download"
    )
    src_func = ast.get_source_segment(src, func) or ""
    # The inner _worker must contain a bare 'except Exception' that calls
    # _on_download_failed
    assert "except Exception" in src_func
    # And it should still catch the specific UpdateCheckError first
    assert "UpdateCheckError" in src_func
    assert "_on_download_failed" in src_func


def test_quit_for_update_uses_wx_exit_not_os_exit():
    """Pin: _quit_for_update must not call os._exit. os._exit skips the
    interpreter shutdown which can kill alive sounddevice streams, producing
    exit code -22 (STATUS_INVALID_PARAMETER) on Windows.
    """
    src = (PROJECT_ROOT / "audio_editor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_quit_for_update"
    )
    src_func = ast.get_source_segment(src, func) or ""
    # Strip Python comments so the explanatory comment that mentions
    # 'os._exit' as the thing-being-avoided doesn't trip the test.
    code_only = "\n".join(
        line.split("#", 1)[0] for line in src_func.splitlines()
    )
    # must use wx.Exit
    assert "wx.Exit" in code_only
    # must NOT call os._exit
    assert "os._exit" not in code_only


def test_run_update_download_includes_prelaunch_hint():
    """Pin: _on_download_verified should show the user a heads-up before
    SpeechCraft closes, so the user knows an installer should be appearing
    in a few seconds — gives them a chance to notice if SmartScreen/UAC
    is blocking the spawn.
    """
    src = (PROJECT_ROOT / "audio_editor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_on_download_verified"
    )
    src_func = ast.get_source_segment(src, func) or ""
    assert "Installer starting" in src_func or "about to close" in src_func


# ── Behavioural test: worker thread guard (needs wx, skipped on Linux) ──

needs_wx = pytest.mark.skipif(
    sys.platform == "linux", reason="wxPython not available on Linux CI")


@needs_wx
def test_run_update_download_surfaces_unexpected_exceptions(wx_app):
    """When download_with_progress raises a non-UpdateCheckError exception,
    _on_download_failed must still be invoked with a useful message.
    Previously, the worker thread would die silently and the user saw a
    0% progress bar forever — the root cause of Paul's report.
    """
    if wx_app is None:
        pytest.skip("wxPython not installed")

    # Build a bare frame, like test_menu_gating does, so we don't pay for
    # the full SpeechCraftFrame.__init__ (ffmpeg check, lazy module
    # imports, etc.).
    import wx
    import audio_editor
    frame = audio_editor.SpeechCraftFrame.__new__(audio_editor.SpeechCraftFrame)
    wx.Frame.__init__(frame, parent=None, title="test", size=(100, 100))

    try:
        # Stub _on_download_failed to capture the call
        fail_calls = []
        frame._on_download_failed = lambda msg: fail_calls.append(msg)

        # Build a fake UpdateInfo
        from updater import UpdateInfo, AssetInfo
        info = UpdateInfo(
            version="9.9.9",
            url="https://example.com/release",
            title="v9.9.9",
            notes="",
            published_at="",
            assets=(AssetInfo(
                name="SpeechCraft_Studio_Setup.exe",
                url="https://example.com/setup.exe",
                size_bytes=1024),),
        )

        # The download call raises a bare OSError (not UpdateCheckError).
        with mock.patch("updater.download_with_progress",
                        side_effect=OSError("network unreachable")):
            try:
                frame._run_update_download(info)
            except Exception as exc:
                # If _run_update_download itself errors before scheduling
                # the worker, that's a regression — fail loud.
                pytest.fail(f"_run_update_download raised: {exc}")

        # Give the (daemon) worker a moment to run and call wx.CallAfter
        import time
        for _ in range(40):  # up to ~4s
            wx.Yield()
            time.sleep(0.1)
            if fail_calls:
                break

        assert fail_calls, (
            "Worker thread died with OSError but _on_download_failed "
            "was never invoked — exception guard regression."
        )
        # The surfaced message should mention 'Unexpected error' or
        # 'OSError', not just 'OSError: network unreachable' silently.
        assert any(
            "Unexpected error" in msg or "OSError" in msg
            for msg in fail_calls
        )
    finally:
        frame.Destroy()
