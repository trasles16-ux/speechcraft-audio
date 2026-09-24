"""Build artifact verification: ensure the bundled EXE contains everything it claims to.

Single-EXE architecture (v1.3.6+): the build produces one EXE
that bundles every Python dep (pedalboard, librosa, scipy,
faster_whisper, torch). Model files (Piper voices, Whisper models,
piper.exe) download at runtime via the wizard.

Run with::
    pytest tests/test_build_artifact.py -v

If the EXE is missing, this test is skipped (it's a release gate,
not a build trigger).
"""

import os
import sys
import zlib
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parent.parent / "dist"

# Modules that MUST be bundled in the EXE for the app to start.
# Any module missing here means the EXE will fail at first run.
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
    """Find the most recently-built SpeechCraft_Studio.exe."""
    if not DIST.exists():
        return None
    exes = sorted(
        DIST.glob("SpeechCraft_Studio.exe"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
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
    """We must be able to parse the PyInstaller CArchive TOC."""
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


def _check_module_in_exe(module: str, description: str) -> None:
    exe = _find_exe()
    if exe is None:
        pytest.skip("No EXE to inspect")

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


@pytest.mark.parametrize("module,description", REQUIRED_BUNDLED_PACKAGES)
def test_exe_contains_required_module(module: str, description: str) -> None:
    """The single EXE must bundle every Python dep the app might need.

    Model files (Piper voices, Whisper models) are downloaded by the
    wizard, but the Python deps themselves must be bundled.
    """
    _check_module_in_exe(module, description)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
