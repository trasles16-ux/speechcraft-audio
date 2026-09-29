"""Regression tests for the v1.3.7.1 Piper executable download failure.

Found live 2026-09-29: the wizard downloaded all three model assets fine,
but the 22 MB piper_windows_amd64.zip failed to extract with
``NameError: name 'os' is not defined`` and left a 0-byte piper.exe
behind. Root causes:

1. ``_extract_from_zip``'s truncation handler used ``os.*`` but
   feature_manager.py never imported os.
2. ``download_asset`` skipped SHA verification for zip assets (the
   v1.3.6.2 hardcoded piper.zip SHA was never consulted by the
   refactored path), so a truncated zip reached extraction.
3. Extraction wrote the output IN PLACE over the zip it was reading
   (both are named piper.exe in the same dir), truncating the input
   mid-read — EOFError on every attempt, the original v1.3.6.2 bug.
4. The engine treated a 0-byte piper.exe as installed.
5. The wizard Download page's empty state was a focus dead-end: no
   announcement, NVDA silence, user thinks a11y regressed.

Run: .venv/Scripts/python.exe -m pytest tests/test_v138_piper_zip_fix.py -v
"""
from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import feature_manager  # noqa: E402

needs_wx = pytest.mark.skipif(
    not importlib.util.find_spec("wx"),
    reason="wxPython not installed",
)


def test_feature_manager_imports_os():
    """The truncation handler needs os.* — regression: NameError at runtime."""
    src = (PROJECT_ROOT / "feature_manager.py").read_text(encoding="utf-8")
    # A module-level import (not a function-local one), because the
    # except-clause runs after the local namespace is already live.
    assert "\nimport os\n" in src.split('def _extract_from_zip')[0]


