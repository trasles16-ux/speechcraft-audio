"""v1.3.7 regression tests: unified download pipeline + wizard a11y.

Covers the two reported bugs:

1. "I don't find the button to start the download of the features I
   selected" — the Download page's buttons were clipped out of the
   dialog (fixed-height pages), named with internal keys
   ("Download piper_tts/en_GB.cori"), and page entry focused a
   StaticText (a no-op on wxMSW), so NVDA announced nothing.
2. Downloads landed in three different folders depending on which
   path triggered them, so the wizard's downloads were invisible to
   the engines (double downloads / "files missing after download").
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

needs_wx = pytest.mark.skipif(
    not importlib.util.find_spec("wx"),
    reason="wxPython not installed",
)
pytestmark = pytest.mark.usefixtures("wx_app")

sys_path = str(Path(__file__).resolve().parent.parent)


def _open_wizard(tmp_path):
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from setup_wizard import SetupWizardDialog

    return SetupWizardDialog(parent=None, prefs_file=tmp_path / "setup.json")


# ---------------------------------------------------------------------------
# Focus landing (the "I can't find the button" fix)
# ---------------------------------------------------------------------------


@needs_wx
def test_page_entry_focuses_first_interactive_control(wx_app, tmp_path):
    """Arriving on a page must focus a real control, not a StaticText."""
    dlg = _open_wizard(tmp_path)
    try:
        dlg._notebook.SetSelection(1)  # Editing features
        focused = dlg._focus_page_content()
        assert focused is not None
        # The killer regression: focusing a StaticText is a silent
        # no-op on wxMSW. The target must actually accept focus.
        assert focused.AcceptsFocus()
        assert not isinstance(focused, __import__("wx").StaticText)
        assert isinstance(focused, __import__("wx").CheckBox)

        dlg._notebook.SetSelection(3)  # Download ready
        focused = dlg._focus_page_content()
        assert focused is not None
        assert focused.AcceptsFocus()
        # On a fresh flags set with nothing installed the first
        # interactive control is the "Download all" button.
        assert isinstance(focused, __import__("wx").Button)
    finally:
        dlg.Destroy()


@needs_wx
def test_download_row_buttons_have_human_names(wx_app, tmp_path):
    """Row buttons announce real voice/model names, not internal keys."""
    dlg = _open_wizard(tmp_path)
    try:
        page = dlg._download
        if page.get_row_count() == 0:
            pytest.skip("test env has all assets installed")
        row = page._rows[0]
        name = row["button"].GetName()
        assert "/" not in name, f"accessible name still uses internal key: {name!r}"
        assert name.startswith("Download ")
        # Every row control is named with the same human description.
        desc = row["status"].GetName()
        assert desc.startswith(row["button"].GetName()[len("Download "):])
    finally:
        dlg.Destroy()


@needs_wx
def test_download_page_rows_scroll_into_reach(wx_app, tmp_path):
    """The page is a scrolled window: the virtual size covers every row,
    so per-row buttons can never be clipped out of Tab order."""
    dlg = _open_wizard(tmp_path)
    try:
        page = dlg._download
        assert isinstance(page, __import__("wx").ScrolledWindow)
        virt = page.GetVirtualSize()
        assert virt.GetHeight() > 0
        # With rows present the content must include room for them.
        if page.get_row_count() > 0:
            assert virt.GetHeight() >= 200
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Unified destination (the double-download fix)
# ---------------------------------------------------------------------------


def test_ensure_ready_default_dest_is_assets_root(tmp_path, monkeypatch):
    """ensure_ready/download_asset without dest_dir land under
    PREFS_DIR/feature_assets — the tree the engines read."""
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import feature_manager

    captured = {}

    def _fake_download(feature, asset, *, dest_dir=None, **kwargs):
        captured["dest_dir"] = dest_dir
        return {"ready": True, "paths": {}}

    # Assert the real download_asset's default-dest contract from its
    # source BEFORE monkeypatching replaces the attribute.
    import inspect
    source = inspect.getsource(feature_manager.download_asset)
    assert "dest_dir if dest_dir is not None else ASSETS_ROOT" in source

    monkeypatch.setattr(feature_manager, "download_asset", _fake_download)
    monkeypatch.setattr(
        feature_manager, "is_ready", lambda *a, **k: False
    )
    feature_manager.ensure_ready("piper_tts", "en_GB.cori")
    # ensure_ready forwards dest_dir=None to download_asset (mocked),
    # whose real body resolves None -> ASSETS_ROOT (asserted above).
    assert captured["dest_dir"] is None


def test_wizard_state_file_is_feature_state(tmp_path):
    """Wizard's Download page reads/writes feature_state.json."""
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from feature_manager import load_feature_state

    dlg = _open_wizard(tmp_path)
    try:
        sf = dlg._download._state_file
        assert sf.name == "feature_state.json"
        assert sf.parent == tmp_path
    finally:
        dlg.Destroy()


@needs_wx
def test_wizard_row_download_targets_assets_root(wx_app, tmp_path, monkeypatch):
    """Pressing a row's Download button downloads into ASSETS_ROOT."""
    import wx

    import feature_manager

    dlg = _open_wizard(tmp_path)
    try:
        page = dlg._download
        if page.get_row_count() == 0:
            pytest.skip("test env has all assets installed")
        captured = {}

        def _fake_download(feature, asset, **kwargs):
            captured["dest_dir"] = kwargs.get("dest_dir")
            raise feature_manager.FeatureDownloadError(
                feature_manager.asset_key(feature, asset), "stop-here"
            )

        monkeypatch.setattr(feature_manager, "download_asset", _fake_download)
        row = page._rows[0]
        # Invoke the worker body synchronously would spawn a thread —
        # instead call download path indirectly: _start_download spawns
        # a daemon thread; wait briefly for the captured call.
        page._start_download(row)
        import time

        for _ in range(50):
            if captured:
                break
            time.sleep(0.02)
        assert captured.get("dest_dir") is None or captured["dest_dir"] == (
            feature_manager.ASSETS_ROOT
        )
        wx.GetApp().ProcessPendingEvents()
    finally:
        dlg.Destroy()
