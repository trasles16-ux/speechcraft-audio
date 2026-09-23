"""Lazy install helper for SpeechCraft Studio feature assets.

The v1.3.0 wizard lets the user opt in or out of features, but the
download happens *only* on the wizard's "Download ready" page. If a
user enables a feature later (via Help → Personalise SpeechCraft)
without going through that page, or skips the wizard entirely, the
asset is still missing when they actually try to use the feature.

This module provides a single function,
:func:`prompt_and_install`, that menu / engine code calls the moment a
feature is invoked:

- If the asset is already on disk, returns ``True`` immediately.
- If it's missing, shows a small ``wx.MessageDialog``:
  "<Feature> needs to be downloaded (~60 MB). Download now?"
- On "Yes", shows the same :class:`DownloadProgressDialog` the auto-
  updater uses, runs :func:`feature_manager.ensure_ready` on a worker
  thread, and returns ``True`` when ready.
- On "No" / cancel / failure, returns ``False``.

Pure orchestration — the heavy lifting (HTTP, SHA, atomic write) lives
in :mod:`updater` and :mod:`feature_manager`. This module is just the
glue that makes the lazy-install flow accessible to the rest of the
app and gives the user a clear, non-silent prompt.

The function is wx-aware (it constructs dialogs and calls
``wx.CallAfter``) but the entry point is safe to call from any thread
because all wx interactions happen via ``CallAfter``.
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Callable, Final

import wx

import feature_manager


_PROMPT_ICON: Final = wx.ICON_QUESTION | wx.YES_NO | wx.NO_DEFAULT


def _format_size(size_bytes: int | None) -> str:
    """Return a human-readable size for the dialog text."""
    if not size_bytes or size_bytes <= 0:
        return ""
    mb = size_bytes / (1024 * 1024)
    if mb >= 1:
        return f"~{mb:.0f} MB"
    kb = size_bytes / 1024
    return f"~{kb:.0f} KB"


def _run_download_worker(
    *,
    feature: str,
    asset_name: str,
    state_file: Path | None,
    on_state: Callable[[str], None],
    on_progress: Callable[[int, int], None],
    on_done: Callable[[bool, str | None], None],
    on_cancel: Callable[[], bool] | None,
) -> threading.Thread:
    """Spin up a background thread that calls ``feature_manager.ensure_ready``.

    State callbacks fire on the worker thread — the caller is responsible
    for hopping to the UI thread via ``wx.CallAfter``. The thread is
    daemon so it never wedges app shutdown.
    """

    def _emit_state(s: str) -> None:
        on_state(s)

    def _emit_progress(downloaded: int, total: int) -> None:
        on_progress(downloaded, total)

    def _emit_done(ok: bool, err: str | None) -> None:
        on_done(ok, err)

    def _worker() -> None:
        try:
            _emit_state("connecting")

            def _progress(asset_key: str, done: int, total: int) -> None:
                _emit_progress(done, total)

            _emit_state("downloading")
            feature_manager.ensure_ready(
                feature,
                asset_name,
                progress_cb=_progress,
                cancel_check=on_cancel,
                state_file=state_file,
            )
            _emit_state("verifying")
            _emit_done(True, None)
        except feature_manager.FeatureDownloadError as exc:
            _emit_done(False, str(exc))
        except Exception as exc:  # noqa: BLE001 — surface as a friendly error
            _emit_done(False, f"Unexpected error: {exc}\n{traceback.format_exc()}")

    t = threading.Thread(target=_worker, daemon=True, name=f"lazy-install-{feature}-{asset_name}")
    t.start()
    return t


def prompt_and_install(
    feature: str,
    asset_name: str,
    *,
    parent: wx.Window | None = None,
    state_file: Path | None = None,
    custom_prompt: str | None = None,
) -> bool:
    """Ensure ``(feature, asset_name)`` is on disk; prompt + download if not.

    Returns ``True`` when the asset is ready (already was, or just
    downloaded), ``False`` when the user declined or the download
    failed. Never raises — surface errors via the dialog.

    The function blocks the calling thread until the user dismisses
    the prompt AND any subsequent download completes. That's intentional:
    callers (menu handlers, engine constructors) want a synchronous
    "did this work?" answer before they proceed. The download itself
    runs on a daemon thread; the prompt is shown on the UI thread via
    ``wx.CallAfter`` so the modal stays responsive.
    """
    # Already on disk? Done.
    if feature_manager.is_ready(feature, asset_name, state_file=state_file):
        return True

    # Build the prompt text. ``description`` is what the user sees in
    # the wizard, so reuse it here.
    try:
        asset = feature_manager.get_asset(feature, asset_name)
    except KeyError:
        asset = None
    description = asset.description if asset else f"{feature} / {asset_name}"
    size_hint = _format_size(
        feature_manager.total_asset_bytes(feature, asset_name)
        if asset_name in feature_manager.list_assets(feature)
        else 0
    )

    if custom_prompt:
        prompt_text = custom_prompt
    else:
        size_part = f" ({size_hint})" if size_hint else ""
        prompt_text = (
            f"{description} needs to be downloaded{size_part}.\n\n"
            "Download now?"
        )

    # Must be on the UI thread for wx.MessageDialog.
    prompt_result: list[bool] = [False]

    def _ask() -> None:
        dlg = wx.MessageDialog(
            parent,
            prompt_text,
            f"Download {description}",
            _PROMPT_ICON,
        )
        try:
            prompt_result[0] = dlg.ShowModal() == wx.ID_YES
        finally:
            dlg.Destroy()

    if wx.IsMainThread():
        _ask()
    else:
        wx.CallAfter(_ask)
        # Wait for the UI-thread round-trip.
        while prompt_result == [False] and not _user_already_declined():
            wx.MilliSleep(50)

    if not prompt_result[0]:
        return False

    # User accepted — show progress + run worker.
    progress_dlg: list[DownloadProgressDialog | None] = [None]
    done_evt = threading.Event()
    outcome: list[tuple[bool, str | None]] = [(False, None)]

    def _on_main_state(state: str) -> None:
        if progress_dlg[0] is None:
            return
        wx.CallAfter(progress_dlg[0].update, state, 0, 0)

    def _on_main_progress(downloaded: int, total: int) -> None:
        if progress_dlg[0] is None:
            return
        wx.CallAfter(progress_dlg[0].update, "downloading", downloaded, total)

    def _on_main_done(ok: bool, err: str | None) -> None:
        outcome[0] = (ok, err)
        if progress_dlg[0] is not None:
            wx.CallAfter(progress_dlg[0].EndModal, wx.ID_OK if ok else wx.ID_CANCEL)
        done_evt.set()

    def _show_progress() -> None:
        from dialogs.download_progress_dialog import DownloadProgressDialog
        total = feature_manager.total_asset_bytes(feature, asset_name)
        progress_dlg[0] = DownloadProgressDialog(
            parent,
            file_name=description,
            total_bytes=total or 1,
        )
        try:
            progress_dlg[0].ShowModal()
        finally:
            progress_dlg[0].Destroy()
            progress_dlg[0] = None

    cancelled = threading.Event()

    def _is_cancelled() -> bool:
        return cancelled.is_set() or (
            progress_dlg[0] is not None and progress_dlg[0].is_cancelled()
        )

    # Run worker thread + UI dialog in parallel.
    _run_download_worker(
        feature=feature,
        asset_name=asset_name,
        state_file=state_file,
        on_state=_on_main_state,
        on_progress=_on_main_progress,
        on_done=_on_main_done,
        on_cancel=_is_cancelled,
    )

    # Show progress dialog on the UI thread (blocks until done).
    if wx.IsMainThread():
        _show_progress()
    else:
        wx.CallAfter(_show_progress)

    done_evt.wait()
    cancelled.set()  # tell the worker to stop polling if it's still mid-cancel

    ok, err = outcome[0]
    if not ok and err:
        wx.MessageBox(
            f"Could not download {description}.\n\n{err}",
            "Download failed",
            wx.ICON_ERROR,
            parent=parent,
        )
    return ok


def _user_already_declined() -> bool:  # pragma: no cover — helper
    """Reserved hook so tests can short-circuit the UI-thread wait."""
    return False


# Late import to keep the module's static surface small and to avoid
# pulling wxPython into code paths that only need is_ready / ensure_ready.
from dialogs.download_progress_dialog import (  # noqa: E402  — intentional late import
    DownloadProgressDialog,
)


__all__ = ("prompt_and_install",)
