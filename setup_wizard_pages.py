"""SpeechCraft Studio setup wizard pages.

Five pages walk the user through personalising SpeechCraft:

1. Welcome — plain-text intro, screen-reader friendly
2. Editing features — checkboxes for the 7 toggleable capabilities
   (basic_editing is the foundation, shown as info text, not a checkbox)
3. TTS engines — checkboxes for Edge TTS and Piper TTS
4. Data location — read-only display of where settings / projects live
5. Summary — list of every flag and its current state, Finish button

Each page subclasses :class:`_WizardPage` which provides the standard
padding, accessible naming, and a ``collect()`` method that pages
override to write their current state into a :class:`FeatureFlags`.

Pure UX scaffolding only: no feature toggling, no downloads, no
actual capability gating. Those ship in v1.3.0-feature-manager.

See docs/plans/2026-09-14-v1.3.0-roadmap.md for the broader
v1.3.0 story.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import wx

from feature_flags import (
    FEATURE_DESCRIPTIONS,
    FEATURE_NAMES,
    FeatureFlags,
)


#: Page names, in wizard order. Exposed so :mod:`setup_wizard` can
#: enumerate them without re-typing the list.
PAGE_NAMES = (
    "welcome",
    "editing_features",
    "tts_engines",
    "data_location",
    "summary",
)


# Features the user can actually toggle on the Editing features page.
# basic_editing is the foundation (always on) and is described in the
# page header copy rather than shown as a checkbox.
TOGGLEABLE_FEATURES = tuple(n for n in FEATURE_NAMES if n != "basic_editing")

# Subset of TOGGLEABLE_FEATURES shown on the Editing features page
# (everything except TTS engines, which get their own page).
EDITING_PAGE_FEATURES = (
    "pedalboard_effects",
    "local_transcription",
    "cloud_transcription",
    "destructive_editing",
    "line_placing",
)

TTS_PAGE_FEATURES = (
    "edge_tts",
    "piper_tts",
)


class _WizardPage(wx.Panel):
    """Base class for wizard pages.

    Subclasses should call ``super().__init__`` with a ``name`` (the
    page title), build their UI in ``_build_ui``, and override
    ``collect()`` to write current state into a returned
    :class:`FeatureFlags`.

    The base class:

    - Sets an accessible name on the panel so NVDA announces the
      page title when focus arrives
    - Provides a consistent vertical padding
    - Provides a ``header_text`` static text the subclass populates
    """

    def __init__(self, parent: wx.Window, *, name: str) -> None:
        super().__init__(parent, wx.ID_ANY)
        self._name = name
        self.SetName(name)
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._sizer)
        self._build_ui()

    @property
    def name(self) -> str:
        return self._name

    def _build_ui(self) -> None:
        """Override in subclasses. Default just adds a placeholder."""
        placeholder = wx.StaticText(self, label=self._name)
        placeholder.SetName(self._name)
        self._sizer.Add(placeholder, 0, wx.ALL, 16)

    def collect(self) -> FeatureFlags:
        """Return a :class:`FeatureFlags` reflecting the page's current state.

        Subclasses MUST override. The base implementation returns
        a default-flag set so the wizard still functions even if a
        subclass forgets to override.
        """
        return FeatureFlags()


class WelcomePage(_WizardPage):
    """Plain-text welcome. No choices, just sets the tone."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, name="Welcome to SpeechCraft Studio")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Welcome to SpeechCraft Studio")
        title.SetFont(
            wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Welcome to SpeechCraft Studio, heading")
        self._sizer.Add(title, 0, wx.ALL, 16)

        intro = wx.StaticText(
            self,
            label=(
                "SpeechCraft Studio is a modular audio editor. The "
                "foundation is basic audio editing and effects. Beyond "
                "that, you can choose which capabilities you want to "
                "install: local or cloud transcription, advanced "
                "effects, destructive editing, automatic line placement, "
                "and text-to-speech engines.\n\n"
                "You can change any of these choices later from the "
                "Help menu: Personalise SpeechCraft."
            ),
        )
        intro.SetName(
            "SpeechCraft Studio is a modular audio editor. The "
            "foundation is basic audio editing and effects. Beyond "
            "that, you can choose which capabilities you want to "
            "install. You can change any of these choices later from "
            "the Help menu."
        )
        intro.Wrap(560)
        self._sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)


