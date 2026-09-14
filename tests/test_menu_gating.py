"""Tests for audio_editor._apply_feature_gates (needs wx + audio_editor)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

needs_wx = pytest.mark.skipif(
    sys.platform == "linux", reason="wxPython not available on Linux CI")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_item(enabled: bool = True):
    """A stand-in for a wx.MenuItem that records its enabled state."""

    class _FakeItem:
        def __init__(self) -> None:
            self._enabled = enabled

        def Enable(self, on: bool) -> None:
            self._enabled = bool(on)

        def IsEnabled(self) -> bool:
            return self._enabled

    return _FakeItem()


def _make_frame(*,
                transcribe=None,
                line_placer=None,
                pedalboard=None,
                edge=None,
                piper=None,
                edit_mode=None) -> object:
    """Bare frame exposing only the menu-item attributes the gates touch."""
    import wx

    class _Frame(wx.Frame):
        pass

    frame = _Frame(None, wx.ID_ANY, "gates-test")
    frame.transcribe_item = _make_item() if transcribe else None
    frame.line_placer_item = _make_item() if line_placer else None
    frame.effects_pedalboard_items = [
        _make_item() for _ in range(pedalboard or 0)]
    frame.edge_tts_item = _make_item() if edge else None
    frame.piper_tts_item = _make_item() if piper else None
    frame.edit_mode_item = _make_item() if edit_mode else None
    return frame


def _run_gates(frame, flags):
    """Invoke the real _apply_feature_gates on the bare frame."""
    import audio_editor
    import feature_flags
    with patch.object(feature_flags, "load_feature_flags", return_value=flags):
        audio_editor.SpeechCraftFrame._apply_feature_gates(frame)
    return frame


@needs_wx
def test_gates_disable_transcription_when_local_and_cloud_off(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx
    from feature_flags import FeatureFlags

    flags = FeatureFlags(local_transcription=False, cloud_transcription=False)
    frame = _make_frame(transcribe=True, line_placer=True)
    _run_gates(frame, flags)
    assert not frame.transcribe_item.IsEnabled()
    assert not frame.line_placer_item.IsEnabled()


@needs_wx
def test_gates_enable_transcription_when_local_on(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx
    from feature_flags import FeatureFlags

    flags = FeatureFlags(local_transcription=True, cloud_transcription=False)
    frame = _make_frame(transcribe=True, line_placer=True)
    _run_gates(frame, flags)
    assert frame.transcribe_item.IsEnabled()
    # Line placing becomes usable because a transcriber is available
    assert frame.line_placer_item.IsEnabled()


@needs_wx
def test_gates_disable_pedalboard_effects_when_flag_off(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx
    from feature_flags import FeatureFlags

    flags = FeatureFlags(pedalboard_effects=False)
    frame = _make_frame(pedalboard=5)
    _run_gates(frame, flags)
    assert all(not item.IsEnabled() for item in frame.effects_pedalboard_items)


@needs_wx
def test_gates_keep_pedalboard_effects_when_flag_on(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx
    from feature_flags import FeatureFlags

    flags = FeatureFlags(pedalboard_effects=True)
    frame = _make_frame(pedalboard=5)
    _run_gates(frame, flags)
    assert all(item.IsEnabled() for item in frame.effects_pedalboard_items)


@needs_wx
def test_gates_toggle_tts_items_independently(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx
    from feature_flags import FeatureFlags

    flags = FeatureFlags(edge_tts=False, piper_tts=True)
    frame = _make_frame(edge=True, piper=True)
    _run_gates(frame, flags)
    assert not frame.edge_tts_item.IsEnabled()
    assert frame.piper_tts_item.IsEnabled()


@needs_wx
def test_gates_fail_open_when_flags_unavailable(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx

    frame = _make_frame(transcribe=True, pedalboard=3, edge=True, piper=True)

    def _boom():
        raise FileNotFoundError("setup.json missing")

    import audio_editor
    import feature_flags
    with patch.object(feature_flags, "load_feature_flags", side_effect=_boom):
        audio_editor.SpeechCraftFrame._apply_feature_gates(frame)
    # Fail-open: nothing gets disabled, so all items stay enabled
    assert frame.transcribe_item.IsEnabled()
    assert all(item.IsEnabled() for item in frame.effects_pedalboard_items)


@needs_wx
def test_gates_ignore_missing_items_safely(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx
    from feature_flags import FeatureFlags

    flags = FeatureFlags()
    # No items at all — should not raise
    frame = _make_frame()
    _run_gates(frame, flags)
    assert frame.transcribe_item is None
    assert frame.effects_pedalboard_items == []
