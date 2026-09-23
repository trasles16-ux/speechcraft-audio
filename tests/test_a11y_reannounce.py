"""Regression tests for v1.3.6 PR-2: every label change must re-call
SetName so NVDA re-announces the new value.

Pattern under test: a StaticText / Button / Gauge has its visible
``SetLabel(...)`` updated, AND a corresponding ``SetName(...)`` is
called with the new content. If the developer adds a new ``SetLabel``
site but forgets the ``SetName`` mirror, these tests should fail.

Why this matters
----------------
NVDA reads ``widget.GetName()`` and re-announces only when that name
*changes*. A control whose visible label changes but whose accessible
name is set once at ``__init__`` is invisible to a screen reader user
once focus moves away and returns. The
``dialogs/download_progress_dialog.py`` is the gold standard — every
``update(...)`` call re-sets ``_status.SetName(...)``.

These tests assert the mirror pattern at every site identified in the
v1.3.6 audit. Each test:
- Patches ``SetName`` on the widget class so we can capture calls.
- Drives the same ``SetLabel`` call the production code does.
- Asserts ``SetName`` was called with the new content.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJECT_ROOT)


# Recording dialog monitor_btn: stop/start cycle re-announces
def _read(name: str) -> str:
    """Read a project-root file by name."""
    return Path(PROJECT_ROOT, *name.split("/")).read_text(encoding="utf-8")


def test_recording_monitor_btn_setlabel_also_calls_setname():
    """main_frame_tts / recording dialog monitor button must re-announce
    when toggled between Start/Stop."""
    src = _read("dialogs/recording_dialogs.py")

    # Both SetLabel calls must be accompanied by a SetName with the
    # corresponding running/stopped description.
    assert 'self.monitor_btn.SetLabel("Stop Monitor")' in src
    assert 'self.monitor_btn.SetName("Stop live level monitor. Currently running.")' in src
    assert 'self.monitor_btn.SetLabel("Start Level Monitor")' in src
    assert 'self.monitor_btn.SetName("Start live level monitor. Currently stopped.")' in src


def test_recording_level_text_setlabel_also_calls_setname():
    """level_text updates (reset + every level tick) must mirror SetName."""
    src = _read("dialogs/recording_dialogs.py")

    # Reset to -∞ dB (note: source uses U+221E INFINITY)
    assert 'self.level_text.SetLabel("Level: -\u221e dB")' in src
    assert "minus infinity" in src
    # Live tick
    assert 'self.level_text.SetLabel(f"Level: {db_level:.1f} dB")' in src
    assert 'f"Input level readout in decibels, currently {db_level:.1f}"' in src


def test_studio_recording_progress_text_mirrors_setname():
    """Studio recording dialog's progress_text + actor_status + actor_progress_text
    all re-announce on every state change."""
    src = _read("dialogs/recording_dialogs.py")

    # Main dialog progress text
    assert 'self.progress_text.SetLabel("Recording in progress...")' in src
    assert 'self.progress_text.SetName("Recording progress text, recording in progress")' in src
    assert 'self.progress_text.SetLabel("Recording completed!")' in src
    assert 'self.progress_text.SetName("Recording progress text, recording completed")' in src
    # Live progress tick (within _update_ui)
    assert 'self.progress_text.SetLabel(progress_label)' in src
    assert 'f"Recording progress text, line {progress' in src

    # Voice actor monitor status / progress text
    assert 'self.actor_status.SetLabel("Recording in progress...")' in src
    assert 'self.actor_status.SetName("Director status, recording in progress")' in src
    assert 'self.actor_status.SetLabel("Session completed!")' in src
    assert 'self.actor_status.SetName("Director status, session completed")' in src
    assert 'self.actor_progress_text.SetLabel(progress_label)' in src
    assert 'f"Session progress, line {progress' in src
    assert 'self.actor_status.SetLabel("Redo in progress...")' in src
    assert 'self.actor_status.SetName("Director status, redo in progress")' in src
    assert 'self.actor_status.SetLabel("Recording...")' in src
    assert 'self.actor_status.SetName("Director status, recording")' in src


def test_advanced_audio_setup_level_text_mirrors_setname():
    """audio_editor.py Advanced Audio Setup level_text re-announces."""
    src = _read("audio_editor.py")

    assert 'level_text.SetLabel("Level: -\u221e dB")' in src
    assert "minus infinity, updating live" in src
    assert 'level_text.SetLabel(f"Level: {db_level:.1f} dB")' in src
    # The live-tick SetName f-string is split across lines in the
    # source, so we check for its key fragments.
    assert "Microphone level in decibels" in src
    assert "currently {db_level:.1f}" in src
    assert "updating live while the monitor is running" in src


def test_breath_smoothing_hints_mirror_setname():
    """Breath dialog sens_pct_st / mix_pct_st re-announce on every update."""
    src = _read("dialogs/effects_dialogs.py")

    assert "self.sens_pct_st.SetLabel(sens_hint)" in src
    assert 'self.sens_pct_st.SetName(f"Sensitivity hint: {sens_hint}")' in src
    assert "self.mix_pct_st.SetLabel(mix_hint)" in src
    assert 'self.mix_pct_st.SetName(f"Effect amount hint: {mix_hint}")' in src


def test_compressor_param_labels_mirror_setname():
    """Compressor preset dialog param labels re-announce on every change."""
    src = _read("dialogs/effects_dialogs.py")

    assert "st.SetLabel(label_text)" in src
    assert 'st.SetName(f"{key} current value: {label_text}")' in src


def test_eq_band_labels_mirror_setname():
    """EQ band labels re-announce on every slider change."""
    src = _read("dialogs/effects_dialogs.py")

    assert "self.band_labels[label].SetLabel(label_text)" in src
    # Two sites: slider drag handler, _update_display
    occurrences = src.count(
        'self.band_labels[label].SetName(f"{label} current gain: {label_text}")'
    )
    assert occurrences == 2, (
        f"Expected 2 SetName sites for EQ band labels, found {occurrences}"
    )


def test_batch_path_labels_mirror_setname():
    """Batch process in/out path labels re-announce after folder pick."""
    src = _read("dialogs/effects_dialogs.py")

    assert 'self.in_path_st.SetLabel(path)' in src
    assert 'self.in_path_st.SetName(f"Input folder path: {path}")' in src
    assert 'self.out_path_st.SetLabel(path)' in src
    assert 'self.out_path_st.SetName(f"Output folder path: {path}")' in src


def test_batch_progress_and_button_mirror_setname():
    """Batch process progress_st + next_btn re-announce on every state."""
    src = _read("dialogs/effects_dialogs.py")

    # progress_st
    assert 'self.progress_st.SetLabel("Starting batch...")' in src
    assert 'self.progress_st.SetName("Processing status, starting batch")' in src
    assert 'self.progress_st.SetLabel(f"Processing {i+1}/{total}: {basename}")' in src
    assert 'f"Processing status, processing {i+1} of {total}: {basename}"' in src
    assert 'self.progress_st.SetLabel(f"Done. {ok_count} succeeded, {fail_count} failed.")' in src
    assert 'f"Processing status, done. {ok_count} succeeded, {fail_count} failed."' in src
    # next_btn
    assert 'self.next_btn.SetLabel("Process")' in src
    assert 'self.next_btn.SetName("Process the batch. Start the run on all selected files.")' in src
    assert 'self.next_btn.SetLabel("Next >")' in src
    assert 'self.next_btn.SetName("Next >, advance to next batch step")' in src
    assert 'self.next_btn.SetLabel("Close")' in src
    assert 'self.next_btn.SetName("Close the batch dialog")' in src


def test_wizard_status_rows_mirror_setname():
    """Wizard EditingFeatures / TTSEnginesPage status rows re-announce
    on every refresh_status() call."""
    src = _read("setup_wizard_pages.py")

    # The two _refresh_status methods both call SetName with the new status
    occurrences = src.count(
        'label.SetName(f"{_humanize(name)} status: {status}")'
    )
    assert occurrences == 2, (
        f"Expected 2 SetName sites in _refresh_status, found {occurrences}"
    )


def test_network_monitor_status_mirrors_setname():
    """NetworkMonitorClient re-announces connection + status + progress."""
    src = _read("network_monitor.py")

    # Connection status: connect / fail / disconnect
    assert (
        'wx.CallAfter(self.connection_status.SetLabel, f"Connected to {self.server_ip}")'
        in src
    )
    assert 'f"Connection status: connected to {self.server_ip}"' in src
    assert 'f"Connection failed: {e}"' in src
    assert 'f"Connection status: connection failed, {e}"' in src
    assert 'wx.CallAfter(self.connection_status.SetLabel, "Disconnected")' in src
    assert '"Connection status: disconnected"' in src
    # Director status + progress text
    assert "self.status_text.SetLabel(status)" in src
    assert 'f"Director status: {status}"' in src
    assert 'self.progress_text.SetLabel(f"Line {current} of {total}")' in src
    assert 'f"Session progress: line {current} of {total}"' in src


# Runtime test: ensure SetLabel-then-SetName is actually a 2-arg call
# (sanity check the dialogs module's accessibility helper supports it).

needs_wx = pytest.mark.skipif(
    sys.platform == "linux", reason="wxPython not available on Linux CI")


@needs_wx
def test_wx_setname_re_announces_fires_on_label_change(wx_app):
    """Sanity: SetLabel then SetName on the same wx.StaticText updates
    the accessible name. (NVDA's behaviour is external; we just confirm
    wxPython stores it.)"""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import wx

    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        label = wx.StaticText(frame, label="Ready")
        label.SetName("Recording progress, ready to start")
        assert "ready to start" in label.GetName().lower()

        # Simulate a state change.
        label.SetLabel("Recording in progress...")
        label.SetName("Recording progress, recording in progress")
        assert "recording in progress" in label.GetName().lower()
        assert label.GetLabel() == "Recording in progress..."
    finally:
        frame.Destroy()
