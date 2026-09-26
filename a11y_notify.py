"""Screen-reader announcements for SpeechCraft Studio (UIA notifications).

wx status-bar text changes are NOT announced by NVDA/JAWS automatically
(proven by live NVDA capture): the text is visible but silent. The
documented fix is UiaRaiseNotificationEvent (Windows 10 1703+), which
screen readers announce without stealing focus.

This module is wx-free and GUI-free: callers pass the HWND of the
window to announce on (``wx.Window.GetHandle()``). Best-effort by
design — returns False when the API is unavailable (pre-Win10-1703,
non-Windows, API rejected) so callers only ever lose the sound, never
the visible text.

Used by the setup wizard (page changes, download start/finish/fail)
where the old in-dialog StatusBar was never read by NVDA.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

# UIA NotificationKind.Other / NotificationProcessing.ImportantMostRecent
_KIND_OTHER = 4
_PROCESS_IMPORTANT_MOST_RECENT = 1

_uia_failed_once = False
_last_text: str = ""


def notify(hwnd: int, text: str, *, dedupe: bool = True) -> bool:
    """Raise a UIA notification for ``hwnd``; True when the API accepted it.

    ``dedupe=True`` collapses identical consecutive messages (the wizard
    re-fires the same page announcement when the user navigates back to
    a page they already visited), which screen readers would otherwise
    read twice in a row.
    """
    global _uia_failed_once, _last_text
    if not hwnd or not text:
        return False
    if sys.platform != "win32":
        return False
    if dedupe and text == _last_text:
        return True
    _last_text = text
    try:
        import ctypes
        from ctypes import wintypes

        raise_event = ctypes.windll.UIAutomationCore.UiaRaiseNotificationEvent
        raise_event.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_wchar_p,  # BSTR: the API copies, never frees
            ctypes.c_wchar_p,
        ]
        raise_event.restype = ctypes.HRESULT
        result = raise_event(
            wintypes.HWND(hwnd),
            _KIND_OTHER,
            _PROCESS_IMPORTANT_MOST_RECENT,
            text,
            "status",
        )
        if result != 0 and not _uia_failed_once:
            _uia_failed_once = True
            log.info(
                "UiaRaiseNotificationEvent rejected (hr=0x%08X); text stays visible",
                result & 0xFFFFFFFF,
            )
        return result == 0
    except Exception as e:
        if not _uia_failed_once:
            log.info("UIA notification unavailable (text stays visible): %s", e)
            _uia_failed_once = True
        return False


def announce_window(window, text: str, *, dedupe: bool = True) -> bool:
    """Convenience wrapper: announce ``text`` on a wx.Window (or None-safe).

    Safe to call with ``window=None`` (headless/tests) — returns False.
    Never raises: announcements are best-effort by contract.
    """
    if window is None:
        return False
    try:
        return notify(window.GetHandle(), text, dedupe=dedupe)
    except Exception:
        return False


__all__ = ("notify", "announce_window")
