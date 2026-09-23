"""Accessible download-progress dialog for the auto-update installer.

Shows:
- A heading with the file being downloaded.
- A ``wx.Gauge`` progress bar (percentage).
- A live-region label with bytes downloaded / total + percent.
- A "Cancel" button.

The dialog's ``update(state, downloaded_bytes, total_bytes)`` method is
called from the download worker thread via ``wx.CallAfter`` so the UI
stays responsive. ``state`` is one of ``"connecting"``, ``"downloading"``,
``"retrying"``, ``"verifying"``, ``"done"`` — letting the UI tell the
user what's happening (vs. a frozen bar). The percentage / byte counters
are still driven by ``downloaded_bytes`` / ``total_bytes``.

``is_cancelled()`` is polled by ``updater.download_with_progress`` so the
user can abort mid-download.
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
        self._last_state: str | None = None
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

        self._heading = wx.StaticText(
            panel,
            label=f"Downloading {file_name}…",
        )
        self._heading.SetFont(
            wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        self._heading.SetName(f"Downloading {file_name}")

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
        sizer.Add(self._heading, 0, wx.ALL, 16)
        sizer.Add(self._gauge, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 16)
        sizer.Add(self._status, 0, wx.ALL, 16)
        sizer.Add(cancel_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 16)
        panel.SetSizer(sizer)
        sizer.Fit(self)

    def update(
        self,
        state: str,
        downloaded_bytes: int,
        total_bytes: int = 0,
    ) -> None:
        """Called from the UI thread (via ``wx.CallAfter``) to advance the bar.

        ``state`` is one of ``"connecting"``, ``"downloading"``,
        ``"retrying"``, ``"verifying"``, ``"done"``. The byte counters
        are whole-asset numbers (don't jump backwards between retries).
        ``total_bytes`` of 0 is treated as "unknown" — the bar and the
        live-region label still update, but the percentage is suppressed.
        """
        # Update the live-region label first so a screen reader hears the
        # state transition immediately, even before the bar moves.
        if state != self._last_state:
            self._render_state_label(state, downloaded_bytes, total_bytes)
            self._last_state = state

        if state == "downloading":
            total = total_bytes if total_bytes > 0 else self._total
            pct = min(100, int(downloaded_bytes * 100 / max(total, 1)))
            if pct != self._last_pct:
                self._gauge.SetValue(pct)
                self._last_pct = pct
                # Re-set the accessible name so NVDA re-announces.
                self._status.SetName(
                    f"Download status: {self._status.GetLabel()}"
                )
        elif state == "verifying":
            self._gauge.SetValue(100)
            self._last_pct = 100
            self._status.SetName(
                f"Download status: {self._status.GetLabel()}"
            )
        elif state == "done":
            self._gauge.SetValue(100)
            self._last_pct = 100
            self._status.SetName(
                f"Download status: {self._status.GetLabel()}"
            )

    def _render_state_label(
        self,
        state: str,
        downloaded_bytes: int,
        total_bytes: int,
    ) -> None:
        """Render the visible + accessible status label for ``state``."""
        if state == "connecting":
            self._status.SetLabel("Connecting to GitHub…")
            self._status.SetName("Download status: connecting to GitHub")
        elif state == "retrying":
            self._status.SetLabel(
                "Connection interrupted — retrying. Please wait…"
            )
            self._status.SetName(
                "Download status: connection interrupted, retrying"
            )
        elif state == "downloading":
            total = total_bytes if total_bytes > 0 else self._total
            pct = min(100, int(downloaded_bytes * 100 / max(total, 1)))
            self._status.SetLabel(
                f"Downloading… {pct}%  ({downloaded_bytes:,} of {total:,} bytes)"
            )
            self._status.SetName(
                f"Download status: downloading, {pct} percent, "
                f"{downloaded_bytes:,} of {total:,} bytes"
            )
        elif state == "verifying":
            self._status.SetLabel("Verifying checksum…")
            self._status.SetName("Download status: verifying checksum")
        elif state == "done":
            self._status.SetLabel("Done. Installer ready to launch.")
            self._status.SetName("Download status: done, installer ready")
        else:
            # Unknown state — pass through.
            self._status.SetLabel(f"Status: {state}")
            self._status.SetName(f"Download status: {state}")

    def is_cancelled(self) -> bool:
        """Polled by the download worker; True once user clicks Cancel."""
        return self._cancelled

    def _on_cancel(self, event: wx.Event | None) -> None:
        self._cancelled = True
        self.EndModal(wx.ID_CANCEL)