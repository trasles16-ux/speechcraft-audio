#!/usr/bin/env python3
"""Build both SpeechCraft variants and the NSIS installer.

Run from the project root with the project venv active::

    python build_all.py           # Build both EXEs + installer
    python build_all.py --skip-core
    python build_all.py --skip-full
    python build_all.py --install  # also installs both into a staging dir for NSIS

Output:
    dist/SpeechCraft_Studio_Core.exe
    dist/SpeechCraft_Studio_Full.exe
    dist/SpeechCraft_Studio_Setup.exe  (NSIS installer)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
STAGING = ROOT / "build" / "staging"


def build_one(spec: str, dist_name: str) -> Path:
    """Run PyInstaller for one spec file. Returns the EXE path."""
    print(f"\n=== Building {dist_name} from {spec} ===")
    # Clean previous build of this variant but not the others.
    work_dir = ROOT / "build" / spec.replace("SpeechCraft_Studio", "").replace(".spec", "").lstrip("_").lower() or "default"
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

    exe = DIST / f"SpeechCraft_Studio_{dist_name}.exe"
    if not exe.exists():
        # Try Core (no underscore)
        alt = DIST / f"SpeechCraft_Studio{dist_name}.exe"
        if alt.exists():
            exe = alt
    if not exe.exists():
        sys.exit(f"Expected {exe} after build, but file is missing")
    size_mb = exe.stat().st_size / 1024 / 1024
    print(f"  OK: {exe.name} ({size_mb:.0f} MB)")
    return exe


def stage_for_installer(core_exe: Path, full_exe: Path | None) -> Path:
    """Copy both EXEs into a staging dir the NSIS script can pack.

    Returns the staging dir.
    """
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)

    # Core: always installed
    shutil.copy2(core_exe, STAGING / "SpeechCraft_Studio_Core.exe")

    # Full: optional. The installer asks the user.
    if full_exe and full_exe.exists():
        shutil.copy2(full_exe, STAGING / "SpeechCraft_Studio_Full.exe")

    # Copy the README and licence so the installer can show them.
    for name in ("README.md", "LICENSE", "CHANGELOG.md"):
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, STAGING / name)

    print(f"  Staged: {STAGING}")
    return STAGING


def build_nsis_installer(staging: Path) -> Path:
    """Run makensis to pack the staging dir into a single Setup.exe.

    Requires NSIS to be installed and on PATH (or accessible via
    ``C:/Program Files (x86)/NSIS/makensis.exe``).
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

    cmd = [
        str(makensis),
        "/DSTAGING=" + str(staging),
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
    ]
    for c in candidates:
        if c.exists():
            return c
    which = shutil.which("makensis")
    if which:
        return Path(which)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SpeechCraft Studio variants + NSIS installer")
    parser.add_argument("--skip-core", action="store_true", help="Don't build the Core EXE")
    parser.add_argument("--skip-full", action="store_true", help="Don't build the Full EXE")
    parser.add_argument("--skip-installer", action="store_true", help="Don't run NSIS")
    parser.add_argument("--install", action="store_true",
                        help="Run makensis to produce Setup.exe")
    args = parser.parse_args()

    DIST.mkdir(exist_ok=True)

    core_exe = full_exe = None
    if not args.skip_core:
        core_exe = build_one("SpeechCraft_Studio_Core.spec", "Core")
    if not args.skip_full:
        full_exe = build_one("SpeechCraft_Studio.spec", "Full")

    if not args.skip_installer and (core_exe or full_exe):
        # Use whichever EXE we have for staging. The Core is required
        # in the installer but Full is optional.
        if not core_exe:
            print("WARNING: no Core EXE found; installer will only ship Full.")
        # symlink alternative: rename to Full so we can stage
        staging_exe = full_exe if full_exe else core_exe
        other = core_exe if not full_exe else None
        staging = stage_for_installer(staging_exe, other)

        if args.install:
            setup = build_nsis_installer(staging)
            print(f"\n=== Done ===\n  EXEs:    {DIST}")
            print(f"  Setup:  {setup}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
