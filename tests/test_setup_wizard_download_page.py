"""Smoke tests for the wizard DownloadPage (needs wx)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

needs_wx = pytest.mark.skipif(
    sys.platform == "linux",
    reason="wx not available on Linux CI",
)


@needs_wx
def test_download_page_constructs(wx_app, tmp_path: Path) -> None:
    import wx

    from feature_flags import FeatureFlags
    from setup_wizard_pages import DownloadPage

    parent = wx.Frame(None)
    page = DownloadPage(
        parent,
        flags=FeatureFlags(),
        state_file=tmp_path / "state.json",
    )
    assert page is not None
    assert page.GetName() == "Download ready"
    parent.Destroy()


@needs_wx
def test_download_page_shows_rows_for_missing_assets(wx_app, tmp_path: Path) -> None:
    import wx

    from feature_flags import FeatureFlags
    from setup_wizard_pages import DownloadPage

    parent = wx.Frame(None)
    # All features on, no state file → every asset is missing
    page = DownloadPage(
        parent,
        flags=FeatureFlags(),
        state_file=tmp_path / "state.json",
    )
    # tiny.en + cori + alan = 3 rows
    assert page.get_row_count() == 3
    parent.Destroy()


@needs_wx
def test_download_page_no_rows_when_all_ready(
    wx_app, tmp_path: Path
) -> None:
    import json
    import wx

    from feature_flags import FeatureFlags
    from setup_wizard_pages import DownloadPage

    parent = wx.Frame(None)
    # Seed a state file where every asset is ready + on disk
    asset_dir = tmp_path / "models"
    sf = tmp_path / "state.json"
    state = {}
    for feature, asset, files in [
        ("local_transcription", "tiny.en",
         ["model.bin", "tokenizer.json", "vocabulary.txt", "config.json"]),
        ("piper_tts", "en_GB.cori", ["model", "config"]),
        ("piper_tts", "en_GB.alan", ["model", "config"]),
    ]:
        d = asset_dir / feature / asset
        d.mkdir(parents=True)
        paths = {}
        for f in files:
            p = d / f
            p.write_bytes(b"x")
            paths[f] = str(p)
        state[f"{feature}/{asset}"] = {
            "ready": True,
            "paths": paths,
            "downloaded_at": "2026-09-14T00:00:00Z",
            "last_error": None,
        }
    sf.write_text(json.dumps(state), encoding="utf-8")

    page = DownloadPage(
        parent,
        flags=FeatureFlags(),
        state_file=sf,
    )
    # Every asset ready → zero rows
    assert page.get_row_count() == 0
    parent.Destroy()


@needs_wx
def test_download_page_all_controls_have_set_name(wx_app, tmp_path: Path) -> None:
    import wx

    from feature_flags import FeatureFlags
    from setup_wizard_pages import DownloadPage

    parent = wx.Frame(None)
    page = DownloadPage(
        parent,
        flags=FeatureFlags(),
        state_file=tmp_path / "state.json",
    )
    # The page itself must have a name for NVDA
    assert page.GetName() == "Download ready"
    # Spot-check one row's controls all have names
    row = page._rows[0]
    assert row["gauge"].GetName() != ""
    assert row["status"].GetName() != ""
    assert row["button"].GetName() != ""
    parent.Destroy()


@needs_wx
def test_download_page_disabled_feature_has_no_rows(wx_app, tmp_path: Path) -> None:
    import wx

    from feature_flags import FeatureFlags
    from setup_wizard_pages import DownloadPage

    parent = wx.Frame(None)
    # Everything off except local_transcription
    flags = FeatureFlags(
        basic_editing=True,
        pedalboard_effects=False,
        local_transcription=True,
        cloud_transcription=False,
        destructive_editing=False,
        line_placing=False,
        edge_tts=False,
        piper_tts=False,
    )
    page = DownloadPage(
        parent,
        flags=flags,
        state_file=tmp_path / "state.json",
    )
    # Only tiny.en should be offered (piper disabled)
    assert page.get_row_count() == 1
    parent.Destroy()
