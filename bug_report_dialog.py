"""In-app bug-report flow.

Pattern adapted from QUILL's ``quill.ui.crash_report_dialog`` and
``quill.core.diagnostics.build_support_issue_url``: collect a small
set of declarative fields, attach the tail of the local error log
when present, and either open the GitHub issues page with the URL
pre-filled or copy that URL to the clipboard so the user is never
stranded.

Why pre-fill the URL instead of POSTing to the GitHub Issues API?
Two reasons:

1. No GitHub token is required. This is a single-maintainer project
   and we are not bundling an issues-only PAT the way QUILL does.
2. The user sees exactly what will be filed before anything leaves
   their machine. They can edit, cancel, or paste the URL into an
   email instead.

The dialog is parented to the real ``wx.Frame`` (``SpeechCraftFrame``)
so screen readers announce the modal context correctly.

NVDA notes:

- Every control has an explicit ``SetName`` so NVDA announces the
  role and the field name together (e.g. "Description, edit,
  multi-line"). Without that, NVDA would announce "edit" with no
  context.
- Initial focus lands on the first input field (Title), not on the
  default button. This matches the design intent that "default
  button cancels, primary input gets focus".
- The default button is **Cancel** so a user who opens the dialog by
  accident does not accidentally open a browser window.
- Escape is wired to Cancel via ``wx.ID_CANCEL``.
"""

from __future__ import annotations

import platform
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

import wx

from crash_submit import read_log_tail

GITHUB_REPO = "trasles16-ux/speechcraft-audio"
GITHUB_NEW_ISSUE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
ISSUE_TEMPLATE_DEFAULT = "bug.yml"  # maps to .github/ISSUE_TEMPLATE/bug.yml


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

Act = Literal["send", "copy", "cancel"]


@dataclass(frozen=True)
class BugReportResult:
    """The dialog's outcome plus the user's typed fields.

    ``act`` is one of:

    - ``"send"`` — user clicked **Open in browser**. The bug-report
      URL is opened in the user's default browser.
    - ``"copy"`` — user clicked **Copy URL**. The URL is on the
      clipboard but the browser was not opened.
    - ``"cancel"`` — user clicked Cancel or pressed Escape. Nothing
      happens.
    """

    act: Act
    title: str = ""
    description: str = ""
    expected: str = ""
    steps: str = ""


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def build_issue_url(
    *,
    title: str,
    description: str,
    expected: str,
    steps: str,
    app_version: str,
    platform_label: str,
    python_version: str,
    screen_reader: str,
    log_tail: str | None,
) -> str:
    """Return the GitHub issues/new URL with everything pre-filled.

    The body is assembled as a Markdown-friendly string with the
    same field shape as the bug issue template, so the user lands on
    the issues page and sees a near-complete report ready to submit.
    """
    body_parts: list[str] = []
    if description:
        body_parts.append("## What happened")
        body_parts.append("")
        body_parts.append(description)
        body_parts.append("")
    if expected:
        body_parts.append("## What I expected")
        body_parts.append("")
        body_parts.append(expected)
        body_parts.append("")
    if steps:
        body_parts.append("## Steps to reproduce")
        body_parts.append("")
        body_parts.append(steps)
        body_parts.append("")
    body_parts.append("## Environment")
    body_parts.append("")
    body_parts.append(f"- SpeechCraft version: {app_version}")
    body_parts.append(f"- Operating system: {platform_label}")
    body_parts.append(f"- Python: {python_version}")
    if screen_reader:
        body_parts.append(f"- Screen reader: {screen_reader}")
    if log_tail:
        body_parts.append("")
        body_parts.append("## Recent log output (auto-attached)")
        body_parts.append("")
        body_parts.append("```")
        body_parts.append(log_tail)
        body_parts.append("```")

    params = {
        "template": ISSUE_TEMPLATE_DEFAULT,
        "title": title or "Bug report",
        "body": "\n".join(body_parts).rstrip() + "\n",
    }
    return GITHUB_NEW_ISSUE_URL + "?" + urlencode(params)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


