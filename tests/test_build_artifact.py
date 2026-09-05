"""Build artifact verification: ensure the bundled EXE contains everything it claims to.

These tests catch the exact failure mode that bit SpeechCraft v1.0.0:
a 9.4 MB PyInstaller bundle that reported success but silently dropped
``wx`` (wxPython) and ran with ``ModuleNotFoundError: No module named 'wx'``
on every user machine.

The class of bug is: **PyInstaller exits 0 + artifact under a few MB +
heavy optional deps** = someone built against a half-installed venv.
The fix is an explicit check that the PyInstaller output actually
contains the largest, most-likely-to-be-missing heavy dependency
(wx in this app's case), and that the EXE size is roughly what we
expect for a fully-bundled app.

Run via:
    pytest tests/test_build_artifact.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# Modules that MUST be bundled in the EXE for the app to start.
# Without these, the runtime fails with ModuleNotFoundError on the
# user's machine — exactly the v1.0.0 bug we are guarding against.
REQUIRED_BUNDLED_PACKAGES = [
    ("wx", "wxPython — UI framework"),
    ("numpy", "NumPy — used by all audio modules"),
    ("pydub", "pydub — audio I/O"),
    ("sounddevice", "sounddevice — used by AudioClipboard"),
    ("pedalboard", "pedalboard — effects engine"),
]

# Sanity floor: an empty PyInstaller bootloader on Windows is ~7 MB.
# Any build under 50 MB has obviously dropped a heavy dependency.
# A correctly-built SpeechCraft is ~340 MB (mostly whisper + torch + pedalboard).
MIN_EXE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _find_exe() -> Path | None:
    """Find the most recently-built EXE in dist/."""
    if not DIST.exists():
        return None
    exes = sorted(DIST.glob("*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    return exes[0] if exes else None


def _read_pyinstaller_toc(exe_path: Path) -> list[str] | None:
    """Parse the PyInstaller EXE and return a list of entry names.

    Uses the well-tested pyinstxtractor-ng library, which handles
    every bootloader version. We don't want to reimplement this
    parser ourselves — that's how v1.0.0 was missed in the first place.
    """
    try:
        from pyinstxtractor_ng import PyInstArchive
    except ImportError:
        return None
    try:
        archive = PyInstArchive(str(exe_path))
        if not archive.open():
            return None
        archive.checkFile()
        archive.getCArchiveInfo()
        archive.parseTOC()
        names = [e.name for e in archive.tocList if getattr(e, "name", None)]
        archive.close()
        return names if names else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_exe_exists() -> None:
    """The build artifact should exist in dist/."""
    exe = _find_exe()
    if exe is None:
        pytest.skip(
            "No EXE found in dist/. Run `pyinstaller SpeechCraft_Studio.spec "
            "--clean` first. This test is a release gate, not a build trigger."
        )


def test_exe_size_sanity() -> None:
    """The EXE should be at least MIN_EXE_SIZE_BYTES.

    A 9.4 MB PyInstaller build of SpeechCraft is too small to contain
    wxPython + numpy + pydub + sounddevice + pedalboard + scipy +
    torch + faster-whisper. If you see a build under ~50 MB it has
    silently dropped something heavy. Do NOT publish it.
    """
    exe = _find_exe()
    if exe is None:
        pytest.skip("No EXE to inspect")

    size = exe.stat().st_size
    assert size >= MIN_EXE_SIZE_BYTES, (
        f"EXE is only {size / 1024 / 1024:.1f} MB — too small for a SpeechCraft "
        f"build (expected at least {MIN_EXE_SIZE_BYTES / 1024 / 1024:.0f} MB). "
        f"Heavy packages (wx, numpy, torch, etc.) were almost certainly not "
        f"included. Rebuild from a clean venv where `pip install -r "
        f"requirements.txt` finished before running pyinstaller."
    )


def test_exe_toc_is_readable() -> None:
    """We must be able to parse the PyInstaller CArchive TOC.

    If this fails, the bundle is corrupted or non-standard and we can't
    reliably verify what's bundled. Treat as a build failure.
    """
    exe = _find_exe()
    if exe is None:
        pytest.skip("No EXE to inspect")

    toc = _read_pyinstaller_toc(exe)
    assert toc is not None and len(toc) > 0, (
        f"Could not parse the PyInstaller CArchive TOC for {exe.name}. "
        f"This usually means the build is corrupted, or the bootloader "
        f"version changed between the build and this test's environment."
    )


def test_exe_contains_wx() -> None:
    """The EXE bundle MUST contain wxPython.

    This is the exact bug from v1.0.0: a 9.4 MB build missing wx.
    """
    exe = _find_exe()
    if exe is None:
        pytest.skip("No EXE to inspect")

    toc = _read_pyinstaller_toc(exe)
    assert toc is not None, "Cannot parse TOC"

    # Entries use Windows backslashes; check both separators
    wx_hits = [n for n in toc if "wx" in n and (
        n == "wx" or n.startswith("wx/") or n.startswith("wx\\")
        or "/wx/" in n or "\\wx\\" in n
    )]
    # Also accept any toc entry under the wx package directory
    if not wx_hits:
        wx_hits = [n for n in toc if "/wx/" in n.replace("\\", "/") or n.replace("\\", "/").startswith("wx/")]
    assert wx_hits, (
        f"EXE {exe.name} ({exe.stat().st_size / 1024 / 1024:.1f} MB) "
        f"contains no wx/ entries. This is the v1.0.0 pattern. Rebuild."
    )


@pytest.mark.parametrize("module,description", REQUIRED_BUNDLED_PACKAGES)
def test_exe_contains_required_module(module: str, description: str) -> None:
    """Each heavy dependency must appear in the CArchive TOC or PYZ.

    PyInstaller's CArchive TOC lists every file entry by name. The PYZ
    is a separate archive that contains all compiled Python bytecode
    (.pyc) for the bundled packages. Single-file modules like
    ``sounddevice`` have all their source as bytecode inside PYZ — they
    never appear as separate TOC entries. We check both to catch the
    partial-build failure mode where PyInstaller exits 0 but the
    bundle is missing crucial modules.
    """
    import os
    import zlib

    exe = _find_exe()
    if exe is None:
        pytest.skip("No EXE to inspect")

    toc = _read_pyinstaller_toc(exe)
    assert toc is not None, "Cannot parse TOC"

    # 1. Look for the module as a CArchive entry (e.g. wx/, numpy/)
    norm = [n.replace("\\", "/") for n in toc]
    matches = [
        n for n in norm
        if n == module
        or n.startswith(f"{module}/")
        or n.startswith(f"{module}.")
    ]

    # 2. If not found, search the PYZ archive (which holds compiled
    # bytecode for every bundled package).
    if not matches:
        try:
            archive = pyinstxtractor_ng.PyInstArchive(str(exe))  # type: ignore
        except NameError:
            from pyinstxtractor_ng import PyInstArchive
            archive = PyInstArchive(str(exe))
        archive.open()
        archive.checkFile()
        archive.getCArchiveInfo()
        archive.parseTOC()
        try:
            for entry in archive.tocList:
                if entry.name == "PYZ.pyz":
                    archive.fPtr.seek(entry.position, os.SEEK_SET)
                    raw = archive.fPtr.read(entry.cmprsdDataSize)
                    if entry.cmprsFlag == 1:
                        raw = zlib.decompress(raw)
                    marker = module.encode().lower()
                    if marker in raw.lower():
                        matches.append(f"PYZ archive contains {module}")
                    break
        finally:
            archive.close()

    assert matches, (
        f"EXE {exe.name} ({exe.stat().st_size / 1024 / 1024:.1f} MB) "
        f"contains no {module}/ entries (in CArchive TOC or PYZ archive). "
        f"{description}. This is the v1.0.0 root cause — PyInstaller ran "
        f"against a partially-installed venv. Rebuild cleanly."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
