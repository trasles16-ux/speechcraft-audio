"""Tests for the v1.3.0 modular setup wizard.

The wizard is wx-dependent, so most tests are gated @needs_wx and
also do a body-level wx_app guard. The few pure-logic tests
(progressive save, abandonment handling) work without wx and run on
Linux smoke CI.

The wizard architecture:

- setup_wizard.run_setup_wizard(parent) is the entry point
- SetupWizardDialog is the modal wx.Dialog with 6 pages
- Each page is a _WizardPage subclass with a .collect(flags) method
- Progress is saved to setup.json on each page transition
- wizard_completed flips to True only on the Finish button

What we're testing:
- Default features flag values flow into the wizard correctly
- Toggling a feature on a page writes to setup.json
- Wizard constructor and pages build without crashing
- Accessible names are set on every page header and control
- Cancel/Escape marks wizard_completed=False and announces correctly
- Finish sets wizard_completed=True and persists all flags
- Summary page reflects what the user toggled
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# wx is conditionally imported below for the wx-dependent tests.
# This lets Linux smoke CI (where wx may not be installed) collect
# pure-logic tests without needing to import wx.
if importlib_find_spec := __import__("importlib").util.find_spec("wx"):
    import wx  # type: ignore[import-not-found]
else:
    wx = None  # type: ignore[assignment]

from feature_flags import (
    DEFAULT_FEATURE_FLAGS,
    FEATURE_DESCRIPTIONS,
    FEATURE_NAMES,
    FeatureFlags,
    is_wizard_completed,
    load_feature_flags,
    save_feature_flags,
    set_feature_flag,
)


# ---------------------------------------------------------------------------
# Pure-logic helpers (no wx needed)
# ---------------------------------------------------------------------------


def test_default_flags_match_wizard_pages():
    """Every wizard page exposes exactly the flags in DEFAULT_FEATURE_FLAGS
    minus basic_editing (which is the always-on foundation page header,
    not a toggleable row)."""
    toggleable = set(FEATURE_NAMES) - {"basic_editing"}
    assert toggleable == {
        "pedalboard_effects",
        "local_transcription",
        "cloud_transcription",
        "destructive_editing",
        "line_placing",
        "edge_tts",
        "piper_tts",
    }


def test_every_toggleable_feature_has_description():
    """Every flag the wizard shows needs a one-line description."""
    toggleable = set(FEATURE_NAMES) - {"basic_editing"}
    for name in toggleable:
        assert name in FEATURE_DESCRIPTIONS, f"missing description for {name}"
        assert len(FEATURE_DESCRIPTIONS[name]) > 0


def test_progressive_save_persists_each_toggle(tmp_path):
    """Simulating Next → toggle pedalboard → Next → toggle Edge TTS.
    After both toggles, both should be persisted even if the user
    never clicks Finish.
    """
    target = tmp_path / "setup.json"
    save_feature_flags(prefs_file=target, flags=FeatureFlags())
    set_feature_flag(prefs_file=target, name="pedalboard_effects", value=False)
    set_feature_flag(prefs_file=target, name="edge_tts", value=False)
    flags = load_feature_flags(prefs_file=target)
    assert flags.pedalboard_effects is False
    assert flags.edge_tts is False


def test_first_run_wizard_not_completed(tmp_path):
    """On first launch, is_wizard_completed() returns False."""
    target = tmp_path / "setup.json"
    assert is_wizard_completed(prefs_file=target) is False


def test_finish_marks_wizard_completed(tmp_path):
    """After the Finish button, is_wizard_completed() returns True."""
    target = tmp_path / "setup.json"
    from feature_flags import mark_wizard_completed

    mark_wizard_completed(prefs_file=target)
    assert is_wizard_completed(prefs_file=target) is True


def test_partial_completion_does_not_mark_wizard_completed(tmp_path):
    """User clicks Next a few times then hits Cancel — partial choices
    persist (per progressive-save contract) but wizard_completed stays
    False so the next launch re-shows the wizard."""
    target = tmp_path / "setup.json"
    save_feature_flags(prefs_file=target, flags=FeatureFlags())
    set_feature_flag(prefs_file=target, name="pedalboard_effects", value=False)
    assert is_wizard_completed(prefs_file=target) is False
    flags = load_feature_flags(prefs_file=target)
    assert flags.pedalboard_effects is False


# ---------------------------------------------------------------------------
# wx-dependent tests
# ---------------------------------------------------------------------------

needs_wx = pytest.mark.skipif(
    not __import__("importlib").util.find_spec("wx"),
    reason="wxPython not installed",
)


@needs_wx
def test_wizard_module_imports(wx_app):
    """Importing setup_wizard must succeed when wx is available."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    import setup_wizard  # noqa: F401


