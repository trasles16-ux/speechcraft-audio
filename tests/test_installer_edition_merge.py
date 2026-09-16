"""Regression tests for the installer edition sidecar merge.

The NSIS installer drops %APPDATA%\\SpeechCraft\\PreferredBundle.txt
("Core" or "Full") at install time. On first launch, run_speechcraft.py
merges it into setup.json as preferred_bundle via
prefs.merge_installer_edition() and deletes the sidecar.

Pure-logic tests — no wx, no installer, just the prefs module.
"""
from __future__ import annotations

from pathlib import Path

from prefs import merge_installer_edition, load_prefs, PREFS_DIR


def test_merge_installer_edition_writes_preferred_bundle(tmp_path: Path) -> None:
    prefs_file = tmp_path / "setup.json"
    sidecar = tmp_path / "PreferredBundle.txt"
    sidecar.write_text("Full", encoding="utf-8")

    merge_installer_edition(prefs_file=prefs_file, sidecar=sidecar)

    prefs = load_prefs(prefs_file=prefs_file)
    assert prefs.get("preferred_bundle") == "Full"
    # Sidecar consumed
    assert not sidecar.exists()


def test_merge_installer_edition_core(tmp_path: Path) -> None:
    prefs_file = tmp_path / "setup.json"
    sidecar = tmp_path / "PreferredBundle.txt"
    sidecar.write_text("Core", encoding="utf-8")

    merge_installer_edition(prefs_file=prefs_file, sidecar=sidecar)

    prefs = load_prefs(prefs_file=prefs_file)
    assert prefs.get("preferred_bundle") == "Core"
    assert not sidecar.exists()


def test_merge_installer_edition_no_sidecar_is_noop(tmp_path: Path) -> None:
    prefs_file = tmp_path / "setup.json"
    prefs_file.write_text("{}")

    # No sidecar file at all — must not raise, must not create keys
    merge_installer_edition(prefs_file=prefs_file, sidecar=tmp_path / "nope.txt")

    prefs = load_prefs(prefs_file=prefs_file)
    assert "preferred_bundle" not in prefs


def test_merge_installer_edition_preserves_other_keys(tmp_path: Path) -> None:
    prefs_file = tmp_path / "setup.json"
    prefs_file.write_text('{"auto_check_updates": false, "features": {"piper_tts": true}}')
    sidecar = tmp_path / "PreferredBundle.txt"
    sidecar.write_text("Core", encoding="utf-8")

    merge_installer_edition(prefs_file=prefs_file, sidecar=sidecar)

    prefs = load_prefs(prefs_file=prefs_file)
    assert prefs.get("preferred_bundle") == "Core"
    # Unrelated keys survive the merge
    assert prefs.get("auto_check_updates") is False
    assert prefs.get("features") == {"piper_tts": True}


def test_merge_installer_edition_unknown_content_ignored(tmp_path: Path) -> None:
    prefs_file = tmp_path / "setup.json"
    sidecar = tmp_path / "PreferredBundle.txt"
    sidecar.write_text("Bogus", encoding="utf-8")

    merge_installer_edition(prefs_file=prefs_file, sidecar=sidecar)

    prefs = load_prefs(prefs_file=prefs_file)
    assert "preferred_bundle" not in prefs
    # Invalid content: sidecar kept for inspection rather than consumed
    assert sidecar.exists()


def test_sidecar_path_is_in_prefs_dir() -> None:
    from prefs import PREFERRED_BUNDLE_SIDECAR

    assert PREFERRED_BUNDLE_SIDECAR.parent == PREFS_DIR
    assert PREFERRED_BUNDLE_SIDECAR.name == "PreferredBundle.txt"
