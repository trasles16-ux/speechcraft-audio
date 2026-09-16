"""Shared user-preferences storage for SpeechCraft Studio.

Single read/write path for ``~/.speechcraft/setup.json``. Previously
this logic lived in ``onboarding_dialog._load_prefs`` /
``_save_prefs`` and was re-implemented in ``feature_flags``. This
module is the canonical version that all three callers (onboarding,
feature_flags, future feature_manager) share.

Pure logic - no wx dependency so it can be tested in Linux CI.

Why a dedicated module:
- One place that owns the path layout (``PREFS_DIR`` / ``PREFS_FILE``)
- One place that defines read/write semantics (permissive read,
  silent save on permission errors, preserve unrelated keys)
- New consumers don't re-invent the same helpers with subtle drift

File format
-----------
``setup.json`` is a JSON object whose top-level keys are owned by
different modules:

- ``preferred_bundle`` - onboarding_dialog.py (v1.0-v1.2)
- ``auto_check_updates`` - audio_editor.py auto-update (v1.2+)
- ``skipped_versions`` - audio_editor.py auto-update (v1.2+)
- ``features`` - feature_flags.py (v1.3+)
- ``wizard_completed`` - feature_flags.py (v1.3+)

Each owner calls :func:`load_prefs` and writes only its own keys via
:func:`save_prefs`. Other keys are preserved on disk (read-modify-
write, not full-replace).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final


# --- Paths ------------------------------------------------------------------

if sys.platform == "win32":
    PREFS_DIR: Final = Path(os.environ.get("APPDATA", str(Path.home()))) / "SpeechCraft"
else:
    PREFS_DIR: Final = Path.home() / ".speechcraft"

PREFS_FILE: Final = PREFS_DIR / "setup.json"

#: Sidecar file the NSIS installer drops at install time, containing
#: the edition choice ("Core" or "Full") the user picked. Merged into
#: setup.json as ``preferred_bundle`` on first app launch, then deleted.
PREFERRED_BUNDLE_SIDECAR: Final = PREFS_DIR / "PreferredBundle.txt"


def merge_installer_edition(
    *,
    prefs_file: Path | None = None,
    sidecar: Path | None = None,
) -> None:
    """Ingest the installer's PreferredBundle.txt sidecar into setup.json.

    The NSIS installer cannot safely rewrite setup.json (it would need
    to parse JSON), so it drops the edition choice in a one-line
    sidecar file. This function merges it into the ``preferred_bundle``
    top-level key and deletes the sidecar. Idempotent: if the sidecar
    is already gone, no-op.
    """
    sidecar_path = sidecar if sidecar is not None else PREFERRED_BUNDLE_SIDECAR
    if not sidecar_path.exists():
        return
    try:
        edition = sidecar_path.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if edition not in ("Core", "Full"):
        # Unknown content - ignore rather than corrupt the prefs file.
        return
    prefs_file_path = prefs_file if prefs_file is not None else PREFS_FILE
    prefs = load_prefs(prefs_file=prefs_file_path)
    prefs["preferred_bundle"] = edition
    save_prefs(prefs, prefs_file=prefs_file_path)
    try:
        sidecar_path.unlink()
    except OSError:
        pass


# --- Read / write -----------------------------------------------------------


def load_prefs(
    *,
    prefs_file: Path | None = None,
) -> dict[str, Any]:
    """Read setup.json and return its dict.

    Empty / missing / corrupt / non-object roots all return ``{}``.
    This is intentional: a broken prefs file should not lock the user
    out of SpeechCraft. Callers can re-default and re-prompt.

    Never raises.
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # Only dict-shaped roots make sense for our schema (top-level keys
    # are owned by different modules). A list / number / string root is
    # almost certainly a hand-editing mistake - treat as empty rather
    # than trying to coerce.
    if not isinstance(data, dict):
        return {}
    return data


def save_prefs(
    prefs: dict[str, Any] | None = None,
    *,
    prefs_file: Path | None = None,
) -> None:
    """Write prefs to setup.json.

    Best-effort: silent on permission errors so a read-only filesystem
    just means we re-prompt next launch. Other modules' top-level keys
    are preserved because :func:`load_prefs` is called first; the
    caller passes a dict that already contains those keys (read-modify-
    write pattern). If the caller passes only their own keys, those
    other keys are removed from disk - that's the caller's bug, not
    ours.

    ``prefs`` may be passed positionally (legacy style from
    ``onboarding_dialog._save_prefs(prefs, prefs_file=None)``) or as
    a keyword (``save_prefs(prefs={...})``).

    Indented JSON for hand-editing safety.
    """
    if prefs is None:
        raise TypeError(
            "save_prefs() missing required argument: 'prefs'"
        )
    target = prefs_file if prefs_file is not None else PREFS_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(prefs, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        # Permission denied, read-only filesystem, etc. Not fatal.
        pass


__all__ = (
    "PREFS_DIR",
    "PREFS_FILE",
    "PREFERRED_BUNDLE_SIDECAR",
    "load_prefs",
    "save_prefs",
    "merge_installer_edition",
)