class EditingFeaturesPage(_WizardPage):
    """Checkbox grid for the 5 Editing-feature flags.

    basic_editing is the foundation (always on) and is described in
    the page intro, NOT as a checkbox. The user toggles the 5
    optional capabilities below it.
    """

    def __init__(self, parent: wx.Window, *, flags: FeatureFlags) -> None:
        self._flags = flags
        self.checkboxes: dict[str, wx.CheckBox] = {}
        self._has_state = True  # see _save_current_page in setup_wizard.py
        super().__init__(parent, name="Editing features")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Editing features")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Editing features, heading")
        self._sizer.Add(title, 0, wx.ALL, 16)

        foundation = wx.StaticText(
            self,
            label=(
                "Basic audio editing and effects (cut, copy, paste, "
                "EQ, compressor, breath smoothing) is the core of "
                "SpeechCraft and is always on. Below, choose which "
                "additional capabilities you want:"
            ),
        )
        foundation.SetName(
            "Basic audio editing and effects is the core of SpeechCraft "
            "and is always on."
        )
        foundation.Wrap(560)
        self._sizer.Add(foundation, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        # The 5 optional features as a vertical stack of checkboxes,
        # each with its own description as a sub-label.
        for name in EDITING_PAGE_FEATURES:
            current = getattr(self._flags, name)
            cb = wx.CheckBox(self, label=_humanize(name))
            cb.SetValue(current)
            cb.SetName(f"{_humanize(name)}. {FEATURE_DESCRIPTIONS[name]}")
            self.checkboxes[name] = cb
            self._sizer.Add(cb, 0, wx.LEFT | wx.RIGHT, 24)

            desc = wx.StaticText(self, label=FEATURE_DESCRIPTIONS[name])
            desc.SetName(f"{_humanize(name)} description")
            desc.SetForegroundColour(wx.Colour(80, 80, 80))
            desc.Wrap(520)
            self._sizer.Add(desc, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)

    def collect(self) -> FeatureFlags:
        """Return flags with this page's checkbox state applied."""
        kwargs: dict[str, Any] = {}
        for name in EDITING_PAGE_FEATURES:
            kwargs[name] = self.checkboxes[name].GetValue()
        return FeatureFlags(**kwargs)


class TTSEnginesPage(_WizardPage):
    """Two-checkboxes page: Edge TTS and Piper offline TTS."""

    def __init__(self, parent: wx.Window, *, flags: FeatureFlags) -> None:
        self._flags = flags
        self.checkboxes: dict[str, wx.CheckBox] = {}
        self._has_state = True  # see _save_current_page in setup_wizard.py
        super().__init__(parent, name="Text-to-speech engines")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Text-to-speech engines")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Text-to-speech engines, heading")
        self._sizer.Add(title, 0, wx.ALL, 16)

        intro = wx.StaticText(
            self,
            label=(
                "SpeechCraft can speak text using either of these "
                "engines. You can enable both — SpeechCraft will pick "
                "the best one for each request."
            ),
        )
        intro.SetName(
            "Choose which text-to-speech engines you want to enable."
        )
        intro.Wrap(560)
        self._sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        for name in TTS_PAGE_FEATURES:
            current = getattr(self._flags, name)
            cb = wx.CheckBox(self, label=_humanize(name))
            cb.SetValue(current)
            cb.SetName(f"{_humanize(name)}. {FEATURE_DESCRIPTIONS[name]}")
            self.checkboxes[name] = cb
            self._sizer.Add(cb, 0, wx.LEFT | wx.RIGHT, 24)

            desc = wx.StaticText(self, label=FEATURE_DESCRIPTIONS[name])
            desc.SetName(f"{_humanize(name)} description")
            desc.SetForegroundColour(wx.Colour(80, 80, 80))
            desc.Wrap(520)
            self._sizer.Add(desc, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)

    def collect(self) -> FeatureFlags:
        kwargs: dict[str, Any] = {}
        for name in TTS_PAGE_FEATURES:
            kwargs[name] = self.checkboxes[name].GetValue()
        return FeatureFlags(**kwargs)