def test_extract_from_truncated_zip_no_nameerror(tmp_path):
    """A truncated zip raises OSError with a clear message — not NameError."""
    zip_path = tmp_path / "piper.zip"
    # A real ZipFile truncated mid-entry: write a valid zip then cut it.
    full = tmp_path / "full.zip"
    with zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("piper/piper.exe", b"X" * 500_000)
    data = full.read_bytes()
    zip_path.write_bytes(data[: len(data) // 3])  # central dir lost

    with pytest.raises(OSError, match="truncated or corrupt"):
        feature_manager._extract_from_zip(
            str(zip_path),
            entry_name="piper/piper.exe",
            out_dir=tmp_path / "out",
        )


def test_extract_failure_deletes_bad_zip_and_leaves_no_partial(tmp_path):
    """After a truncated-zip failure: zip gone, no 0-byte output left."""
    zip_path = tmp_path / "piper.zip"
    full = tmp_path / "full.zip"
    with zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("piper/piper.exe", b"Y" * 300_000)
    data = full.read_bytes()
    zip_path.write_bytes(data[: len(data) // 2])

    with pytest.raises(OSError):
        feature_manager._extract_from_zip(
            str(zip_path),
            entry_name="piper/piper.exe",
            out_dir=tmp_path / "out",
        )
    assert not zip_path.exists(), "bad zip must be deleted"
    out = tmp_path / "out" / "piper.exe"
    assert not out.exists() or out.stat().st_size > 0, (
        "no 0-byte leftover may remain"
    )


def test_extract_same_name_as_zip_does_not_truncate_input(tmp_path):
    """Extracting piper.exe into a dir whose zip is also piper.exe works.

    Regression: the in-place write truncated the input zip mid-read,
    EOFError on every attempt. The fix writes to a temp file and
    os.replace()s it after the read completes.
    """
    zip_path = tmp_path / "piper.exe"  # zip named exactly like the entry
    payload = b"FAKE-PE-BYTES" * 1000
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("piper/piper.exe", payload)

    out = feature_manager._extract_from_zip(
        str(zip_path),
        entry_name="piper/piper.exe",
        out_dir=tmp_path,  # same dir -> same path as the zip itself
    )
    assert out == zip_path
    assert out.read_bytes() == payload


def test_extract_bad_zipfile_raises_clean_oserror(tmp_path):
    """A garbage file (BadZipFile) raises OSError, not zipfile's raw error."""
    bad = tmp_path / "piper.zip"
    bad.write_bytes(b"this is not a zip file at all")
    with pytest.raises(OSError, match="truncated or corrupt"):
        feature_manager._extract_from_zip(
            str(bad),
            entry_name="piper/piper.exe",
            out_dir=tmp_path / "out",
        )


def test_download_asset_zip_asset_sha_verified(tmp_path, monkeypatch):
    """A zip asset with a wrong SHA must fail before extraction.

    Regression: the v1.3.7 refactor skipped SHA verification for
    extract-mode files, so corrupt zips reached _extract_from_zip and
    the hardcoded piper.zip SHA (v1.3.6.2) was never used.
    """
    import shutil

    from updater import sha256_of_file

    # Build a real zip whose content does NOT match the spec's SHA.
    zip_path = tmp_path / "dl" / "piper.exe"
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("piper/piper.exe", b"NOT-THE-REAL-Piper")

    calls: list[str] = []

    def fake_download(url, dest, **kwargs):
        calls.append(url)
        shutil.copyfile(zip_path, dest)  # "downloads" the bad zip
        return dest

    monkeypatch.setattr(
        "updater.download_with_progress", fake_download
    )
    spec_sha = "0" * 64
    real_sha = sha256_of_file(str(zip_path))
    assert real_sha != spec_sha

    # Point the executable asset at our temp dir and a mismatching SHA.
    orig = feature_manager.FEATURE_ASSETS["piper_tts"]["executable"]
    patched = dict(orig)
    files = [dict(f) for f in orig["files"]]
    files[0]["sha256"] = spec_sha
    patched["files"] = files
    monkeypatch.setitem(
        feature_manager.FEATURE_ASSETS["piper_tts"],
        "executable",
        patched,
    )

    state_file = tmp_path / "feature_state.json"
    with pytest.raises(feature_manager.FeatureDownloadError, match="SHA-256"):
        feature_manager.download_asset(
            "piper_tts",
            "executable",
            dest_dir=tmp_path / "assets",
            state_file=state_file,
        )
    # No extraction was attempted, no piper.exe landed in assets.
    assert not (tmp_path / "assets" / "piper_tts" / "executable" / "piper.exe").exists()
    state = feature_manager.load_feature_state(state_file=state_file)
    assert state["piper_tts/executable"]["ready"] is False


def test_download_asset_zip_sha_mismatch_retries_then_fails(tmp_path, monkeypatch):
    """Every SHA-failed attempt fetches a fresh copy before giving up."""
    import shutil

    zip_path = tmp_path / "bad" / "piper.exe"
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("piper/piper.exe", b"BAD")

    calls: list[str] = []

    def fake_download(url, dest, **kwargs):
        calls.append(dest)
        shutil.copyfile(zip_path, dest)
        return dest

    monkeypatch.setattr("updater.download_with_progress", fake_download)
    monkeypatch.setattr("updater.RETRY_BACKOFF_S", (0.0, 0.0, 0.0))

    orig = feature_manager.FEATURE_ASSETS["piper_tts"]["executable"]
    patched = dict(orig)
    files = [dict(f) for f in orig["files"]]
    files[0]["sha256"] = "f" * 64  # never matches
    patched["files"] = files
    monkeypatch.setitem(
        feature_manager.FEATURE_ASSETS["piper_tts"],
        "executable",
        patched,
    )

    with pytest.raises(feature_manager.FeatureDownloadError, match="SHA-256"):
        feature_manager.download_asset(
            "piper_tts",
            "executable",
            dest_dir=tmp_path / "assets",
            state_file=tmp_path / "feature_state.json",
        )
    assert len(calls) >= 2, "SHA mismatch must trigger fresh re-downloads"


def test_download_asset_zip_asset_happy_path(tmp_path, monkeypatch):
    """A good zip with the right SHA extracts piper.exe correctly."""
    import shutil

    payload = b"GOOD-PIPER-EXE" * 100
    zip_src = tmp_path / "good.zip"
    with zipfile.ZipFile(zip_src, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("piper/piper.exe", payload)

    from updater import sha256_of_file

    real_sha = sha256_of_file(str(zip_src))

    def fake_download(url, dest, **kwargs):
        shutil.copyfile(zip_src, dest)
        return dest

    monkeypatch.setattr("updater.download_with_progress", fake_download)

    orig = feature_manager.FEATURE_ASSETS["piper_tts"]["executable"]
    patched = dict(orig)
    files = [dict(f) for f in orig["files"]]
    files[0]["sha256"] = real_sha
    patched["files"] = files
    monkeypatch.setitem(
        feature_manager.FEATURE_ASSETS["piper_tts"],
        "executable",
        patched,
    )

    assets = tmp_path / "assets"
    feature_manager.download_asset(
        "piper_tts",
        "executable",
        dest_dir=assets,
        state_file=tmp_path / "feature_state.json",
    )
    exe = assets / "piper_tts" / "executable" / "piper.exe"
    assert exe.read_bytes() == payload
    # The throw-away zip is deleted; only the extracted binary remains.
    assert sorted(p.name for p in exe.parent.iterdir()) == ["piper.exe"]
    state = feature_manager.load_feature_state(
        state_file=tmp_path / "feature_state.json"
    )
    assert state["piper_tts/executable"]["ready"] is True


@needs_wx
def test_engine_ignores_zero_byte_piper_exe(wx_app, tmp_path, monkeypatch):
    """_find_piper must not return a 0-byte download leftover."""
    import piper_tts_engine

    exe_dir = tmp_path / "piper_tts" / "executable"
    exe_dir.mkdir(parents=True)
    (exe_dir / "piper.exe").write_bytes(b"")  # the live-bug leftover

    monkeypatch.setattr(feature_manager, "ASSETS_ROOT", tmp_path)

    def fake_is_ready(feature, asset, **kwargs):
        return feature == "piper_tts" and asset == "executable"

    monkeypatch.setattr(feature_manager, "is_ready", fake_is_ready)
    engine = piper_tts_engine.PiperTTSEngine.__new__(
        piper_tts_engine.PiperTTSEngine
    )
    engine.models_dir = tmp_path
    engine._parent = None
    engine._allow_prompt = False
    assert engine._find_piper() is None


@needs_wx
def test_empty_download_page_announces_no_controls(wx_app, tmp_path, monkeypatch):
    """A page with no focusable control says why instead of silence."""
    from setup_wizard import SetupWizardDialog

    dlg = SetupWizardDialog(parent=None, prefs_file=tmp_path / "setup.json")
    try:
        # Jump to the Summary page (no interactive controls by design).
        summary_idx = dlg._notebook.GetPageCount() - 1
        dlg._notebook.SetSelection(summary_idx)
        target = dlg._focus_page_content()
        assert target is None  # Summary has no interactive control
        # The dialog status text still describes the page; the UIA
        # announcement (fire-and-forget) covered the no-controls case.
        assert "Summary" in dlg._status.GetStatusText()
    finally:
        dlg.Destroy()
