"""Accessible download-progress dialog for the auto-update installer.

Shows:
- A heading with the file being downloaded.
- A ``wx.Gauge`` progress bar (percentage).
- A live-region label with bytes downloaded / total + percent.
- A "Cancel" button.

The dialog's ``update(downloaded_bytes)`` method is called from the
download worker thread via ``wx.CallAfter`` so the UI stays responsive.
``is_cancelled()`` is polled by ``updater.download_with_progress`` so
the user can abort mid-download.
"""

from __future__ import annotations

from typing import Final

import wx


_BTN_CANCEL_ID: Final = wx.NewIdRef()


class DownloadProgressDialog(wx.Dialog):
    """Modal dialog showing installer-download progress."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        file_name: str,
        total_bytes: int,
    ) -> None:
        super().__init__(
            parent,
            wx.ID_ANY,
            "Downloading update",
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.SetName("Downloading SpeechCraft update")
        self._total = max(total_bytes, 1)
        self._cancelled = False
        self._last_pct = -1
        self._build_ui(file_name)
        self.CentreOnScreen()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char)

    def _on_char(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_cancel(None)
        else:
            event.Skip()

    def _build_ui(self, file_name: str) -> None:
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(248, 246, 240))

        heading = wx.StaticText(
            panel,
            label=f"Downloading {file_name}…",
        )
        heading.SetFont(
            wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        heading.SetName(f"Downloading {file_name}")

        self._gauge = wx.Gauge(
            panel,
            range=100,  # percent
            style=wx.GA_HORIZONTAL | wx.GA_SMOOTH,
            name="Download progress",
        )
        self._gauge.SetMinSize((420, 24))

        self._status = wx.StaticText(
            panel,
            label="Starting download…",
            name="Download status",
        )
        self._status.SetName("Download status: starting")

        cancel_btn = wx.Button(panel, _BTN_CANCEL_ID, "Cancel")
        cancel_btn.SetName("Cancel download")
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 16)
        sizer.Add(self._gauge, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 16)
        sizer.Add(self._status, 0, wx.ALL, 16)
        sizer.Add(cancel_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 16)
        panel.SetSizer(sizer)
        sizer.Fit(self)

    def update(self, downloaded_bytes: int) -> None:
        """Called from the UI thread (via ``wx.CallAfter``) to advance the bar."""
        pct = min(100, int(downloaded_bytes * 100 / self._total))
        if pct != self._last_pct:
            self._gauge.SetValue(pct)
            self._status.SetLabel(
                f"{pct}%  ({downloaded_bytes:,} / {self._total:,} bytes)"
            )
            # NVDA only re-announces the status label when its accessible
            # name changes — re-set it on each percent change so screen
            # readers can speak the live progress.
            self._status.SetName(
                f"Download status: {pct}% ({downloaded_bytes:,} of "
                f"{self._total:,} bytes)"
            )
            self._last_pct = pct

    def is_cancelled(self) -> bool:
        """Polled by the download worker; True once user clicks Cancel."""
        return self._cancelled

    def _on_cancel(self, event: wx.Event | None) -> None:
        self._cancelled = True
        self.EndModal(wx.ID_CANCEL)