class DataLocationPage(_WizardPage):
    """Read-only display of where SpeechCraft stores its data.

    Per v1.3.0-wizard-shell scope: no editing. Future PRs may add a
    Browse button. For now the page just tells the user where things
    live, so they can find their files.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        settings_dir: Path,
        projects_dir: Path,
    ) -> None:
        self._settings_dir = settings_dir
        self._projects_dir = projects_dir
        super().__init__(parent, name="Where your files live")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Where your files live")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Where your files live, heading")
        self._sizer.Add(title, 0, wx.ALL, 16)

        intro = wx.StaticText(
            self,
            label=(
                "SpeechCraft keeps its settings and your projects in "
                "standard locations so they're easy to back up."
            ),
        )
        intro.SetName("SpeechCraft keeps its settings and projects in standard locations.")
        intro.Wrap(560)
        self._sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        # Settings path row
        settings_label = wx.StaticText(self, label="Settings and preferences:")
        settings_label.SetName("Settings location label")
        self._sizer.Add(settings_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        settings_path = wx.StaticText(self, label=str(self._settings_dir))
        settings_path.SetName(f"Settings location: {self._settings_dir}")
        settings_path.SetFont(
            wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        )
        self._sizer.Add(settings_path, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        # Projects path row
        projects_label = wx.StaticText(self, label="Projects (audio files):")
        projects_label.SetName("Projects location label")
        self._sizer.Add(projects_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        projects_path = wx.StaticText(self, label=str(self._projects_dir))
        projects_path.SetName(f"Projects location: {self._projects_dir}")
        projects_path.SetFont(
            wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        )
        self._sizer.Add(projects_path, 0, wx.LEFT | wx.RIGHT, 16)


class SummaryPage(_WizardPage):
    """Summary of every flag and its current state, with Finish button.

    The Finish button is wired by the parent SetupWizardDialog, not
    here. This page just renders the summary text and exposes the
    flags for the dialog to read at Finish time.
    """

    def __init__(self, parent: wx.Window, *, flags: FeatureFlags) -> None:
        self._flags = flags
        super().__init__(parent, name="Summary")
        self._refresh_summary()

    def update_flags(self, flags: FeatureFlags) -> None:
        """Refresh the summary text with new flags (called as pages
        are navigated backwards to)."""
        self._flags = flags
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        # Replace the summary body if it already exists.
        if hasattr(self, "_summary_text"):
            self._summary_text.SetLabel(self._render_text())
            self._summary_text.SetName(self._accessible_summary())
            self._summary_text.Wrap(560)
            return
        # Otherwise nothing yet — body is built in _build_ui.

    def _render_text(self) -> str:
        lines = ["Here's what you've chosen:"]
        for name in FEATURE_NAMES:
            on = getattr(self._flags, name)
            mark = "ON " if on else "OFF"
            lines.append(f"  [{mark}]  {_humanize(name)}")
        lines.append("")
        lines.append(
            "Click Finish to apply these settings. You can change "
            "them later from Help → Personalise SpeechCraft."
        )
        return "\n".join(lines)

    def _accessible_summary(self) -> str:
        parts = ["Summary of your choices:"]
        for name in FEATURE_NAMES:
            on = getattr(self._flags, name)
            status = "enabled" if on else "disabled"
            parts.append(f"{_humanize(name)} is {status}.")
        return " ".join(parts)

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Summary")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Summary, heading")
        self._sizer.Add(title, 0, wx.ALL, 16)

        body = wx.StaticText(self, label=self._render_text())
        body.SetName(self._accessible_summary())
        body.Wrap(560)
        self._summary_text = body
        self._sizer.Add(body, 0, wx.LEFT | wx.RIGHT, 16)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _humanize(name: str) -> str:
    """basic_editing -> Basic editing, line_placing -> Line placing."""
    parts = name.split("_")
    return " ".join(parts).capitalize()


__all__ = (
    "EDITING_PAGE_FEATURES",
    "PAGE_NAMES",
    "TTS_PAGE_FEATURES",
    "TOGGLEABLE_FEATURES",
    "DataLocationPage",
    "EditingFeaturesPage",
    "SummaryPage",
    "TTSEnginesPage",
    "WelcomePage",
)
