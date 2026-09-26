"""Regression tests: wizard announces page changes to NVDA (bug #5).

v1.3.2 shipped a wizard whose tab navigation NVDA didn't read:
no page-landing announcement and description labels announced
as the low-value "X description". Fix: a status bar on the dialog
(the channel NVDA watches without stealing focus), focus landing
on each page's heading on navigation, and real description text
as the accessible name of the sub-labels.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

needs_wx = pytest.mark.skipif(
    not importlib.util.find_spec("wx"),
    reason="wxPython not installed",
)

pytestmark = pytest.mark.usefixtures("wx_app")


def _open_wizard(tmp_path):
    from setup_wizard import SetupWizardDialog

    dlg = SetupWizardDialog(
        parent=None,
        prefs_file=tmp_path / "setup.json",
    )
    return dlg


@needs_wx
def test_wizard_has_status_bar_channel(wx_app, tmp_path):
    """The dialog carries a status bar NVDA reads on page changes."""
    dlg = _open_wizard(tmp_path)
    try:
        assert dlg._status is not None
        # Initial state: page 1 announcement is live on construction.
        assert "Page 1" in dlg._status.GetStatusText()
        assert "Welcome" in dlg._status.GetStatusText()
    finally:
        dlg.Destroy()


@needs_wx
def test_page_change_updates_status_text(wx_app, tmp_path):
    """Navigating forward announces the new page in the status bar."""
    dlg = _open_wizard(tmp_path)
    try:
        dlg._notebook.SetSelection(1)  # -> Editing features
        assert "Page 2 of 6" in dlg._status.GetStatusText()
        assert "Editing features" in dlg._status.GetStatusText()

        dlg._notebook.SetSelection(2)  # -> TTS engines
        assert "Page 3 of 6" in dlg._status.GetStatusText()
    finally:
        dlg.Destroy()


@needs_wx
def test_focus_lands_on_page_heading(wx_app, tmp_path):
    """After navigation, focus is on the page's first interactive control
    so NVDA reads something actionable on the focus change.

    v1.3.7 update: v1.3.3 landed focus on the page heading (a
    StaticText), which wxMSW accepts as a silent no-op — NVDA never
    announced it. The contract is now "first shown, enabled control";
    this test pins that the target accepts focus for real."""
    import wx

    dlg = _open_wizard(tmp_path)
    try:
        dlg._notebook.SetSelection(1)
        focused = dlg._focus_page_content()
        assert focused is not None
        assert focused.AcceptsFocus()
        assert not isinstance(focused, wx.StaticText)

        dlg._notebook.SetSelection(5)  # -> Summary
        focused = dlg._focus_page_content()
        # The Summary page has no interactive control (the Finish
        # button lives on the dialog's nav bar). v1.3.7's contract:
        # return None there instead of silently focusing a StaticText.
        assert focused is None
    finally:
        dlg.Destroy()


@needs_wx
def test_checkbox_description_names_are_real_text(wx_app, tmp_path):
    """Sub-labels announce the actual description, not 'X description'."""
    from feature_flags import FEATURE_DESCRIPTIONS

    dlg = _open_wizard(tmp_path)
    try:
        assert len(dlg._editing._descriptions) == len(dlg._editing.checkboxes)
        for name in dlg._editing.checkboxes:
            desc = dlg._editing._descriptions[name]
            # The accessible name must equal the visible description
            # text — that's what NVDA reads.
            assert desc.GetName() == FEATURE_DESCRIPTIONS[name]
    finally:
        dlg.Destroy()


@needs_wx
def test_pages_expose_heading_attr(wx_app, tmp_path):
    """Every wizard page exposes _heading for focus-landing."""
    dlg = _open_wizard(tmp_path)
    try:
        for page in (
            dlg._welcome, dlg._editing, dlg._tts,
            dlg._download, dlg._data, dlg._summary,
        ):
            assert getattr(page, "_heading", None) is not None, \
                f"{page.GetName()} has no _heading"
            assert page._heading.GetName()
    finally:
        dlg.Destroy()
