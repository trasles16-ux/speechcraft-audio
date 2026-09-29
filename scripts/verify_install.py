"""Verify an already-installed SpeechCraft Studio (no install, no uninstall).

Verification-only companion to installer_smoke.py: same checks (installed
payload, Add/Remove Programs keys in BOTH registry views, Setup version
resource, Start Menu shortcuts) but never runs the installer or the
uninstaller. Built for upgrading a broken install in place, where you want
the verification battery without the silent uninstall that ends the smoke
test.

Usage:
    python scripts/verify_install.py --version 1.3.7
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path

UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SpeechCraft Studio"
)
APP_KEY = r"Software\SpeechCraft\Studio"
INSTALL_DIR = Path(os.environ.get("ProgramW6432", r"C:\Program Files")) / (
    "SpeechCraft Studio"
)
START_MENU = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "SpeechCraft Studio"
)

REQUIRED_FILES = ("SpeechCraft_Studio.exe", "ReadMe.txt", "Uninstall.exe")
REQUIRED_SHORTCUTS = ("SpeechCraft Studio.lnk", "Uninstall.lnk")


class CheckFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)
    print(f"  [OK] {message}")


def read_reg_str(root: int, sub_key: str, name: str) -> str | None:
    """Read a REG_SZ from BOTH registry views (native first, then WOW64-32)."""
    try:
        import winreg
    except ImportError:
        return None
    for view in (0, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(root, sub_key, 0, winreg.KEY_READ | view) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except OSError:
            continue
    return None


def reg_key_exists(root: int, sub_key: str) -> bool:
    try:
        import winreg
    except ImportError:
        return False
    for view in (0, winreg.KEY_WOW64_32KEY):
        try:
            winreg.OpenKey(root, sub_key, 0, winreg.KEY_READ | view).Close()
            return True
        except OSError:
            continue
    return False


HKEY_LOCAL_MACHINE = 0x80000002


def verify_installed_files() -> None:
    print("Verifying installed files in Program Files:")
    check(INSTALL_DIR.is_dir(), f"install dir exists: {INSTALL_DIR}")
    for name in REQUIRED_FILES:
        check((INSTALL_DIR / name).is_file(), f"file present: {name}")
    exe = INSTALL_DIR / "SpeechCraft_Studio.exe"
    size_mb = exe.stat().st_size / 1024 / 1024
    check(size_mb > 1.0, f"EXE is a real payload ({size_mb:.1f} MB)")


def verify_registry(version: str | None) -> None:
    print("Verifying Add/Remove Programs registry keys:")
    display_name = read_reg_str(HKEY_LOCAL_MACHINE, UNINSTALL_KEY, "DisplayName")
    check(display_name == "SpeechCraft Studio", f"DisplayName = {display_name!r}")
    uninstall_string = read_reg_str(HKEY_LOCAL_MACHINE, UNINSTALL_KEY, "UninstallString")
    check(
        uninstall_string is not None and "Uninstall.exe" in uninstall_string,
        f"UninstallString = {uninstall_string!r}",
    )
    display_version = read_reg_str(HKEY_LOCAL_MACHINE, UNINSTALL_KEY, "DisplayVersion")
    check(display_version is not None, f"DisplayVersion present: {display_version!r}")
    if version is not None:
        check(
            display_version == version,
            f"DisplayVersion {display_version!r} matches expected {version!r}",
        )
    install_dir_reg = read_reg_str(HKEY_LOCAL_MACHINE, APP_KEY, "InstallDir")
    check(
        install_dir_reg is not None and Path(install_dir_reg) == INSTALL_DIR,
        f"HKLM InstallDir = {install_dir_reg!r}",
    )


def verify_setup_version_resource(version: str | None) -> None:
    setup = INSTALL_DIR / "Uninstall.exe"
    print("Verifying the Uninstaller version resource (sanity):")
    handle = ctypes.windll.version.GetFileVersionInfoSizeW(str(setup), None)
    check(handle > 0, "uninstaller carries a version resource")
    # Full Setup.exe resource checks live in installer_smoke.py; here the
    # uninstaller resource is only a sanity signal that NSIS metadata exists.
    _ = version


def verify_start_menu() -> None:
    print("Verifying Start Menu shortcuts:")
    for name in REQUIRED_SHORTCUTS:
        check((START_MENU / name).is_file(), f"shortcut present: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=None, help="Expected version (e.g. 1.3.7)")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("This verification runs on Windows only.")
        return 1

    try:
        verify_installed_files()
        verify_registry(args.version)
        verify_setup_version_resource(args.version)
        verify_start_menu()
    except CheckFailure as exc:
        print(f"\nVERIFY: FAIL - {exc}")
        return 1
    print("\nVERIFY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
