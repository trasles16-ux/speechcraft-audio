"""Crash-time helpers: read the local error log for the bug-report flow.

SpeechCraft already writes to ``speechcraft_error.log`` from
``run_speechcraft.py``'s launcher. This module is the read-side:
it returns the last N lines of that file so the bug-report dialog
can attach them to the GitHub URL pre-fill.

The function is intentionally dependency-light so it can be called
from any code path without importing wx.
"""

from __future__ import annotations

from pathlib import Path

# How many tail lines to attach. Bounded so a runaway log does not
# dwarf the rest of the GitHub URL.
_TAIL_LINES = 40


def read_log_tail(log_path: str | Path | None = None, *, max_lines: int = _TAIL_LINES) -> str | None:
    """Return the last ``max_lines`` lines of the local error log.

    Returns ``None`` when the log file does not exist or cannot be
    read; the bug-report dialog treats ``None`` as "no log to attach".

    Parameters
    ----------
    log_path:
        Path to the log file. Defaults to ``speechcraft_error.log``
        in the current working directory, matching the launcher.
    max_lines:
        Override the line cap (mainly for tests).
    """
    if log_path is None:
        log_path = Path("speechcraft_error.log")
    else:
        log_path = Path(log_path)

    if not log_path.is_file():
        return None

    try:
        # Read the whole file then keep the tail. Log files here are
        # small (one launch's worth of tracebacks), so this is fine.
        # Switch to a true ring-buffer reader only if size becomes
        # an issue.
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    lines = text.splitlines()
    tail = lines[-max_lines:] if len(lines) > max_lines else lines
    if not tail:
        return None
    return "\n".join(tail)
