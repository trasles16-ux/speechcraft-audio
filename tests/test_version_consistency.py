"""Guard: the app version is defined once and propagated everywhere.

v1.3.6 shipped with five hand-maintained version strings, and the NSIS
one was invalid (5 segments — makensis requires exactly 4). These
pure-logic tests fail the build when the sources drift apart again.
No wx needed; runs on Linux CI.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_audio_editor_defines_version() -> None:
    source = _read("audio_editor.py")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', source, re.MULTILINE)
    assert match, "audio_editor.py must define __version__ at module top"
    version = match.group(1)
    # x.y.z — build_all.py passes this to NSIS as /DAPP_VERSION, and the
    # .nsi appends ".0" for VIProductVersion's 4-segment requirement.
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"__version__ {version!r} must be three numeric segments (x.y.z)"
    )


def test_nsi_uses_version_define_not_a_literal() -> None:
    """The installer's VIProductVersion must derive from /DAPP_VERSION.

    A hardcoded literal here is how v1.3.6 shipped "1.3.6.2.0" (five
    segments) — makensis requires exactly four. Deriving it from the
    define makes that class of bug impossible.
    """
    nsi = _read("installer", "speechcraft_setup.nsi")
    vi_lines = [
        line.strip() for line in nsi.splitlines()
        if line.strip().startswith("VIProductVersion")
    ]
    assert len(vi_lines) == 1, "expected exactly one VIProductVersion"
    assert vi_lines[0] == 'VIProductVersion "${APP_VERSION}.0"', (
        f"VIProductVersion must be derived from APP_VERSION, got {vi_lines[0]!r}"
    )
    # And no hardcoded dotted version literal anywhere in the script.
    assert not re.search(r'VIProductVersion "\d+\.\d+', nsi)
    assert not re.search(r'DisplayVersion" "\d+\.\d+', nsi)


def test_build_all_passes_version_and_out_dir() -> None:
    build_all = _read("build_all.py")
    assert "/DAPP_VERSION=" in build_all
    assert "/DOUT_DIR=" in build_all
    assert "/DSTAGING=" in build_all
    # No machine-specific absolute output paths.
    assert "C:/Users" not in build_all


def test_workflows_reference_real_installer_script() -> None:
    for wf in ("build.yml", "release.yml"):
        text = _read(".github", "workflows", wf)
        assert "speechcraft_setup.nsi" in text, f"{wf} must compile the real installer script"
        assert "speech_setup.nsi" not in text
        if wf == "release.yml":
            assert "/DAPP_VERSION=" in text


def test_download_destination_is_unified() -> None:
    """Single download root: PREFS_DIR/feature_assets, read by wizard,
    lazy-install, and the Piper engine alike."""
    import sys
    sys.path.insert(0, str(ROOT))
    import feature_manager

    assert feature_manager.ASSETS_ROOT == (
        feature_manager.DEFAULT_STATE_FILE.parent / "feature_assets"
    )
    # The Piper engine reads the same root.
    engine_source = _read("piper_tts_engine.py")
    assert "feature_manager.ASSETS_ROOT" in engine_source
    # lazy_install no longer downloads into the CWD.
    lazy_source = _read("dialogs", "lazy_install.py")
    assert "dest_dir=" not in lazy_source


def test_wizard_uses_asset_state_file_not_prefs() -> None:
    """Regression guard for the v1.3.6 bug: the wizard handed setup.json
    to the Download page as its asset-state file, so the wizard's
    'what's installed' view disagreed with every engine."""
    wizard_source = _read("setup_wizard.py")
    assert 'with_name("feature_state.json")' in wizard_source
    assert "state_file=self._prefs_file,\n        )" not in wizard_source


def test_installer_smoke_wired_into_workflows() -> None:
    """The silent-install smoke gate must run on every push/PR build
    AND before a release's artifacts are attached."""
    for wf in ("build.yml", "release.yml"):
        text = _read(".github", "workflows", wf)
        assert "installer_smoke.py" in text, f"{wf} must run the installer smoke test"
        assert "--version $version" in text, f"{wf} must pass the expected version"
        assert "Upload smoke logs on failure" in text, (
            f"{wf} must upload smoke logs when the gate fails"
        )
    # The release workflow must smoke-test BEFORE attaching artifacts.
    release = _read(".github", "workflows", "release.yml")
    assert release.index("Installer smoke test") < release.index("name: Checksums")


def test_installer_smoke_registry_keys_match_nsi() -> None:
    """The smoke test verifies exactly the registry keys the installer
    writes — a key renamed in one place must fail the other's checks."""
    nsi = _read("installer", "speechcraft_setup.nsi")
    smoke = _read("scripts", "installer_smoke.py")
    for key in (
        "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SpeechCraft Studio",
        "Software\\SpeechCraft\\Studio",
    ):
        assert key in nsi, f"key missing from installer script: {key}"
        assert key in smoke, f"key missing from smoke test: {key}"