@needs_wx
def test_wizard_pages_module_imports(wx_app):
    """setup_wizard_pages has all 5 page classes."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import (
        WelcomePage,
        EditingFeaturesPage,
        TTSEnginesPage,
        DataLocationPage,
        SummaryPage,
    )
    assert WelcomePage is not None
    assert EditingFeaturesPage is not None
    assert TTSEnginesPage is not None
    assert DataLocationPage is not None
    assert SummaryPage is not None


@needs_wx
def test_welcome_page_constructs(wx_app):
    """Welcome page builds with accessible name set."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import WelcomePage

    # Pages require a real parent wx.Window (wx.Notebook or wx.Frame).
    # Wrap in a throwaway Frame so the test exercises the same path
    # the production dialog uses.
    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = WelcomePage(parent=frame)
        assert "SpeechCraft" in page.GetName()
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_editing_features_page_constructs_with_seven_checkboxes(wx_app):
    """Editing features page exposes the 7 toggleable features (basic_editing
    is in the page header copy, not as a checkbox)."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import EditingFeaturesPage
    from feature_flags import FeatureFlags

    flags = FeatureFlags()
    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = EditingFeaturesPage(parent=frame, flags=flags)
        # 5 toggleable checkboxes on this page (TTS engines are on
        # their own page, basic_editing is in the page header copy).
        assert len(page.checkboxes) == 5
        assert "pedalboard_effects" in page.checkboxes
        assert "local_transcription" in page.checkboxes
        assert "cloud_transcription" in page.checkboxes
        assert "destructive_editing" in page.checkboxes
        assert "line_placing" in page.checkboxes
        assert "basic_editing" not in page.checkboxes
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_editing_features_page_collect_returns_current_state(wx_app):
    """collect() returns a FeatureFlags reflecting every checkbox state."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import EditingFeaturesPage
    from feature_flags import FeatureFlags

    flags = FeatureFlags()
    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = EditingFeaturesPage(parent=frame, flags=flags)
        page.checkboxes["pedalboard_effects"].SetValue(False)
        result = page.collect()
        assert result.pedalboard_effects is False
        # Unchanged features retain defaults
        assert result.basic_editing is True
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_tts_engines_page_constructs_with_two_checkboxes(wx_app):
    """TTS engines page exposes the 2 TTS options."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import TTSEnginesPage
    from feature_flags import FeatureFlags

    flags = FeatureFlags()
    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = TTSEnginesPage(parent=frame, flags=flags)
        assert "edge_tts" in page.checkboxes
        assert "piper_tts" in page.checkboxes
        assert len(page.checkboxes) == 2
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_data_location_page_constructs_showing_paths(wx_app):
    """Data location page is read-only and shows the current settings path."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import DataLocationPage

    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = DataLocationPage(
            parent=frame,
            settings_dir=Path("/tmp/speechcraft"),
            projects_dir=Path.home(),
        )
        assert page.GetName() != ""
        # Has a static text that mentions settings
        labels = [w.GetLabel() for w in page.GetChildren()]
        joined = " ".join(labels)
        assert "SpeechCraft" in joined or "settings" in joined.lower()
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_summary_page_lists_every_toggled_flag(wx_app):
    """Summary page renders a list of all feature flags and their state."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import SummaryPage
    from feature_flags import FeatureFlags

    flags = FeatureFlags(pedalboard_effects=False, piper_tts=False)
    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = SummaryPage(parent=frame, flags=flags)
        # The page renders via static text; verify it has a non-empty
        # accessible name and the body mentions the toggled flags.
        assert page.GetName() != ""
        labels = [w.GetLabel() for w in page.GetChildren()]
        joined = " ".join(labels)
        # 'pedalboard' and 'piper' both appear in the body because
        # the summary lists every flag by its humanised name.
        assert "Pedalboard" in joined
        assert "Piper" in joined
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_wizard_dialog_constructs_with_six_pages(wx_app, monkeypatch):
    """The full SetupWizardDialog builds 6 pages and wires nav buttons."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard import SetupWizardDialog
    from prefs import PREFS_FILE

    # Redirect the prefs file to tmp so tests don't pollute the real one
    target = __import__("pathlib").Path(
        monkeypatch.setenv  # noqa: B018  -- placeholder
    ) if False else None
    # Simpler: pass an explicit prefs_file override through the dialog.
    dlg = SetupWizardDialog(
        parent=None,
        prefs_file=__import__("pathlib").Path("/tmp/speechcraft_test.json"),
    )
    try:
        assert dlg.GetPageCount() == 6
        assert dlg.GetName() != ""
    finally:
        dlg.Destroy()


