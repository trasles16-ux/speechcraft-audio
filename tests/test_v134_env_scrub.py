"""Regression tests: the updater scrubs _PYI_* env when launching the installer.

v1.3.3 shipped an auto-update flow where the running app (a PyInstaller
onefile, which carries _PYI_* internal env vars) Popen'd the new
installer. The installer inherited those vars, and the new app
launched from the installer's finish page saw a dead "originating
parent" — PyInstaller >= 6.22.1's onefile security check (mandatory
in elevated mode) aborted it with "Security validation failure:
parent process has different executable!". launch_installer now
starts the installer from a scrubbed environment.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from unittest import mock

import pytest

needs_wx = pytest.mark.skipif(
    not importlib.util.find_spec("wx"),
    reason="wxPython not installed",
)

import updater  # noqa: E402


def _installer_path(tmp_path: Path) -> Path:
    p = tmp_path / "setup.exe"
    p.write_bytes(b"stub")
    return p


def test_launch_installer_scrubs_pyinstaller_env(tmp_path):
    """_PYI_* variables from the running onefile app must NOT reach
    the installer process; everything else passes through."""
    import os

    leaked = {}

    def fake_popen(args, **kwargs):
        leaked["args"] = args
        leaked["env"] = kwargs.get("env")

        class _Proc:
            def poll(self):
                return None  # installer "still running"
        return _Proc()

    # Simulate the app's process environment carrying PyInstaller
    # internals, plus a normal var that must survive.
    with mock.patch.object(os, "environ", {
        "_PYI_APPLICATION_HOME_DIR": r"C:\Users\x\AppData\Local\Temp\_MEI123",
        "_PYI_PARENT_PROCESS_LEVEL": "2",
        "_PYI_ARCHIVE_FILE": r"C:\Program Files\SpeechCraft Studio\SpeechCraft_Studio.exe",
        "PATH": r"C:\Windows\System32",
        "USERNAME": "trace",
    }), mock.patch.object(updater.subprocess, "Popen", fake_popen), \
         mock.patch("time.sleep"):
        updater.launch_installer(str(_installer_path(tmp_path)))

    env = leaked["env"]
    assert env is not None, "launch_installer must pass an explicit env"
    # No _PYI_* may leak:
    assert not any(k.startswith("_PYI_") for k in env), \
        f"PyInstaller internals leaked: {[k for k in env if k.startswith('_PYI_')]}"
    # Unrelated vars pass through unchanged:
    assert env["PATH"] == r"C:\Windows\System32"
    assert env["USERNAME"] == "trace"


def test_no_pyinstaller_variables_leak_globally():
    """Source-scan: the scrub must key off the _PYI_ prefix, so both
    the public PYINSTALLER_* vars and internal _PYI_* vars are
    considered. (The scrub only targets _PYI_* — PYINSTALLER_*
    names are public and safe to pass; this pins the decision so a
    'scrub everything' refactor has to consciously change this test.)
    """
    src = updater.__file__
    text = Path(src).read_text(encoding="utf-8")
    assert 'startswith("_PYI_")' in text or 'startswith(\'_PYI_\')' in text
