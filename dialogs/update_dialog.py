"""Update-prompt dialog — the first user-facing piece of auto-update.

Shown when:
- A newer release exists (either auto-detected on launch, or via
  Help → Check for updates).
- ``UpdateInfo`` carries release notes the user can read before deciding.

Three choices:
- "update"    — start the download-and-install flow.
- "skip"      — never nag about this version again (persisted in
                ``setup.json`` under ``skipped_versions``).
- "remind"    — default; ask again on the next launch.

The dialog is read-only and accessible — text-heavy with three large
buttons that NVDA can announce independently. The default button is
"Remind me later" so an accidental Enter never kicks off an installer.
"""

from __future__ import annotations

from typing import Final

import wx

from updater import UpdateInfo


_BTN_UPDATE_ID: Final = wx.NewIdRef()
_BTN_SKIP_ID: Final = wx.NewIdRef()
_BTN_REMIND_ID: Final = wx.NewIdRef()


class UpdatePromptDialog(wx.Dialog):
    """Ask the user what to do about a newly available release."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        current_version: str,
        update_info: UpdateInfo,
    ) -> None:
        super().__init__(
            parent,
            wx.ID_ANY,
            "Update SpeechCraft Studio",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(640, 480),
        )
        self.SetName("SpeechCraft Studio update prompt")
        self._info = update_info
        self._build_ui(current_version)
        self.CentreOnScreen()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char)

    def _on_char(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def _build_ui(self, current_version: str) -> None:
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(248, 246, 240))

        info = self._info
        installer = info.find_installer()
        size_mb = f"{installer.size_mb:.1f} MB" if installer else "unknown size"

        heading = wx.StaticText(
            panel,
            label=f"A new version is available: {info.title}",
        )
        heading.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        heading.SetName(
            f"New version available. Current is {current_version}, "
            f"new is {info.version}. Installer is {size_mb}."
        )

        intro = wx.StaticText(
            panel,
            label=(
                f"SpeechCraft {info.version} is ready to download and install. "
                f"The installer is {size_mb}. SpeechCraft will close and reopen "
                f"once the installer finishes."
            ),
        )
        intro.Wrap(580)
        intro.SetName(
            f"SpeechCraft version {info.version} is ready to download. "
            f"Installer is {size_mb}. SpeechCraft will close and reopen."
        )

        notes_label = wx.StaticText(panel, label="Release notes:")
        notes_label.SetName("Release notes section")

        notes_ctrl = wx.TextCtrl(
            panel,
            value=info.notes or "(no notes provided)",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
            name="Release notes",
        )
        notes_ctrl.SetMinSize((-1, 180))
        notes_ctrl.SetName(f"Release notes for version {info.version}")

        update_btn = wx.Button(
            panel,
            _BTN_UPDATE_ID,
            f"Download and install {info.version}",
        )
        update_btn.SetName(
            f"Download and install version {info.version} now. "
            f"SpeechCraft will close during installation."
        )
        update_btn.Bind(wx.EVT_BUTTON, self._on_update)

        skip_btn = wx.Button(
            panel,
            _BTN_SKIP_ID,
            f"Skip version {info.version}",
        )
        skip_btn.SetName(
            f"Skip version {info.version} permanently. "
            f"You will not be reminded of this version again."
        )
        skip_btn.Bind(wx.EVT_BUTTON, self._on_skip)

        remind_btn = wx.Button(panel, _BTN_REMIND_ID, "Remind me next launch")
        remind_btn.SetName(
            "Remind me about this update on the next launch. "
            "This is the default choice — pressing Enter will pick this."
        )
        remind_btn.SetDefault()  # safe default — Enter does NOT install
        remind_btn.Bind(wx.EVT_BUTTON, self._on_remind)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(update_btn, 0, wx.RIGHT, 8)
        buttons.Add(skip_btn, 0, wx.RIGHT, 8)
        buttons.Add(remind_btn, 0)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 16)
        sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        sizer.Add(notes_label, 0, wx.LEFT | wx.RIGHT, 16)
        sizer.Add(notes_ctrl, 1, wx.ALL | wx.EXPAND, 16)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 16)
        panel.SetSizer(sizer)
        sizer.Fit(self)

        self._choice = "remind"  # matches SetDefault above

    def _on_update(self, event: wx.Event) -> None:
        self._choice = "update"
        self.EndModal(wx.ID_OK)

    def _on_skip(self, event: wx.Event) -> None:
        self._choice = "skip"
        self.EndModal(wx.ID_OK)

    def _on_remind(self, event: wx.Event) -> None:
        self._choice = "remind"
        self.EndModal(wx.ID_CANCEL)

    def get_choice(self) -> str:
        """Return one of: 'update', 'skip', 'remind'. Default 'remind'."""
        return self._choice