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

# Modules that MUST be bundled in the Full EXE for the app to start.
# Without these, the runtime fails with ModuleNotFoundError on the
# user's machine — exactly the v1.0.0 bug we are guarding against.
REQUIRED_BUNDLED_PACKAGES_FULL = [
    ("wx", "wxPython — UI framework"),
    ("numpy", "NumPy — used by all audio modules"),
    ("pydub", "pydub — audio I/O"),
    ("sounddevice", "sounddevice — used by AudioClipboard"),
    ("pedalboard", "pedalboard — effects engine"),
]

# Core build drops advanced-effects dependencies (pedalboard, scipy,
# librosa) and local Whisper (faster_whisper + torch). Everything in
# REQUIRED_BUNDLED_PACKAGES_CORE is needed for Core to run at all.
REQUIRED_BUNDLED_PACKAGES_CORE = [
    ("wx", "wxPython — UI framework"),
    ("numpy", "NumPy — used by all audio modules"),
    ("pydub", "pydub — audio I/O"),
    ("sounddevice", "sounddevice — used by AudioClipboard"),
]

# Sanity floor: an empty PyInstaller bootloader on Windows is ~7 MB.
# Any build under 50 MB has obviously dropped a heavy dependency.
# A correctly-built SpeechCraft is ~340 MB (mostly whisper + torch + pedalboard).
MIN_EXE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _find_exe(variant: str = "Full") -> Path | None:
    """Find the most recently-built EXE for the given variant."""
    if not DIST.exists():
        return None
    if variant == "Full":
        pattern = "SpeechCraft_Studio.exe"
    elif variant == "Core":
        pattern = "SpeechCraft_Studio_Core.exe"
    else:
        return None
    exes = sorted(DIST.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
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


def test_exe_size_sanity(variant="Full") -> None:
    """The EXE should be at least MIN_EXE_SIZE_BYTES.

    A 9.4 MB PyInstaller build of SpeechCraft is too small to contain
    wxPython + numpy + pydub + sounddevice + pedalboard + scipy +
    torch + faster-whisper. If you see a build under ~50 MB it has
    silently dropped something heavy. Do NOT publish it.
    """
    exe = _find_exe(variant)
    if exe is None:
        pytest.skip(f"No {variant} EXE to inspect")

    size = exe.stat().st_size
    assert size >= MIN_EXE_SIZE_BYTES, (
        f"EXE is only {size / 1024 / 1024:.1f} MB — too small for a SpeechCraft "
        f"build (expected at least {MIN_EXE_SIZE_BYTES / 1024 / 1024:.0f} MB). "
        f"Heavy packages (wx, numpy, torch, etc.) were almost certainly not "
        f"included. Rebuild from a clean venv where `pip install -r "
        f"requirements.txt` finished before running pyinstaller."
    )


def test_exe_toc_is_readable(variant="Full") -> None:
    """We must be able to parse the PyInstaller CArchive TOC."""
    exe = _find_exe(variant)
    if exe is None:
        pytest.skip(f"No {variant} EXE to inspect")

    toc = _read_pyinstaller_toc(exe)
    assert toc is not None and len(toc) > 0, (
        f"Could not parse the PyInstaller CArchive TOC for {exe.name}. "
        f"This usually means the build is corrupted, or the bootloader "
        f"version changed between the build and this test's environment."
    )


def test_exe_contains_wx(variant="Full") -> None:
    """The EXE bundle MUST contain wxPython.

    This is the exact bug from v1.0.0: a 9.4 MB build missing wx.
    """
    exe = _find_exe(variant)
    if exe is None:
        pytest.skip(f"No {variant} EXE to inspect")

    toc = _read_pyinstaller_toc(exe)
    assert toc is not None, "Cannot parse TOC"

    wx_hits = [n for n in toc if "wx" in n and (
        n == "wx" or n.startswith("wx/") or n.startswith("wx\\")
        or "/wx/" in n or "\\wx\\" in n
    )]
    if not wx_hits:
        wx_hits = [n for n in toc if "/wx/" in n.replace("\\", "/") or n.replace("\\", "/").startswith("wx/")]
    assert wx_hits, (
        f"EXE {exe.name} ({exe.stat().st_size / 1024 / 1024:.1f} MB) "
        f"contains no wx/ entries. This is the v1.0.0 pattern. Rebuild."
    )


def _check_module_in_exe(variant: str, module: str, description: str) -> None:
    import os
    import zlib

    exe = _find_exe(variant)
    if exe is None:
        pytest.skip(f"No {variant} EXE to inspect")

    toc = _read_pyinstaller_toc(exe)
    assert toc is not None, "Cannot parse TOC"

    norm = [n.replace("\\", "/") for n in toc]
    matches = [
        n for n in norm
        if n == module
        or n.startswith(f"{module}/")
        or n.startswith(f"{module}.")
    ]

    if not matches:
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
        f"contains no {module}/ entries. {description}. "
        f"Rebuild cleanly."
    )


@pytest.mark.parametrize("module,description", REQUIRED_BUNDLED_PACKAGES_FULL)
def test_full_exe_contains_required_module(module: str, description: str) -> None:
    """Full build must bundle these heavy deps."""
    _check_module_in_exe("Full", module, description)


@pytest.mark.parametrize("module,description", REQUIRED_BUNDLED_PACKAGES_CORE)
def test_core_exe_contains_required_module(module: str, description: str) -> None:
    """Core build must bundle wx + numpy + pydub + sounddevice but can
    safely skip pedalboard, librosa, scipy, faster_whisper, torch."""
    _check_module_in_exe("Core", module, description)


def test_core_exe_excludes_heavy_modules() -> None:
    """Core build must NOT contain pedalboard, faster_whisper, or torch.

    These are huge and optionally downloaded. If they sneak back in
    because some hidden import pulled them in, this test will fail and
    alert us.
    """
    import os
    import zlib

    exe = _find_exe("Core")
    if exe is None:
        pytest.skip("No Core EXE to inspect")

    from pyinstxtractor_ng import PyInstArchive
    archive = PyInstArchive(str(exe))
    archive.open()
    archive.checkFile()
    archive.getCArchiveInfo()
    archive.parseTOC()
    try:
        # Find PYZ archive
        raw = b""
        for entry in archive.tocList:
            if entry.name == "PYZ.pyz":
                archive.fPtr.seek(entry.position, os.SEEK_SET)
                data = archive.fPtr.read(entry.cmprsdDataSize)
                if entry.cmprsFlag == 1:
                    data = zlib.decompress(data)
                raw = data
                break

        # Check that "pedalboard" / "faster_whisper" / "torch" are NOT
        # embedded as module names. Whitelist: "faster" + "whisper" may
        # appear as part of unrelated strings, so we look at byte
        # patterns characteristic of Python module names.
        forbidden = ["pedalboard/", "faster_whisper/", "torch/"]
        for token in forbidden:
            if token.encode() in raw:
                pytest.fail(
                    f"Core EXE {exe.name} ({exe.stat().st_size / 1024 / 1024:.1f} MB) "
                    f"contains '{token}' byte sequence — heavy module sneaked in. "
                    f"Either update _Core.spec excludes, or move to Full build."
                )
    finally:
        archive.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