class BugReportDialog:
    """Modal bug-report dialog.

    The dialog never sends anything on its own. It collects the
    user's fields, then either hands the pre-filled URL to the
    default browser or copies it to the clipboard. The user is
    always the one who decides whether a report leaves the machine.
    """

    _ID_OPEN: int = wx.ID_HIGHEST + 11
    _ID_COPY: int = wx.ID_HIGHEST + 12

    def __init__(
        self,
        parent: wx.Window,
        *,
        app_version: str = "3.0.2",
        screen_reader: str = "",
        log_tail: str | None = None,
    ) -> None:
        self._parent = parent
        self._app_version = app_version
        self._screen_reader = screen_reader or self._detect_screen_reader()
        self._log_tail = log_tail
        self._result = BugReportResult(act="cancel")

        self.dialog: wx.Dialog = wx.Dialog(
            parent,
            title="Report a Bug",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.dialog.SetName("bug_report_dialog")
        self.dialog.SetSize((720, 640))
        self.dialog.SetMinSize((560, 480))

        root = wx.BoxSizer(wx.VERTICAL)

        # --- Header / explanation -----------------------------------------
        intro = wx.StaticText(
            self.dialog,
            label=(
                "Describe the bug below. When you click 'Open in browser', "
                "the GitHub issues page will open in your default browser "
                "with your answers pre-filled. You review and submit it "
                "from there — nothing leaves this machine until you click "
                "Submit on the GitHub page.\n\n"
                "If you cannot open a browser right now, 'Copy URL' puts "
                "the same pre-filled link on your clipboard."
            ),
        )
        intro.SetName("Introduction")
        intro.Wrap(680)
        root.Add(intro, 0, wx.EXPAND | wx.ALL, 8)

        # --- Title ---------------------------------------------------------
        title_label = wx.StaticText(self.dialog, label="Title")
        title_label.SetName("Title label")
        root.Add(title_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self._title_ctrl = wx.TextCtrl(self.dialog)
        self._title_ctrl.SetName("Title")
        root.Add(self._title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Description ---------------------------------------------------
        desc_label = wx.StaticText(
            self.dialog, label="What happened? (include any error messages)"
        )
        desc_label.SetName("Description label")
        root.Add(desc_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self._desc_ctrl = wx.TextCtrl(self.dialog, style=wx.TE_MULTILINE)
        self._desc_ctrl.SetName("Description")
        self._desc_ctrl.SetMinSize((560, 100))
        root.Add(self._desc_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Expected ------------------------------------------------------
        expect_label = wx.StaticText(
            self.dialog, label="What did you expect to happen?"
        )
        expect_label.SetName("Expected label")
        root.Add(expect_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self._expect_ctrl = wx.TextCtrl(self.dialog, style=wx.TE_MULTILINE)
        self._expect_ctrl.SetName("Expected behaviour")
        self._expect_ctrl.SetMinSize((560, 60))
        root.Add(self._expect_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Steps ---------------------------------------------------------
        steps_label = wx.StaticText(
            self.dialog, label="Steps to reproduce (one per line)"
        )
        steps_label.SetName("Steps label")
        root.Add(steps_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self._steps_ctrl = wx.TextCtrl(self.dialog, style=wx.TE_MULTILINE)
        self._steps_ctrl.SetName("Steps to reproduce")
        self._steps_ctrl.SetMinSize((560, 80))
        root.Add(self._steps_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Auto-attached log footer -------------------------------------
        if self._log_tail:
            footer = wx.StaticText(
                self.dialog,
                label=(
                    "Recent lines from speechcraft_error.log will be "
                    "attached automatically (read-only)."
                ),
            )
            footer.SetName("Log attachment note")
            root.Add(footer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # --- Buttons -------------------------------------------------------
        self._btn_open = wx.Button(
            self.dialog, self._ID_OPEN, label="&Open in browser"
        )
        self._btn_open.SetName("Open in browser")

        self._btn_copy = wx.Button(
            self.dialog, self._ID_COPY, label="&Copy URL"
        )
        self._btn_copy.SetName("Copy URL")

        self._btn_cancel = wx.Button(
            self.dialog, wx.ID_CANCEL, label="Cancel"
        )
        self._btn_cancel.SetName("Cancel")
        self._btn_cancel.SetDefault()

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(self._btn_open)
        btn_sizer.AddButton(self._btn_copy)
        btn_sizer.AddButton(self._btn_cancel)
        btn_sizer.Realize()
        root.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.dialog.SetSizer(root)

        # --- Events --------------------------------------------------------
        self._btn_open.Bind(wx.EVT_BUTTON, self._on_open)
        self._btn_copy.Bind(wx.EVT_BUTTON, self._on_copy)
        self._btn_cancel.Bind(wx.EVT_BUTTON, self._on_cancel)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self) -> BugReportResult:
        """Show the dialog modally and return the user's choice.

        Initial focus lands on the Title field so screen readers
        announce the first input first, not the buttons.
        """
        try:
            self.dialog.CentreOnParent()
            self._title_ctrl.SetFocus()
            self.dialog.ShowModal()
            return self._result
        finally:
            self.dialog.Destroy()

    def set_title(self, text: str) -> None:
        """Pre-fill the Title field. Used by the post-crash hook."""
        self._title_ctrl.SetValue(text)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_open(self, _event: wx.Event) -> None:
        url = self._build_url()
        opened = False
        try:
            opened = bool(webbrowser.open(url))
        except Exception:
            opened = False
        self._capture_result("send")
        if not opened:
            # Browser launch failed — fall back to clipboard so the
            # user is never stranded with their text and no way out.
            self._copy_to_clipboard(url)
            wx.MessageBox(
                "Your browser could not be opened. The pre-filled URL "
                "is on your clipboard — paste it into a browser or "
                "email it to tracy@tracysmith.co.za.",
                "Browser unavailable",
                wx.OK | wx.ICON_INFORMATION,
            )
        self.dialog.EndModal(self._ID_OPEN)

    def _on_copy(self, _event: wx.Event) -> None:
        url = self._build_url()
        self._copy_to_clipboard(url)
        self._capture_result("copy")
        wx.MessageBox(
            "The pre-filled bug-report URL is on your clipboard.",
            "Copied",
            wx.OK | wx.ICON_INFORMATION,
        )
        self.dialog.EndModal(self._ID_COPY)

    def _on_cancel(self, _event: wx.Event) -> None:
        self._result = BugReportResult(act="cancel")
        self.dialog.EndModal(wx.ID_CANCEL)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_url(self) -> str:
        return build_issue_url(
            title=self._title_ctrl.GetValue().strip(),
            description=self._desc_ctrl.GetValue().strip(),
            expected=self._expect_ctrl.GetValue().strip(),
            steps=self._steps_ctrl.GetValue().strip(),
            app_version=self._app_version,
            platform_label=f"{platform.system()} {platform.release()}",
            python_version=sys.version.splitlines()[0],
            screen_reader=self._screen_reader,
            log_tail=self._log_tail,
        )

    def _capture_result(self, act: Act) -> None:
        self._result = BugReportResult(
            act=act,
            title=self._title_ctrl.GetValue().strip(),
            description=self._desc_ctrl.GetValue().strip(),
            expected=self._expect_ctrl.GetValue().strip(),
            steps=self._steps_ctrl.GetValue().strip(),
        )

    def _copy_to_clipboard(self, text: str) -> None:
        if wx.TheClipboard.IsOpened():
            wx.TheClipboard.Close()
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
            finally:
                wx.TheClipboard.Close()

    @staticmethod
    def _detect_screen_reader() -> str:
        """Best-effort detection. Empty string if unknown."""
        try:
            import win32gui  # type: ignore[import-not-found]
            foreground = win32gui.GetForegroundWindow()
            if not foreground:
                return ""
            pid = win32gui.GetWindowThreadProcessId(foreground)[1]
            try:
                import psutil  # type: ignore[import-not-found]
                proc = psutil.Process(pid)
                name = proc.name().lower()
            except Exception:
                return ""
            if "nvda" in name:
                return "NVDA"
            if "jaws" in name:
                return "JAWS"
            if "narrator" in name:
                return "Narrator"
        except Exception:
            return ""
        return ""
