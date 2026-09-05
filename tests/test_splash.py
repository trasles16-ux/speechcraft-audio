"""Smoke tests for the Splash window.

The Splash class is a wx.Frame so tests need an alive wx App. We use
the session-scoped ``wx_app`` fixture from conftest.
"""

from __future__ import annotations

import pytest

pytest.importorskip("wx")

from splash import Splash, STARTUP_STEPS


@pytest.fixture
def splash(wx_app):
    """Create a Splash against the session wx App and tear it down."""
    s = Splash()
    yield s
    s.close()


def test_splash_window_appears(splash):
    """The splash window exists and is visible."""
    assert splash.IsShown()


def test_splash_window_has_accessible_name(splash):
    """The window itself has a discoverable name for NVDA."""
    assert "SpeechCraft Studio" in splash.GetName()


def test_step_marks_starts_empty(splash):
    """All step marks begin as '○' (pending)."""
    for step in STARTUP_STEPS:
        marker = splash._step_labels[step]
        assert marker.GetLabel() == "○", f"{step} should start pending"


def test_update_marks_step_complete(splash):
    """Calling update() flips the marker to ✓ and updates accessibility name."""
    first_step = STARTUP_STEPS[0]
    splash.update(first_step)
    marker = splash._step_labels[first_step]
    assert marker.GetLabel() == "✓"
    # Accessible name should have updated, so NVDA reannounces.
    assert "complete" in marker.GetName().lower()


def test_update_sets_status_message(splash):
    """Status text becomes the bottom-line label and the announced name."""
    splash.update("Loading user interface", "Reading FFmpeg path")
    assert splash._status.GetLabel() == "Reading FFmpeg path"
    assert "Reading FFmpeg path" in splash._status.GetName()


def test_double_update_is_idempotent(splash):
    """Calling update(step) twice leaves the step as ✓ but doesn't crash."""
    step = STARTUP_STEPS[1]
    splash.update(step)
    splash.update(step)
    assert splash._step_labels[step].GetLabel() == "✓"


def test_close_then_close_does_not_raise(splash):
    """close() is safe to call after the window already closed."""
    splash.close()
    splash.close()  # second call must not raise


def test_escape_does_not_raise(splash):
    """Pressing Escape closes the splash (developer escape hatch)."""
    # Trigger the same code path Escape would.
    import wx

    event = wx.KeyEvent(wx.EVT_CHAR_HOOK.typeId)
    event.SetKeyCode(wx.WXK_ESCAPE)
    splash._on_char(event)
    # No assert — just verifying no exception propagates.
