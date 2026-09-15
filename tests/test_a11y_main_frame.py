"""Regression tests: main frame + inline audio-setup dialog expose
meaningful NVDA accessible names on every control.

NVDA reads ``widget.GetName()`` and nothing else. wxPython's defaults
for ``wx.ListBox`` / ``wx.TextCtrl`` / ``wx.Gauge`` are uninformative
("listBox", "textCtrl", "gauge"). These tests pin the names so a
future refactor that drops the SetName calls fails loudly instead of
silently shipping a screen-reader-unfriendly build.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

needs_wx = pytest.mark.skipif(
    sys.platform == "linux", reason="wxPython not available on Linux CI")


# ── Main frame: init_ui region controls ─────────────────────────────────

@needs_wx
def test_main_frame_regions_have_meaningful_names(wx_app):
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx
    import audio_editor

    # Build a bare frame and invoke only the UI construction method,
    # avoiding the full __init__ (ffmpeg check, sounddevice import, etc.)
    frame = audio_editor.SpeechCraftFrame.__new__(audio_editor.SpeechCraftFrame)
    frame.__init__ = lambda *a, **k: None  # neutralise
    # Minimal wx.Frame super-init so SetName etc. work
    wx.Frame.__init__(frame, parent=None, title="SpeechCraft Studio", size=(100, 100))
    try:
        frame.init_ui()

        # Panel
        assert frame.panel.GetName() == "SpeechCraft main panel"
        # Region 1
        assert frame.tracks_label.GetName() != ""
        assert "track" in frame.tracks_list.GetName().lower()
        # Region 2
        assert frame.workspace.GetName() != ""
        assert "transcript" in frame.workspace.GetName().lower()
        # Region 3
        assert frame.log_area.GetName() != ""
        assert "log" in frame.log_area.GetName().lower()
    finally:
        frame.Destroy()


# ── Audio setup dialog: comboboxes, gauge, buttons ─────────────────────

@needs_wx
def test_audio_setup_dialog_controls_are_named(wx_app):
    """on_audio_setup builds the dialog inline; we can't call it without
    a real frame, so we assert the SetName calls are present in source
    by scanning for the exact strings. This is a source-level pin that
    catches a refactor removing the SetName line before it reaches a
    runtime test."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "audio_editor.py"
    text = src.read_text()

    expected_names = (
        "Advanced audio setup dialog. Choose audio engine, input and output devices, and test them.",
        "Audio engine selection. Options: SoundDevice WASAPI or MME, PyAudio compatibility, or Custom ASIO for ultra-low latency.",
        "Playback output device selection",
        "Microphone input device selection",
        "Microphone level gauge. Shows current input level as a percentage from quiet to loud.",
        "Toggle the live microphone level monitor. Currently stopped.",
        "Play a short test tone through the selected output device to verify playback",
        "Record a two-second test from the selected microphone and play it back on the output device",
        "Apply the audio engine and device selections and close the dialog",
    )
    for name in expected_names:
        assert name in text, f"missing SetName: {name!r}"
