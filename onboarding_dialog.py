"""Onboarding dialog shown on SpeechCraft's first launch.

Goal: keep first-launch UX calm instead of "wait 15 seconds, splash
disappears, freeze for 2 minutes." Instead:

1. Welcome the user
2. Tell them what's about to happen (defender scan + bundle extract)
3. Offer a "Lite" install for users who only need TTS + recording
4. Save their preference so it doesn't show again

Lifecycle:
- First run of either EXE -> Onboarding().show() shows the dialog
- User picks a bundle type ("Use Core" / "Use Full") and clicks OK
- We write the choice to ~/.speechcraft/setup.json
- Run the chosen bundle
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import wx

# Where we store user preferences. %APPDATA% on Windows, ~/.speechcraft
# on Linux/macOS dev runs.
if sys.platform == "win32":
    PREFS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "SpeechCraft"
else:
    PREFS_DIR = Path.home() / ".speechcraft"

PREFS_FILE = PREFS_DIR / "setup.json"


def _load_prefs(prefs_file: Path | None = None) -> dict[str, Any]:
    """Read existing prefs (if any). Returns {} on any parse error.

    Prefs_path override exists so tests can redirect to a temp file.
    Production code uses the module-level PREFS_FILE.
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_prefs(prefs: dict[str, Any], prefs_file: Path | None = None) -> None:
    """Persist prefs to disk. Best-effort; no error dialog."""
    target = prefs_file if prefs_file is not None else PREFS_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except OSError:
        # Read-only filesystem, no permissions. Not fatal — we just
        # re-prompt next launch.
        pass


def get_preferred_bundle() -> str | None:
    """Return the bundle the user previously picked, or None on first run.

    Use this from run_speechcraft.py: if onboarding was completed,
    skip showing the dialog.
    """
    prefs = _load_prefs()
    return prefs.get("preferred_bundle")


class OnboardingDialog(wx.Dialog):
    """First-launch dialog. Lets the user choose Core or Full bundle.

    The dialog is intentionally text-heavy and accessible — no
    images, no spinning animations. Each radio button has a
    SetName() so NVDA announces it correctly.
    """

    def __init__(self, parent: wx.Window | None) -> None:
        super().__init__(
            parent,
            wx.ID_ANY,
            "Welcome to SpeechCraft Studio",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(640, 480),
        )
        self.SetName("SpeechCraft Studio first-run setup")
        self._build_ui()
        self.CentreOnScreen()
        self._result = "Core"  # Safe default: lite install
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char)

    def _on_char(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_OK)
        else:
            event.Skip()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(248, 246, 240))

        title = wx.StaticText(
            panel,
            label="Welcome to SpeechCraft Studio",
        )
        title.SetFont(
            wx.Font(
                18,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )
        title.SetName("Welcome heading")

        intro = wx.StaticText(
            panel,
            label=(
                "Before we start, pick the edition that matches your needs. "
                "SpeechCraft Studio comes in two variants: a small Core build "
                "for everyday audio work, and a Full build with local AI "
                "transcription and advanced effects."
            ),
        )
        intro.Wrap(580)
        intro.SetName("Pick the edition that matches your needs")

        # Bundle selection as radio buttons. The accessibility name on
        # each is the full description a screen reader should announce.
        self._core = wx.RadioButton(
            panel,
            label="Core — small download, fast launch, recommended",
        )
        self._core.SetName(
            "Core edition — small download, fast launch, recommended. "
            "Includes recording, transcription via your cloud account, "
            "TTS, basic effects, breath smoothing, room tone match."
        )
        self._core.SetValue(True)  # Safe default
        self._core.Bind(wx.EVT_RADIOBUTTON, self._on_select)

        self._full = wx.RadioButton(
            panel,
            label="Full — adds local AI transcription and advanced effects",
        )
        self._full.SetName(
            "Full edition — adds local AI transcription (Whisper) and "
            "advanced effects (pedalboard). Larger download, slower "
            "first launch."
        )
        self._full.Bind(wx.EVT_RADIOBUTTON, self._on_select)

        details = wx.StaticText(
            panel,
            label=(
                "If you're not sure, choose Core. You can always switch "
                "to Full later from the menu bar once you're set up. "
                "You can also skip this question by pressing Enter."
            ),
        )
        details.Wrap(580)
        details.SetName(
            "If you're not sure, choose Core. You can switch later "
            "from the menu bar. Press Enter to continue."
        )

        ok = wx.Button(panel, wx.ID_OK, "Continue")
        ok.SetDefault()
        ok.Bind(wx.EVT_BUTTON, self._on_ok)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(title, 0, wx.ALL, 16)
        sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        sizer.AddStretchSpacer(1)
        sizer.Add(self._core, 0, wx.LEFT | wx.RIGHT, 24)
        sizer.Add(self._full, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        sizer.Add(details, 0, wx.ALL, 16)
        sizer.Add(ok, 0, wx.ALIGN_RIGHT | wx.ALL, 16)
        panel.SetSizer(sizer)
        sizer.Fit(self)

    def _on_select(self, event: wx.CommandEvent) -> None:
        if event.GetEventObject() is self._core:
            self._result = "Core"
        elif event.GetEventObject() is self._full:
            self._result = "Full"
        event.Skip()

    def _on_ok(self, event: wx.Event) -> None:
        prefs = _load_prefs()
        prefs["preferred_bundle"] = self._result
        _save_prefs(prefs)
        self.EndModal(wx.ID_OK)

    def get_choice(self) -> str:
        """Return 'Core' or 'Full' based on what the user picked."""
        return self._result


def run_onboarding() -> str | None:
    """Open the onboarding dialog and persist the choice.

    Returns the bundle type ('Core' or 'Full') the user picked, or None
    if they cancelled (in which case we keep showing the dialog next launch).
    """
    if not (sys.platform == "win32" or os.environ.get("DISPLAY")):
        # Headless. No dialog possible.
        return None

    from onboarding_dialog import (
        _load_prefs,
        OnboardingDialog,
    )

    prefs = _load_prefs()
    if prefs.get("preferred_bundle"):
        return prefs["preferred_bundle"]

    app = wx.App()
    try:
        dlg = OnboardingDialog(parent=None)
        result = dlg.ShowModal()
    finally:
        app.Destroy()

    if result == wx.ID_OK:
        return dlg.get_choice()
    return None
