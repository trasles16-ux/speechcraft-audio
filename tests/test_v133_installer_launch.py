"""Regression tests for the installer-launch silent-failure fix.

Symptom (reported from Paul's machine): the auto-update download
succeeded, he clicked "Yes" at "Ready to install update", and then
nothing happened. Root cause: launch_installer() spawned the
installer EXE but never confirmed the spawn succeeded. In a remote
session the NSIS installer (RequestExecutionLevel admin) hits a UAC
prompt that cannot be shown, Popen raises OSError (WinError 740),
the exception escaped the caller's `except UpdateCheckError`, and
wx's event loop swallowed it — a completely silent failure.

These tests pin:
- launch_installer converts spawn-time OSError into UpdateCheckError
  with an actionable message (manual-run path)
- launch_installer catches an installer that exits immediately
- launch_installer returns the live Popen handle on success
"""
from __future__ import annotations

import unittest.mock as mock

import pytest


def _make_proc(poll_result: object) -> mock.Mock:
    p = mock.Mock()
    p.poll.return_value = poll_result
    return p


def test_launch_installer_converts_spawn_oserror() -> None:
    from updater import UpdateCheckError, launch_installer

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        path = f.name
    try:
        with mock.patch("updater.subprocess.Popen",
                        side_effect=OSError("WinError 740: The process "
                                            "cannot access the file")):
            with pytest.raises(UpdateCheckError) as exc_info:
                launch_installer(path)
        msg = str(exc_info.value)
        assert "Run as administrator" in msg or "remote session" in msg
        # The actionable manual path is surfaced
        assert path in msg
    finally:
        os.unlink(path)


def test_launch_installer_catches_immediate_exit() -> None:
    from updater import UpdateCheckError, launch_installer

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        path = f.name
    try:
        proc = _make_proc(poll_result=1)  # exited immediately, code 1
        with mock.patch("updater.subprocess.Popen", return_value=proc), \
             mock.patch("time.sleep"):
            with pytest.raises(UpdateCheckError) as exc_info:
                launch_installer(path)
        assert "SmartScreen" in str(exc_info.value) or "Antivirus" in str(exc_info.value)
    finally:
        os.unlink(path)


def test_launch_installer_returns_handle_on_success() -> None:
    from updater import launch_installer

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        path = f.name
    try:
        proc = _make_proc(poll_result=None)  # still running
        with mock.patch("updater.subprocess.Popen", return_value=proc) as p, \
             mock.patch("time.sleep"):
            result = launch_installer(path)
        assert result is proc
        # DETACHED_PROCESS flag (0x00000008) must be present
        assert p.call_args.kwargs["creationflags"] == (0x00000008 | 0x00000200)
    finally:
        os.unlink(path)


def test_on_download_verified_catches_launch_failure(tmp_path, wx_app) -> None:
    """End-to-end: the install step surfaces a dialog, not a silent quit.

    If launch_installer raises UpdateCheckError (e.g. UAC blocked in a
    remote session), _on_download_verified must show the user a message
    box and NOT proceed to _quit_for_update. Before the fix, the
    `except UpdateCheckError` in the caller was correct, but
    launch_installer did not raise UpdateCheckError on spawn failure
    (it raised OSError), so nothing was shown and the app just quit.
    """
    import wx
    from audio_editor import SpeechCraftFrame
    from updater import UpdateCheckError

    frame = SpeechCraftFrame()
    frame.Show()

    shown = []

    class _YesDialog:
        """Stands in for the 'Ready to install' confirm dialog."""
        def ShowModal(self):
            return wx.ID_YES
        def Destroy(self):
            pass

    def _box(message, caption, *args, **kwargs):
        shown.append((caption, message))

    with mock.patch("updater.launch_installer",
                    side_effect=UpdateCheckError("Could not start the installer.")), \
         mock.patch.object(wx, "MessageDialog", return_value=_YesDialog()), \
         mock.patch.object(wx, "MessageBox", side_effect=_box), \
         mock.patch.object(frame, "_quit_for_update") as quit_mock:
        class _Info:
            version = "9.9.9"
        frame._on_download_verified(str(tmp_path / "x.exe"), _Info())

    frame.Destroy()

    # The failure was surfaced: "Could not start the installer." box
    assert any("Could not start the installer" in msg for _c, msg in shown), \
        f"expected an installer-launch failure dialog, got: {shown}"
    # And we did NOT proceed to quit+install after the failure
    quit_mock.assert_not_called()
