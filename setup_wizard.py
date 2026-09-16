"""SpeechCraft Studio modular setup wizard.

Five-page wizard (Welcome → Editing features → TTS engines → Data
location → Summary). Replaces the v1.2.0 Core/Full onboarding
dialog with a feature-by-feature choice.

Lifecycle:

- First launch (``is_wizard_completed() == False``) → wizard shows
  automatically
- Help → Personalise SpeechCraft… menu item reopens it any time
- Forward nav = "make choices, hit Next"
- Choices are saved to setup.json after every Next click (progressive
  save). wizard_completed flips to True only when the user clicks
  Finish on the Summary page
- Cancel/Escape during first-run keeps partial choices saved but
  leaves wizard_completed=False, so the wizard re-shows on next
  launch — protects the user from losing the flow if they hit X by
  accident

Architecture (mirrors Quill's split, see quill/ui/setup_wizard.py):

- :mod:`setup_wizard_pages` — each page is a :class:`_WizardPage`
  subclass with a ``collect()`` method that returns a
  :class:`FeatureFlags`
- :class:`SetupWizardDialog` — the modal wx.Dialog that hosts the
  six pages, wires Next/Back/Finish, and writes setup.json
- :func:`run_setup_wizard` — module-level entry point, opens the
  dialog and returns ``(completed, aborted)``

What v1.3.0-wizard-shell does NOT do (deferred to later PRs):

- Trigger feature downloads when the user enables something
  uninstalled → v1.3.0-feature-manager
- Hide menu items / gate code paths based on flag values →
  v1.3.0-feature-toggling
- Allow editing the data location paths → not planned yet

See docs/plans/2026-09-14-v1.3.0-roadmap.md for the broader story.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import wx

from feature_flags import (
    FeatureFlags,
    is_wizard_completed,
    load_feature_flags,
    mark_wizard_completed,
    save_feature_flags,
    set_feature_flag,
)
from prefs import PREFS_FILE
from setup_wizard_pages import (
    DataLocationPage,
    DownloadPage,
    EditingFeaturesPage,
    SummaryPage,
    TTSEnginesPage,
    WelcomePage,
)


_WIZARD_TITLE = "Personalise SpeechCraft"


class SetupWizardDialog(wx.Dialog):
    """The 6-page wizard as a modal wx.Dialog.

    Uses wx.Notebook under the hood — pages are tabs the user
    navigates with the Next/Back buttons at the bottom. The
    ``prefs_file`` parameter redirects reads/writes to a temp file
    so tests don't pollute the real setup.json.
    """

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        prefs_file: Path | None = None,
    ) -> None:
        super().__init__(
            parent,
            wx.ID_ANY,
            _WIZARD_TITLE,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(640, 540),
        )
        self.SetName("Personalise SpeechCraft setup wizard")
        self._prefs_file = prefs_file if prefs_file is not None else PREFS_FILE

        # Load the user's current flags so the wizard pre-selects them.
        self._flags = load_feature_flags(prefs_file=self._prefs_file)

        self._build_ui()
        self.CentreOnScreen()

        # Escape cancels; Enter activates the default button (Next)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char)

        self._aborted = False

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(248, 246, 240))

        # NVDA announcement channel: screen readers watch the status
        # bar of the focused window and read text changes without
        # focus being stolen. Page changes set the status text so a
        # keyboard/NVDA user always hears "Page N of M: <page>" when
        # navigating Next/Back. Parented to the panel and placed by
        # the panel sizer so it actually renders (wx.Dialog has no
        # CreateStatusBar — that's a Frame API).
        self._status = wx.StatusBar(panel)
        self._status.SetName("Wizard status")

        outer = wx.BoxSizer(wx.VERTICAL)

        # Page indicator: "Page 2 of 5 — Editing features"
        self._indicator = wx.StaticText(panel, label="")
        self._indicator.SetName("Page indicator")
        self._indicator.SetForegroundColour(wx.Colour(80, 80, 80))
        outer.Add(self._indicator, 0, wx.ALL, 12)

        # The 5 pages, built once with the loaded flags
        self._notebook = wx.Notebook(
            panel,
            style=wx.NB_TOP | wx.NB_MULTILINE,  # NB_MULTILINE: tabs wrap if too narrow
        )
        self._notebook.SetName("Wizard pages")

        self._welcome = WelcomePage(self._notebook)
        self._editing = EditingFeaturesPage(self._notebook, flags=self._flags)
        self._tts = TTSEnginesPage(self._notebook, flags=self._flags)
        self._download = DownloadPage(
            self._notebook,
            flags_provider=self._current_flags,
            state_file=self._prefs_file,
        )
        self._data = DataLocationPage(
            self._notebook,
            settings_dir=self._prefs_file.parent,
            projects_dir=Path.home() / "Documents" / "SpeechCraft",
        )
        self._summary = SummaryPage(self._notebook, flags=self._flags)

        for page, label in [
            (self._welcome, "Welcome"),
            (self._editing, "Editing features"),
            (self._tts, "TTS engines"),
            (self._download, "Download ready"),
            (self._data, "Data location"),
            (self._summary, "Summary"),
        ]:
            self._notebook.AddPage(page, label)

        # Refresh indicator whenever the user changes pages (back/forward)
        self._notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_page_changed)
        self._refresh_indicator()

        outer.Add(self._notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # Nav buttons: Back | <spacer> | Next | Finish | Cancel
        nav = wx.BoxSizer(wx.HORIZONTAL)
        self._back = wx.Button(panel, wx.ID_BACKWARD, "Back")
        self._back.SetName("Back, previous page")
        self._back.Bind(wx.EVT_BUTTON, self._on_back)
        nav.Add(self._back, 0, wx.RIGHT, 8)

        nav.AddStretchSpacer(1)

        self._next = wx.Button(panel, wx.ID_FORWARD, "Next")
        self._next.SetName("Next, next page")
        self._next.SetDefault()
        self._next.Bind(wx.EVT_BUTTON, self._on_next)
        nav.Add(self._next, 0, wx.RIGHT, 8)

        self._finish = wx.Button(panel, wx.ID_OK, "Finish")
        self._finish.SetName("Finish, apply settings and close wizard")
        self._finish.Bind(wx.EVT_BUTTON, self._on_finish)
        # Finish is hidden until the user reaches the Summary page
        self._finish.Hide()
        nav.Add(self._finish, 0, wx.RIGHT, 8)

        self._cancel = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        self._cancel.SetName("Cancel, close wizard without applying")
        self._cancel.Bind(wx.EVT_BUTTON, self._on_cancel)
        nav.Add(self._cancel, 0)

        outer.Add(nav, 0, wx.EXPAND | wx.ALL, 12)

        # Status bar renders last (bottom edge) and carries the NVDA
        # page-announcement text.
        outer.Add(self._status, 0, wx.EXPAND)

        panel.SetSizer(outer)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def GetPageCount(self) -> int:
        """Test hook: how many pages does this wizard have?"""
        return self._notebook.GetPageCount()

    @property
    def aborted_first_run(self) -> bool:
        """True if the user cancelled on the first run (no completed
        choices). Distinguishes "Cancel because I'm done configuring"
        from "Cancel because I never engaged"."""
        return self._aborted

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_char(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_cancel(event)
        else:
            event.Skip()

    def _on_page_changed(self, event: wx.Event) -> None:
        self._refresh_indicator()
        self._refresh_nav_buttons()
        # When navigating back to the Summary, refresh it with the
        # current flags so it shows the up-to-date state.
        if self._notebook.GetCurrentPage() is self._summary:
            self._summary.update_flags(self._current_flags())
        # The Download page's list is live-rebuilt from the current
        # checkbox state, so it always reflects what the user has
        # chosen on the Editing / TTS pages.
        if self._notebook.GetCurrentPage() is self._download:
            self._download.refresh()
        # NVDA: land focus on the new page's heading so the screen
        # reader announces the page the user just arrived at.
        self._focus_page_content()
        event.Skip()

    def _on_back(self, event: wx.Event) -> None:
        # Save whatever the current page has set so far (progressive
        # save), then move back. This means the user can go Back,
        # change a checkbox, hit Back again, and the Summary will
        # already show the updated state.
        self._save_current_page()
        idx = self._notebook.GetSelection()
        if idx > 0:
            self._notebook.SetSelection(idx - 1)

    def _on_next(self, event: wx.Event) -> None:
        # Save current page's choices before moving on
        self._save_current_page()
        idx = self._notebook.GetSelection()
        if idx < self._notebook.GetPageCount() - 1:
            self._notebook.SetSelection(idx + 1)

    def _on_finish(self, event: wx.Event) -> None:
        # Save the Summary page's state (no flags on it, but defensive)
        self._save_current_page()
        # Mark the wizard as completed so next-launch won't re-show it
        mark_wizard_completed(prefs_file=self._prefs_file)
        # If on the Summary page and the user clicked Finish, make
        # sure they don't get the Cancel-announcement side effect.
        self._aborted = False
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event: wx.Event) -> None:
        # Save any partial choices the user made (so they don't lose
        # work if they were navigating page-by-page), but DON'T mark
        # wizard_completed=True. Next launch will re-show the wizard.
        self._save_current_page()
        self._aborted = True
        self.EndModal(wx.ID_CANCEL)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_page(self) -> Any:
        return self._notebook.GetCurrentPage()

    def _current_flags(self) -> FeatureFlags:
        """Return a FeatureFlags reflecting the live state of all
        pages that have collect() methods. Used to refresh the
        Summary page when navigating back to it and to feed the
        Download page's live list.

        Each page's collect() returns a FeatureFlags with only its
        own toggles set (others at default), so merge them against
        the dialog's loaded baseline: a page's own fields win, every
        other field keeps the value it had when the wizard opened.
        """
        baseline = self._flags
        editing = self._editing.collect()
        tts = self._tts.collect()
        return FeatureFlags(
            basic_editing=baseline.basic_editing,
            pedalboard_effects=editing.pedalboard_effects,
            local_transcription=editing.local_transcription,
            cloud_transcription=editing.cloud_transcription,
            destructive_editing=editing.destructive_editing,
            line_placing=editing.line_placing,
            edge_tts=tts.edge_tts,
            piper_tts=tts.piper_tts,
        )

    def _save_current_page(self) -> None:
        """Persist the merged live flag state to setup.json.

        Progressive save: each Next / Back click persists whatever the
        user has toggled so far. Saving the *merged* state (via
        :meth:`_current_flags`) rather than the single page's
        collect() result avoids clobbering the other page's choices —
        a page's collect() only carries its own toggles, so writing
        it directly would reset the other page's fields to defaults.
        """
        page = self._current_page()
        if not getattr(page, "_has_state", False):
            return
        self._flags = self._current_flags()
        save_feature_flags(prefs_file=self._prefs_file, flags=self._flags)

    def _refresh_indicator(self) -> None:
        idx = self._notebook.GetSelection()
        total = self._notebook.GetPageCount()
        page_name = self._notebook.GetPageText(idx)
        self._indicator.SetLabel(f"Page {idx + 1} of {total} — {page_name}")
        self._indicator.SetName(f"Page {idx + 1} of {total}: {page_name}")
        # Screen-reader announcement: NVDA reads status-bar changes on
        # the focused window without stealing focus from the tab strip,
        # so the user always hears which page they've landed on.
        self._status.SetStatusText(f"Page {idx + 1} of {total}: {page_name}")

    def _focus_page_content(self):
        """Move focus to the first meaningful control on the page.

        NVDA announces the focused control on focus-change, so landing
        focus on the page heading makes the screen reader read the
        page title when the user navigates Next/Back. Returns the
        focused widget (or None) so callers/tests can verify the
        target.
        """
        page = self._current_page()
        if page is None:
            return None
        heading = getattr(page, "_heading", None)
        if heading is not None and heading.IsShown():
            heading.SetFocus()
            return heading
        # No dedicated heading (e.g. Download page list panel) —
        # focus the first child so NVDA reads something meaningful.
        children = page.GetChildren()
        if children:
            children[0].SetFocus()
            return children[0]
        return None

    def _refresh_nav_buttons(self) -> None:
        idx = self._notebook.GetSelection()
        total = self._notebook.GetPageCount()
        # Back button enabled iff not on first page
        self._back.Enable(idx > 0)
        # Next button visible on every page except the last
        self._next.Show(idx < total - 1)
        # Finish button visible on the Summary page only
        self._finish.Show(idx == total - 1)
        # Re-layout the nav sizer so the buttons move
        self._notebook.GetParent().Layout()


def run_setup_wizard(
    parent: wx.Window | None = None,
    *,
    prefs_file: Path | None = None,
) -> tuple[bool, bool]:
    """Open the setup wizard as a modal dialog.

    Returns ``(completed, aborted)``:

    - ``completed``: True if the user clicked Finish (the changes
      have been applied and wizard_completed=True has been written)
    - ``aborted``: True if the user clicked Cancel during the first
      run (used by the caller to decide whether to re-prompt next
      launch)

    The caller is responsible for deciding what to do with the
    result: e.g. ``audio_editor.main()`` announces "Setup completed"
    and reloads feature-dependent menus.

    Pass an explicit ``prefs_file`` to redirect reads/writes
    (tests use this; production code passes nothing and the wizard
    reads ``prefs.PREFS_FILE``).
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    dlg = SetupWizardDialog(parent, prefs_file=target)
    try:
        result = dlg.ShowModal()
        completed = result == wx.ID_OK
        aborted = dlg.aborted_first_run
    finally:
        dlg.Destroy()
    return completed, aborted


def should_show_wizard_on_launch(*, prefs_file: Path | None = None) -> bool:
    """Return True iff the wizard should auto-show on launch.

    First run (``is_wizard_completed() is False``): show it.
    Subsequent runs: don't auto-show, but the user can still open
    it from Help → Personalise SpeechCraft.

    This is the function ``run_speechcraft.py`` calls before
    showing the main frame.
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    return not is_wizard_completed(prefs_file=target)


__all__ = (
    "SetupWizardDialog",
    "run_setup_wizard",
    "should_show_wizard_on_launch",
)
