"""CI smoke test: silently install the built Setup.exe and verify it.

Runs the NSIS installer with /S (silent), waits for completion, then
verifies the installed files, the Add/Remove Programs registry keys,
the version resource, the Start Menu shortcuts, and finally
uninstalls silently (NSIS uninstaller /S) and checks the cleanup.

Exit codes: 0 = everything verified; 1 = any check failed (the log
says exactly which). Windows only - this is a CI/local release-gate
tool, not part of the app.

Usage:
    python scripts/installer_smoke.py --setup dist/SpeechCraft_Studio_Setup.exe
    python scripts/installer_smoke.py --setup ... --version 1.3.7 --keep
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Registry keys the installer writes (must match speechcraft_setup.nsi).
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
    """Assert with a hard failure (CI shows the message verbatim)."""
    if not condition:
        raise CheckFailure(message)
    print(f"  [OK] {message}")


def read_reg_str(root: int, sub_key: str, name: str) -> str | None:
    """Read a REG_SZ value from BOTH registry views.

    The Setup.exe is a 32-bit NSIS binary, so its HKLM writes are
    redirected to the WOW64 32-bit view when it runs on x64 Windows.
    A 64-bit Python reads the native view by default and would report
    the keys as missing on a perfectly good install. Try native first,
    then the 32-bit view; first hit wins.
    """
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
    """True if the key exists in EITHER registry view."""
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


HKEY_LOCAL_MACHINE = 0x80000002  # winreg.HKEY_LOCAL_MACHINE (import-free)


def run_installer(setup: Path, log_dir: Path) -> None:
    """Run the installer silently and wait for it to finish.

    NSIS /S is silent; /NCRC skips the (offline-hostile) CRC prompt
    toggle; /D= overrides the install dir to the default Program Files
    location the script verifies. /D must be the LAST argument and
    must NOT be quoted, even when it contains spaces (NSIS parsing
    rule). Exit code 0 = success.
    """
    print(f"Installing silently: {setup}")
    # NSIS's /D switch must be the LAST argument and must NOT be quoted,
    # even when the path contains spaces (its own command-line parser,
    # not CommandLineToArgvW). subprocess would quote a list element
    # with spaces, so build the raw lpCommandLine string ourselves.
    # Found live: a quoted /D makes silent mode exit 2 in 0.2s.
    cmd = f'"{setup}" /S /NCRC /D={INSTALL_DIR}'
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 740:
            raise CheckFailure(
                "The installer requires elevation (RequestExecutionLevel "
                "admin). Run this script from an elevated shell (CI "
                "runners are already elevated)."
            ) from exc
        raise
    print(
        f"  installer exited {proc.returncode} after {time.time() - started:.1f}s"
    )
    (log_dir / "install_stdout.log").write_text(
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise CheckFailure(
            f"installer exited {proc.returncode} (see install_stdout.log)"
        )
    # NSIS copies can briefly outlive the process handle; poll for the
    # uninstaller appearing before declaring the install done.
    uninstaller = INSTALL_DIR / "Uninstall.exe"
    for _ in range(30):
        if uninstaller.exists():
            return
        time.sleep(0.5)
    raise CheckFailure(f"installer finished but {uninstaller} never appeared")


def verify_installed_files() -> None:
    print("Verifying installed files in Program Files:")
    check(INSTALL_DIR.is_dir(), f"install dir exists: {INSTALL_DIR}")
    for name in REQUIRED_FILES:
        path = INSTALL_DIR / name
        check(path.is_file(), f"file present: {name}")
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


def verify_version_resource(setup: Path, version: str | None) -> None:
    print("Verifying the Setup.exe version resource:")
    size = ctypes.create_unicode_buffer(520)
    handle = ctypes.windll.version.GetFileVersionInfoSizeW(str(setup), None)
    check(handle > 0, "Setup.exe carries a version resource")
    data = ctypes.create_string_buffer(handle)
    ok = ctypes.windll.version.GetFileVersionInfoW(str(setup), 0, handle, data)
    check(bool(ok), "version resource readable")
    value = ctypes.c_void_p()
    length = ctypes.c_uint()
    ok = ctypes.windll.version.VerQueryValueW(
        data, "\\", ctypes.byref(value), ctypes.byref(length)
    )
    check(bool(ok) and length.value >= 268, "VS_FIXEDFILEINFO present")

    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [
            ("dwSignature", ctypes.c_uint),
            ("dwStrucVersion", ctypes.c_uint),
            ("dwFileVersionMS", ctypes.c_uint),
            ("dwFileVersionLS", ctypes.c_uint),
            ("dwProductVersionMS", ctypes.c_uint),
            ("dwProductVersionLS", ctypes.c_uint),
            ("dwFileFlagsMask", ctypes.c_uint),
            ("dwFileFlags", ctypes.c_uint),
            ("dwFileOS", ctypes.c_uint),
            ("dwFileType", ctypes.c_uint),
            ("dwFileSubtype", ctypes.c_uint),
            ("dwFileDateMS", ctypes.c_uint),
            ("dwFileDateLS", ctypes.c_uint),
        ]

    info = ctypes.cast(value, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    ms, ls = info.dwProductVersionMS, info.dwProductVersionLS
    res_version = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    check(
        res_version.startswith("1.3."),
        f"ProductVersion = {res_version} (4 segments, NSIS-valid shape)",
    )
    if version is not None:
        expected = f"{version}.0"
        check(res_version == expected, f"ProductVersion {res_version} == {expected}")


def verify_start_menu() -> None:
    print("Verifying Start Menu shortcuts:")
    for name in REQUIRED_SHORTCUTS:
        check((START_MENU / name).is_file(), f"shortcut present: {name}")


def run_uninstaller(log_dir: Path) -> None:
    print("Uninstalling silently:")
    uninstaller = INSTALL_DIR / "Uninstall.exe"
    # Run the uninstaller exactly like Add/Remove Programs does: no
    # _?= parameter. NSIS copies itself to temp and the copy deletes
    # everything — including the original Uninstall.exe. Found live:
    # passing _?= tells NSIS "you ARE the temp copy", so a running exe
    # tries to delete itself, fails silently, and Uninstall.exe (and
    # thus the install dir) survives uninstall.
    try:
        proc = subprocess.run(
            f'"{uninstaller}" /S',
            capture_output=True, text=True, timeout=300,
        )
    except OSError as exc:
        if getattr(exc, "winerror", None) == 740:
            raise CheckFailure(
                "The uninstaller also requires elevation; run this script "
                "from an elevated shell."
            ) from exc
        raise
    print(f"  uninstaller exited {proc.returncode}")
    (log_dir / "uninstall_stdout.log").write_text(
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
        encoding="utf-8",
    )
    # The uninstaller returns immediately (the temp copy does the work);
    # poll for the artifacts to disappear.
    deadline = time.time() + 120
    while time.time() < deadline:
        if not (INSTALL_DIR / "SpeechCraft_Studio.exe").exists():
            break
        time.sleep(1.0)
    check(
        not INSTALL_DIR.exists(),
        f"install dir removed: {INSTALL_DIR}",
    )
    check(
        not reg_key_exists(HKEY_LOCAL_MACHINE, UNINSTALL_KEY),
        "Add/Remove Programs key removed (both registry views)",
    )
    check(
        not reg_key_exists(HKEY_LOCAL_MACHINE, APP_KEY),
        "InstallDir key removed (both registry views)",
    )
    check(
        not START_MENU.exists(),
        "Start Menu folder removed",
    )
    feature_assets = (
        Path(os.environ.get("APPDATA", "")) / "SpeechCraft" / "feature_assets"
    )
    check(
        not feature_assets.exists(),
        "downloaded feature assets removed (%APPDATA%\SpeechCraft\feature_assets)",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--setup", required=True, type=Path, help="Path to the Setup.exe")
    parser.add_argument("--version", default=None, help="Expected version (e.g. 1.3.7)")
    parser.add_argument(
        "--keep", action="store_true",
        help="Install but skip uninstall verification (debugging).",
    )
    parser.add_argument(
        "--log-dir", type=Path, default=None,
        help="Where to write installer logs (default: build/installer-smoke).",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        print("This smoke test runs on Windows only.")
        return 1
    setup = args.setup.resolve()
    if not setup.is_file():
        print(f"Setup.exe not found: {setup}")
        return 1
    log_dir = args.log_dir or Path("build") / "installer-smoke"
    log_dir.mkdir(parents=True, exist_ok=True)

    try:
        run_installer(setup, log_dir)
        verify_installed_files()
        verify_registry(args.version)
        verify_version_resource(setup, args.version)
        verify_start_menu()
        if not args.keep:
            run_uninstaller(log_dir)
        else:
            print("Keeping the install (--keep).")
    except CheckFailure as exc:
        print(f"\nSMOKE FAILED: {exc}")
        return 1
    except subprocess.TimeoutExpired:
        print("\nSMOKE FAILED: installer/uninstaller timed out")
        return 1
    print("\nINSTALLER SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
