"""Splash screen shown during SpeechCraft Studio startup.

Provides an accessible loading indicator that NVDA can read, instead
of leaving the user staring at a blank screen wondering if anything is
happening. The splash shows real text (not a spinner's alt text) and
logs each startup milestone as it completes — so if startup stalls
midway, the user can read what's already done and what step is
currently blocking.

Lifecycle:
    Splash() created → shows immediately with current milestone
    Splash.update("step name") → updates the visible text + NVDA-speakable label
    Splash.close() → dismiss

Threading model: the splash is created and shown on the main thread,
before wx.App().MainLoop() is entered. Updates are called from the
main thread only (the work it monitors is run on the main thread
sequentially, not via threading). If we ever run startup work in a
background thread, the splash updates must use wx.CallAfter to
bounce back to the UI thread.
"""

from __future__ import annotations

import time
import wx


# The ordered list of startup milestones. Each step shows as a checkmark
# (or "in progress" marker) next to a human-readable description. The order
# is also the announcement order — NVDA will speak the whole window
# when it gains focus, so the user knows what's done and what's left.
STARTUP_STEPS = (
    "Loading user interface",
    "Checking FFmpeg",
    "Checking Piper TTS",
    "Loading effects presets",
    "Loading recent projects",
    "Preparing workspace",
)


class Splash(wx.Frame):
    """Borderless, always-on-top splash window with a status checklist.

    Borderless so it reads as a clear loading surface rather than a
    dialog the user might try to interact with. Always-on-top so the
    user can't lose it behind another window while waiting.

    Pressing Escape closes the splash. This is a power-user shortcut
    for testing — in normal use Splash.close() is called from main()
    once the main frame is visible.
    """

    def __init__(self) -> None:
        # wx.Frame so we can call Raise(), SetFocus(), and have proper
        # accessibility tree entry rather than a top-level wx.Dialog
        # (which is also fine, but Frame is more idiomatic for splash).
        super().__init__(
            None,
            wx.ID_ANY,
            "SpeechCraft Studio starting",
            style=wx.BORDER_NONE
            | wx.STAY_ON_TOP
            | wx.FRAME_NO_TASKBAR,
            size=(520, 360),
        )
        # Set a redundant but explicit accessible name. Some screen
        # readers ignore the window title and only announce via Name.
        self.SetName("SpeechCraft Studio loading")
        self.CentreOnScreen()
        self._completed: set[str] = set()
        self._build_ui()
        self.Show()
        # Yield so the splash actually paints before any heavy work
        # starts. Without this, on slow machines the splash can appear
        # blank for the entire startup duration.
        wx.Yield()
        self._speak_announcement()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(248, 246, 240))  # warm cream

        title = wx.StaticText(
            panel,
            label="SpeechCraft Studio",
        )
        title.SetFont(
            wx.Font(
                22,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )

        subtitle = wx.StaticText(
            panel,
            label="Loading, please wait…",
        )
        subtitle.SetFont(
            wx.Font(
                10,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
            )
        )

        # One StaticText line per startup step. Stored on self so we
        # can update them in place as work progresses. Each line has a
        # explicit label so NVDA can announce it without reading 8 lines
        # as one blob.
        self._step_labels: dict[str, wx.StaticText] = {}
        step_box = wx.BoxSizer(wx.VERTICAL)
        for step in STARTUP_STEPS:
            row = wx.BoxSizer(wx.HORIZONTAL)
            marker = wx.StaticText(panel, label="○")
            marker.SetName(f"{step} status: pending")
            row.Add(marker, 0, wx.RIGHT, 10)
            label = wx.StaticText(panel, label=step)
            label.SetName(f"{step}")
            row.Add(label, 1, wx.EXPAND)
            # Cache for in-place updates
            self._step_labels[step] = marker  # we update the marker
            step_box.Add(row, 0, wx.EXPAND | wx.BOTTOM, 6)

        # Aggregate status message that NVDA will also pick up. Updated
        # alongside the step marks so the user always knows the current
        # overall status, not just a list of completed steps.
        self._status = wx.StaticText(panel, label="Starting…")
        self._status.SetName("Status: Starting up")
        self._status.SetFont(
            wx.Font(
                11,
                wx.FONTFAMILY_DEFAULT,
                wx.FONTSTYLE_ITALIC,
                wx.FONTWEIGHT_NORMAL,
            )
        )

        # Bind Escape → close. Note: this only matters during dev/testing,
        # because production Splash.close() is called automatically when
        # the main frame is ready. Users would never manually close it.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(title, 0, wx.LEFT | wx.TOP, 30)
        outer.Add(subtitle, 0, wx.LEFT | wx.BOTTOM, 30)
        outer.Add(step_box, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 30)
        outer.Add(self._status, 0, wx.LEFT | wx.TOP, 30)

        panel.SetSizer(outer)
        outer.Fit(self)

    def _on_char(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def _speak_announcement(self) -> None:
        """Speak a one-line status when the splash gets focus.

        If pyttsx3 is unavailable (which it usually is in our frozen
        EXE), we rely on NVDA to read the controls when focus arrives.
        Still, trying is cheap and helps in JAWS too.
        """
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say("SpeechCraft Studio is starting. Please wait.")
            engine.runAndWait()
        except Exception:
            pass

    def update(self, step: str, status: str | None = None) -> None:
        """Mark a startup step as complete and update the visible status.

        Steps are matched by exact string against STARTUP_STEPS. If a
        step has already been marked complete, this is a no-op.

        status: optional human-readable description of what just
        finished (e.g. "FFmpeg found at /usr/bin/ffmpeg"). If given,
        shown in the bottom status line.
        """
        if step in self._completed:
            return
        self._completed.add(step)
        marker = self._step_labels.get(step)
        if marker is not None:
            marker.SetLabel("✓")
            marker.SetName(f"{step} status: complete")
            marker.SetForegroundColour(wx.Colour(58, 110, 70))  # forest green
        if status is not None:
            self._status.SetLabel(status)
            self._status.SetName(f"Status: {status}")
        # Force a paint so the user sees progress in real time, not
        # only when the event loop processes our batched updates.
        self.Refresh()
        wx.Yield()

    def close(self) -> None:
        """Dismiss the splash. Safe to call multiple times."""
        if self.IsBeingDeleted():
            return
        try:
            self.Close()
        except Exception:
            pass