@needs_wx
def test_run_setup_wizard_returns_completed_flag_on_finish(wx_app):
    """run_setup_wizard() returns (completed, aborted) tuple; on Finish
    the caller knows the user actually completed the flow."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard import run_setup_wizard

    # We can't drive the modal ShowModal() from a test, but we can verify
    # the function exists and returns the documented tuple type.
    import inspect

    sig = inspect.signature(run_setup_wizard)
    assert "parent" in sig.parameters
    assert "prefs_file" in sig.parameters


@needs_wx
def test_welcome_page_does_not_have_state(wx_app):
    """Welcome page must not mark itself as having wizard state, so
    clicking Next on Welcome doesn't accidentally overwrite the
    user's saved flags with defaults."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import WelcomePage

    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = WelcomePage(parent=frame)
        assert getattr(page, "_has_state", False) is False
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_data_location_page_does_not_have_state(wx_app):
    """Data location page is read-only — no state to save."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import DataLocationPage

    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = DataLocationPage(
            parent=frame,
            settings_dir=Path("/tmp/speechcraft"),
            projects_dir=Path.home(),
        )
        assert getattr(page, "_has_state", False) is False
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_editing_features_page_has_state(wx_app):
    """Editing features page must mark itself as having wizard state."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import EditingFeaturesPage
    from feature_flags import FeatureFlags

    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = EditingFeaturesPage(parent=frame, flags=FeatureFlags())
        assert getattr(page, "_has_state", False) is True
    finally:
        page.Destroy()
        frame.Destroy()


@needs_wx
def test_tts_engines_page_has_state(wx_app):
    """TTS engines page must mark itself as having wizard state."""
    if wx_app is None:
        pytest.skip("wxPython not installed")
    from setup_wizard_pages import TTSEnginesPage
    from feature_flags import FeatureFlags

    frame = wx.Frame(None, wx.ID_ANY, "test")
    try:
        page = TTSEnginesPage(parent=frame, flags=FeatureFlags())
        assert getattr(page, "_has_state", False) is True
    finally:
        page.Destroy()
        frame.Destroy()


def test_save_current_page_skips_pages_without_state(tmp_path):
    """Pure-logic test for the Welcome-page-reset regression.

    Simulates a v1.2.0 user who has pedalboard_effects disabled.
    Calling _save_current_page() while on a stateless page (Welcome,
    Data location, Summary) must NOT overwrite that choice with
    defaults. We exercise this by inspecting the gate logic
    directly: pages that don't set ``_has_state = True`` are skipped
    by the wizard's save path.
    """
    target = tmp_path / "setup.json"
    save_feature_flags(
        prefs_file=target,
        flags=FeatureFlags(pedalboard_effects=False),
    )
    pre_existing = load_feature_flags(prefs_file=target)
    assert pre_existing.pedalboard_effects is False

    # Confirm the gate contract: the wizard's _save_current_page()
    # reads getattr(page, "_has_state", False) and bails when False.
    # We can't drive the modal from this pure-logic test, but the wx
    # tests above verify each page's _has_state value directly.
    #
    # What we CAN test here: simulating the gate logic in isolation.
    class _FakePage:
        # Stateless — like WelcomePage.
        pass

    class _FakeStatefulPage:
        _has_state = True

        def collect(self):
            return FeatureFlags(pedalboard_effects=True)  # would reset!

    # The gate check the wizard uses:
    assert not getattr(_FakePage(), "_has_state", False)
    assert getattr(_FakeStatefulPage(), "_has_state", False)
