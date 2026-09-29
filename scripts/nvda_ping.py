"""NVDA-audible ping: announce a message via Windows UIA notifications.

Thin wrapper around the app's a11y_notify.py (UiaRaiseNotificationEvent,
wx-free). Run from a normal shell; no admin needed.

Usage:
    python scripts/nvda_ping.py "Setup is waiting for your approval"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import a11y_notify  # noqa: E402


def _pick_hwnd() -> int:
    import ctypes

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        hwnd = ctypes.windll.user32.GetDesktopWindow()
    return hwnd


def main() -> int:
    message = " ".join(sys.argv[1:]).strip() or "SpeechCraft setup needs your attention"
    ok = a11y_notify.notify(_pick_hwnd(), message, dedupe=False)
    if ok:
        print(f"NVDA ping sent: {message}")
    else:
        print(f"NVDA ping FAILED: {message}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
