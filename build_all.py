#!/usr/bin/env python3
"""Build the SpeechCraft Studio EXE and the NSIS installer.

Single-EXE architecture (v1.3.6+): one bundled EXE that includes every
Python dep (pedalboard, librosa, scipy, faster_whisper, torch) but no
model files. The in-app wizard downloads Piper voices, Whisper
models, and piper.exe on first use.

Run from the project root with the project venv active::

    python build_all.py                # Build EXE + installer
    python build_all.py --skip-installer   # Just rebuild the EXE

Output:
    dist/SpeechCraft_Studio.exe         (the one and only EXE)
    dist/SpeechCraft_Studio_Setup.exe   (NSIS installer)
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
STAGING = ROOT / "build" / "staging"

SPEC = "SpeechCraft_Studio.spec"
EXE_NAME = "SpeechCraft_Studio"


def app_version() -> str:
    """Read the app version from audio_editor.py's __version__.

    Single source of truth: the same string feeds the EXE metadata,
    the NSIS version resource, and Add/Remove Programs. v1.3.6 kept
    five hand-maintained copies that had already drifted out of sync
    (the NSIS literal even carried an invalid 5-segment version).
    """
    source = (ROOT / "audio_editor.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if not match:
        sys.exit("Could not find __version__ in audio_editor.py")
    return match.group(1)


def build_one(spec: str, name: str) -> Path:
    """Run PyInstaller for the spec. Returns the EXE path."""
    print(f"\n=== Building {name} from {spec} ===")
    work_dir = ROOT / "build" / name.lower()
    if work_dir.exists():
        shutil.rmtree(work_dir)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        spec,
    ]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        sys.exit(f"Build failed for {spec}")

    exe = DIST / f"{name}.exe"
    if not exe.exists():
        sys.exit(f"Expected {exe} after build, but file is missing")
    size_mb = exe.stat().st_size / 1024 / 1024
    print(f"  OK: {exe.name} ({size_mb:.0f} MB)")
    return exe


def stage_for_installer(exe: Path) -> Path:
    """Copy the EXE + bundled docs into a staging dir for NSIS.

    Returns the staging dir. v1.3.7: the installer reads EVERYTHING
    from this folder (the .nsi's File lines point at ${STAGING}), so
    the ReadMe.txt the Finish page offers must be staged here too —
    v1.3.6 had the .nsi reach into the CWD for it while the build
    script was already passing an unused /DSTAGING argument.
    """
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)

    shutil.copy2(exe, STAGING / f"{EXE_NAME}.exe")
    readme = ROOT / "installer" / "ReadMe.txt"
    if readme.exists():
        shutil.copy2(readme, STAGING / "ReadMe.txt")
    for name in ("README.md", "LICENSE", "CHANGELOG.md"):
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, STAGING / name)

    print(f"  Staged: {STAGING}")
    return STAGING


def build_nsis_installer(staging: Path, version: str) -> Path:
    """Run makensis to pack the staging dir into a single Setup.exe.

    Requires NSIS to be installed and on PATH (or accessible via
    ``C:/Program Files (x86)/NSIS/makensis.exe``). v1.3.7 passes the
    app version (the .nsi hard-errors without it, so a drifted
    version can never ship again) and the output dir (the v1.3.6
    script hardcoded an absolute user-profile path).
    """
    makensis = _find_makensis()
    if not makensis:
        sys.exit(
            "NSIS (makensis.exe) not found. Install from "
            "https://nsis.sourceforge.io/Download and rerun."
        )

    installer_script = ROOT / "installer" / "speechcraft_setup.nsi"
    if not installer_script.exists():
        sys.exit(f"NSIS script missing: {installer_script}")

    staged_exe = staging / f"{EXE_NAME}.exe"
    staged_readme = staging / "ReadMe.txt"
    for required in (staged_exe, staged_readme):
        if not required.exists():
            sys.exit(f"Staging incomplete: {required} is missing (run stage_for_installer first)")

    cmd = [
        str(makensis),
        "/DAPP_VERSION=" + version,
        "/DSTAGING=" + str(staging),
        "/DOUT_DIR=" + str(DIST),
        str(installer_script),
    ]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT / "installer"))
    if result.returncode != 0:
        sys.exit(f"NSIS build failed (exit {result.returncode})")

    setup = DIST / "SpeechCraft_Studio_Setup.exe"
    if not setup.exists():
        sys.exit(f"Expected {setup} after NSIS run, not found")
    size_mb = setup.stat().st_size / 1024 / 1024
    print(f"  OK: {setup.name} ({size_mb:.0f} MB)")
    return setup


def _find_makensis() -> Path | None:
    """Locate NSIS's makensis.exe on Windows."""
    candidates = [
        Path("C:/Program Files (x86)/NSIS/makensis.exe"),
        Path("C:/Program Files/NSIS/makensis.exe"),
        # Project-local copy (tools/nsis/nsis-3.10/) — Tracy bundles NSIS
        # with the source tree so contributors don't need a system install.
        Path(__file__).resolve().parent / "tools" / "nsis" / "nsis-3.10" / "Bin" / "makensis.exe",
        Path(__file__).resolve().parent / "tools" / "nsis" / "Bin" / "makensis.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    which = shutil.which("makensis")
    if which:
        return Path(which)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the SpeechCraft Studio EXE and NSIS installer"
    )
    parser.add_argument(
        "--skip-installer", action="store_true",
        help="Don't run NSIS (just build the EXE).",
    )
    args = parser.parse_args()

    DIST.mkdir(exist_ok=True)
    version = app_version()
    print(f"Building SpeechCraft Studio v{version}")
    exe = build_one(SPEC, EXE_NAME)

    if not args.skip_installer:
        staging = stage_for_installer(exe)
        setup = build_nsis_installer(staging, version)
        print(f"\n=== Done ===\n  EXE:    {exe}\n  Setup:  {setup}")
    else:
        print(f"\n=== Done ===\n  EXE:    {exe}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
