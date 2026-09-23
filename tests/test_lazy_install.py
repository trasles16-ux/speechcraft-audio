"""Tests for ``dialogs.lazy_install``.

The lazy-install flow glues together :func:`feature_manager.ensure_ready`
and the wx ``DownloadProgressDialog``. Tests stub the dialog so we
don't need a real display, and stub ``ensure_ready`` so we don't need
the network.

The flow under test:

- Asset is ready → ``prompt_and_install`` returns True without
  showing any dialog (the "no UI when already on disk" guarantee).
- Asset is missing + user says No → returns False, no download.
- Asset is missing + user says Yes + download succeeds → returns True.
- Asset is missing + user says Yes + download fails → returns False
  and the user sees a "Download failed" message box.

Pure logic tests for the size formatter live alongside.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_format_size_bytes():
    from dialogs.lazy_install import _format_size

    assert _format_size(0) == ""
    assert _format_size(1) == "~0 KB"  # tiny values
    assert _format_size(1024) == "~1 KB"
    assert _format_size(60 * 1024 * 1024) == "~60 MB"
    assert _format_size(1024 * 1024 * 1024) == "~1024 MB"


def test_extract_from_zip_literal_entry(tmp_path):
    """_extract_from_zip finds the entry by its literal name."""
    import feature_manager

    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("piper/piper.exe", b"FAKE-ONNX-CONTENT")

    out = feature_manager._extract_from_zip(
        str(zip_path),
        entry_name="piper/piper.exe",
        out_dir=tmp_path / "out",
    )
    assert out.exists()
    assert out.name == "piper.exe"
    assert out.read_bytes() == b"FAKE-ONNX-CONTENT"


def test_extract_from_zip_basename_fallback(tmp_path):
    """If literal entry isn't found, fall back to basename match."""
    import feature_manager

    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("piper/piper.exe", b"BIN")

    out = feature_manager._extract_from_zip(
        str(zip_path),
        entry_name="piper.exe",  # short form, no "piper/" prefix
        out_dir=tmp_path / "out",
    )
    assert out.exists()
    assert out.name == "piper.exe"


def test_extract_from_zip_missing_entry_raises(tmp_path):
    import feature_manager

    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("something/else.txt", b"x")

    with pytest.raises(OSError, match="not found in zip"):
        feature_manager._extract_from_zip(
            str(zip_path),
            entry_name="piper/piper.exe",
            out_dir=tmp_path / "out",
        )


# --- Integration: lazy_install with mocked dialogs ----------------------------


def test_prompt_and_install_returns_true_when_already_ready(tmp_path, monkeypatch):
    """If the asset is on disk, no dialog is shown and we return True."""
    import feature_manager
    from dialogs.lazy_install import prompt_and_install

    # Mark the asset as ready without actually touching the disk.
    monkeypatch.setattr(
        feature_manager, "is_ready",
        lambda *a, **kw: True,
    )

    with patch("dialogs.lazy_install.wx.MessageDialog") as md:
        result = prompt_and_install(
            "piper_tts", "en_GB.cori",
            parent=None,
            state_file=tmp_path / "feature_state.json",
        )

    assert result is True
    md.assert_not_called()


def test_prompt_and_install_user_says_no(monkeypatch, tmp_path):
    """If the user dismisses the prompt, return False without downloading."""
    import feature_manager
    from dialogs.lazy_install import prompt_and_install

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **kw: False)

    with patch("dialogs.lazy_install.wx.MessageDialog") as md:
        # Simulate the user clicking "No".
        md.return_value.ShowModal.return_value = wx.ID_NO
        result = prompt_and_install("piper_tts", "en_GB.cori")

    assert result is False
    md.assert_called_once()


def test_prompt_and_install_user_says_yes_and_download_succeeds(monkeypatch, tmp_path):
    """Yes → ensure_ready → True. The progress dialog appears and closes."""
    import feature_manager
    from dialogs.lazy_install import prompt_and_install

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **kw: False)
    monkeypatch.setattr(
        feature_manager, "ensure_ready",
        lambda *a, **kw: True,  # pretend the download succeeded
    )

    # Stub the progress dialog so we don't need a real wx display loop.
    class _FakeDlg:
        def __init__(self, *a, **kw):
            pass

        def ShowModal(self):
            return wx.ID_OK

        def Destroy(self):
            pass

        def is_cancelled(self):
            return False

        def update(self, *a, **kw):
            pass

        def EndModal(self, *a, **kw):
            pass

    with patch("dialogs.lazy_install.wx.MessageDialog") as md:
        md.return_value.ShowModal.return_value = wx.ID_YES
        with patch("dialogs.download_progress_dialog.DownloadProgressDialog", _FakeDlg):
            result = prompt_and_install("piper_tts", "en_GB.cori")

    assert result is True


def test_prompt_and_install_user_says_yes_but_download_fails(monkeypatch):
    """Yes → ensure_ready raises → False + error dialog."""
    import feature_manager
    from dialogs.lazy_install import prompt_and_install

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **kw: False)

    def _raise(*a, **kw):
        raise feature_manager.FeatureDownloadError(
            "piper_tts/en_GB.cori", "Could not reach Hugging Face"
        )

    monkeypatch.setattr(feature_manager, "ensure_ready", _raise)

    class _FakeDlg:
        def __init__(self, *a, **kw):
            pass

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass

        def is_cancelled(self):
            return True  # user cancelled mid-download

        def update(self, *a, **kw):
            pass

        def EndModal(self, *a, **kw):
            pass

    with patch("dialogs.lazy_install.wx.MessageDialog") as md_prompt, \
         patch("dialogs.lazy_install.wx.MessageBox") as md_err:
        md_prompt.return_value.ShowModal.return_value = wx.ID_YES
        with patch("dialogs.download_progress_dialog.DownloadProgressDialog", _FakeDlg):
            result = prompt_and_install("piper_tts", "en_GB.cori")

    assert result is False
    # The user sees a "Download failed" MessageBox.
    md_err.assert_called_once()
    args, _ = md_err.call_args
    assert "Could not download" in args[0]
    assert "Could not reach Hugging Face" in args[0]


# wx import for the ID_* constants used in mocks.
import wx  # noqa: E402  — late import; tests run on Windows where wx is installed
