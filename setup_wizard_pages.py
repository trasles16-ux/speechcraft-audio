"""SpeechCraft Studio setup wizard pages.

Five pages walk the user through personalising SpeechCraft:

1. Welcome — plain-text intro, screen-reader friendly
2. Editing features — checkboxes for the 7 toggleable capabilities
   (basic_editing is the foundation, shown as info text, not a checkbox)
3. TTS engines — checkboxes for Edge TTS and Piper TTS
4. Data location — read-only display of where settings / projects live
5. Summary — list of every flag and its current state, Finish button

Each page subclasses :class:`_WizardPage` which provides the standard
padding, accessible naming, and a ``collect()`` method that pages
override to write their current state into a :class:`FeatureFlags`.

Pure UX scaffolding only: no feature toggling, no downloads, no
actual capability gating. Those ship in v1.3.0-feature-manager.

See docs/plans/2026-09-14-v1.3.0-roadmap.md for the broader
v1.3.0 story.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

import wx

from feature_flags import (
    FEATURE_DESCRIPTIONS,
    FEATURE_NAMES,
    FeatureFlags,
)


#: Page names, in wizard order. Exposed so :mod:`setup_wizard` can
#: enumerate them without re-typing the list.
PAGE_NAMES = (
    "welcome",
    "editing_features",
    "tts_engines",
    "download_ready",
    "data_location",
    "summary",
)


# Features the user can actually toggle on the Editing features page.
# basic_editing is the foundation (always on) and is described in the
# page header copy rather than shown as a checkbox.
TOGGLEABLE_FEATURES = tuple(n for n in FEATURE_NAMES if n != "basic_editing")

# Subset of TOGGLEABLE_FEATURES shown on the Editing features page
# (everything except TTS engines, which get their own page).
EDITING_PAGE_FEATURES = (
    "pedalboard_effects",
    "local_transcription",
    "cloud_transcription",
    "destructive_editing",
    "line_placing",
)

TTS_PAGE_FEATURES = (
    "edge_tts",
    "piper_tts",
)


class _WizardPage(wx.Panel):
    """Base class for wizard pages.

    Subclasses should call ``super().__init__`` with a ``name`` (the
    page title), build their UI in ``_build_ui``, and override
    ``collect()`` to write current state into a returned
    :class:`FeatureFlags`.

    The base class:

    - Sets an accessible name on the panel so NVDA announces the
      page title when focus arrives
    - Provides a consistent vertical padding
    - Provides a ``header_text`` static text the subclass populates
    """

    def __init__(self, parent: wx.Window, *, name: str) -> None:
        super().__init__(parent, wx.ID_ANY)
        self._name = name
        self.SetName(name)
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._sizer)
        self._build_ui()

    @property
    def name(self) -> str:
        return self._name

    def _build_ui(self) -> None:
        """Override in subclasses. Default just adds a placeholder."""
        placeholder = wx.StaticText(self, label=self._name)
        placeholder.SetName(self._name)
        self._sizer.Add(placeholder, 0, wx.ALL, 16)

    def collect(self) -> FeatureFlags:
        """Return a :class:`FeatureFlags` reflecting the page's current state.

        Subclasses MUST override. The base implementation returns
        a default-flag set so the wizard still functions even if a
        subclass forgets to override.
        """
        return FeatureFlags()


class WelcomePage(_WizardPage):
    """Plain-text welcome. No choices, just sets the tone."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, name="Welcome to SpeechCraft Studio")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Welcome to SpeechCraft Studio")
        title.SetFont(
            wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Welcome to SpeechCraft Studio, heading")
        self._heading = title
        self._sizer.Add(title, 0, wx.ALL, 16)

        intro = wx.StaticText(
            self,
            label=(
                "SpeechCraft Studio is a modular audio editor. The "
                "foundation is basic audio editing and effects. Beyond "
                "that, you can choose which capabilities you want to "
                "install: local or cloud transcription, advanced "
                "effects, destructive editing, automatic line placement, "
                "and text-to-speech engines.\n\n"
                "You can change any of these choices later from the "
                "Help menu: Personalise SpeechCraft."
            ),
        )
        intro.SetName(
            "SpeechCraft Studio is a modular audio editor. The "
            "foundation is basic audio editing and effects. Beyond "
            "that, you can choose which capabilities you want to "
            "install. You can change any of these choices later from "
            "the Help menu."
        )
        intro.Wrap(560)
        self._sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)


class EditingFeaturesPage(_WizardPage):
    """Checkbox grid for the 5 Editing-feature flags.

    basic_editing is the foundation (always on) and is described in
    the page intro, NOT as a checkbox. The user toggles the 5
    optional capabilities below it.

    v1.3.5: each feature has a status row showing whether its asset
    (model files, etc.) is ready, needs a download, or isn't
    available in this build. The row uses a small coloured StaticText
    so NVDA reads the label and sighted users see the colour.
    """

    def __init__(self, parent: wx.Window, *, flags: FeatureFlags) -> None:
        self._flags = flags
        self.checkboxes: dict[str, wx.CheckBox] = {}
        self._descriptions: dict[str, wx.StaticText] = {}
        self._status_labels: dict[str, wx.StaticText] = {}
        self._has_state = True  # see _save_current_page in setup_wizard.py
        super().__init__(parent, name="Editing features")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Editing features")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Editing features, heading")
        self._heading = title
        self._sizer.Add(title, 0, wx.ALL, 16)

        foundation = wx.StaticText(
            self,
            label=(
                "Basic audio editing and effects (cut, copy, paste, "
                "EQ, compressor, breath smoothing) is the core of "
                "SpeechCraft and is always on. Below, choose which "
                "additional capabilities you want:"
            ),
        )
        foundation.SetName(
            "Basic audio editing and effects is the core of SpeechCraft "
            "and is always on."
        )
        foundation.Wrap(560)
        self._sizer.Add(foundation, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        # The 5 optional features as a vertical stack of checkboxes,
        # each with its own description as a sub-label and a status row.
        for name in EDITING_PAGE_FEATURES:
            current = getattr(self._flags, name)
            cb = wx.CheckBox(self, label=_humanize(name))
            cb.SetValue(current)
            cb.SetName(f"{_humanize(name)}. {FEATURE_DESCRIPTIONS[name]}")
            self.checkboxes[name] = cb
            self._sizer.Add(cb, 0, wx.LEFT | wx.RIGHT, 24)

            desc = wx.StaticText(self, label=FEATURE_DESCRIPTIONS[name])
            desc.SetName(FEATURE_DESCRIPTIONS[name])
            self._descriptions[name] = desc
            desc.SetForegroundColour(wx.Colour(80, 80, 80))
            desc.Wrap(520)
            self._sizer.Add(desc, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            # v1.3.5 status row
            status = wx.StaticText(self, label="")
            status.SetName(f"{_humanize(name)} status")
            self._status_labels[name] = status
            self._sizer.Add(status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)
        self._refresh_status()

    def collect(self) -> FeatureFlags:
        """Return flags with this page's checkbox state applied."""
        kwargs: dict[str, Any] = {}
        for name in EDITING_PAGE_FEATURES:
            kwargs[name] = self.checkboxes[name].GetValue()
        return FeatureFlags(**kwargs)

    def _refresh_status(self) -> None:
        """Fill each status label with the current asset state.

        Called on construction and whenever the wizard refreshes this
        page (the dialog's ``_on_page_changed`` hook calls this when
        the user navigates to a feature page).
        """
        for name, label in self._status_labels.items():
            status = status_for_feature(name)
            label.SetLabel("Status: " + status)
            # v1.3.6: re-call SetName so NVDA re-announces the status
            # change when focus lands back on the row.
            label.SetName(f"{_humanize(name)} status: {status}")


class TTSEnginesPage(_WizardPage):
    """Two-checkboxes page: Edge TTS and Piper offline TTS.

    v1.3.5: each TTS engine has a status row showing whether its asset
    (voice files, piper.exe) is ready, needs a download, or isn't
    available in this build.
    """

    def __init__(self, parent: wx.Window, *, flags: FeatureFlags) -> None:
        self._flags = flags
        self.checkboxes: dict[str, wx.CheckBox] = {}
        self._descriptions: dict[str, wx.StaticText] = {}
        self._status_labels: dict[str, wx.StaticText] = {}
        self._has_state = True  # see _save_current_page in setup_wizard.py
        super().__init__(parent, name="Text-to-speech engines")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Text-to-speech engines")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Text-to-speech engines, heading")
        self._heading = title
        self._sizer.Add(title, 0, wx.ALL, 16)

        intro = wx.StaticText(
            self,
            label=(
                "SpeechCraft can speak text using either of these "
                "engines. You can enable both — SpeechCraft will pick "
                "the best one for each request."
            ),
        )
        intro.SetName(
            "Choose which text-to-speech engines you want to enable."
        )
        intro.Wrap(560)
        self._sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        for name in TTS_PAGE_FEATURES:
            current = getattr(self._flags, name)
            cb = wx.CheckBox(self, label=_humanize(name))
            cb.SetValue(current)
            cb.SetName(f"{_humanize(name)}. {FEATURE_DESCRIPTIONS[name]}")
            self.checkboxes[name] = cb
            self._sizer.Add(cb, 0, wx.LEFT | wx.RIGHT, 24)

            desc = wx.StaticText(self, label=FEATURE_DESCRIPTIONS[name])
            desc.SetName(FEATURE_DESCRIPTIONS[name])
            self._descriptions[name] = desc
            desc.SetForegroundColour(wx.Colour(80, 80, 80))
            desc.Wrap(520)
            self._sizer.Add(desc, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            # v1.3.5 status row
            status = wx.StaticText(self, label="")
            status.SetName(f"{_humanize(name)} status")
            self._status_labels[name] = status
            self._sizer.Add(status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)
        self._refresh_status()

    def collect(self) -> FeatureFlags:
        kwargs: dict[str, Any] = {}
        for name in TTS_PAGE_FEATURES:
            kwargs[name] = self.checkboxes[name].GetValue()
        return FeatureFlags(**kwargs)

    def _refresh_status(self) -> None:
        for name, label in self._status_labels.items():
            status = status_for_feature(name)
            label.SetLabel("Status: " + status)
            # v1.3.6: re-call SetName so NVDA re-announces the status
            # change when focus lands back on the row.
            label.SetName(f"{_humanize(name)} status: {status}")


class DownloadPage(_WizardPage):
    """Lists every enabled-and-missing asset and offers download buttons.

    One row per ``(feature, asset)`` pair from
    :func:`feature_toggling.gates_to_download_list`. Each row:
    a description label, a :class:`wx.Gauge` progress bar, a live
    status label, and a Download button. A "Download all" button runs
    them in sequence.

    Downloads run in background :class:`threading.Thread` workers so
    the UI stays responsive; every GUI mutation hops to the main
    thread via :func:`wx.CallAfter`. A per-row Cancel button sets a
    ``threading.Event`` the worker polls between chunks.

    This page does not change any flags — it *acts on* them. Its
    ``collect()`` returns the flags it was constructed with,
    unchanged.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        flags: FeatureFlags | None = None,
        flags_provider: Callable[[], FeatureFlags] | None = None,
        state_file: Path | None = None,
    ) -> None:
        # ``flags_provider`` is preferred over a static ``flags``
        # snapshot: the wizard's live flag state changes as the user
        # toggles checkboxes on the Editing / TTS pages, and the
        # download list must reflect those choices. If no provider is
        # supplied, we fall back to a constant provider returning the
        # static ``flags`` (for tests).
        if flags_provider is not None:
            self._flags_provider = flags_provider
        else:
            static = flags if flags is not None else FeatureFlags()

            def _static_provider() -> FeatureFlags:
                return static

            self._flags_provider = _static_provider
        self._flags = self._flags_provider()
        self._state_file = state_file
        self._workers: list[threading.Thread] = []
        self._rows: list[dict] = []
        # Container that gets rebuilt on every refresh
        self._list_holder: wx.Panel | None = None
        self._dl_all: wx.Button | None = None
        self._empty_label: wx.StaticText | None = None
        self._has_state = True
        super().__init__(parent, name="Download ready")

    def refresh(self) -> None:
        """Rebuild the download list from the live flags.

        Called by the wizard on page-navigation so the list reflects
        the user's most recent checkbox choices, not the flags that
        happened to be on disk when the wizard dialog was constructed.
        """
        self._flags = self._flags_provider()
        if self._list_holder is None:
            return
        # Destroy old rows + button
        for row in self._rows:
            for key in ("gauge", "status", "button", "cancel"):
                ctrl = row.get(key)
                if ctrl is not None:
                    ctrl.Destroy()
        self._rows.clear()
        if self._dl_all is not None:
            self._dl_all.Destroy()
            self._dl_all = None
        if self._empty_label is not None:
            self._empty_label.Destroy()
            self._empty_label = None
        # Clear the holder sizer (wxPython 4.x Clear has no kwarg)
        from feature_toggling import build_gates, gates_to_download_list

        holder = self._list_holder
        holder_sizer = holder.GetSizer()
        if holder_sizer is not None:
            holder_sizer.Clear()

        gates = build_gates(self._flags, state_file=self._state_file)
        dl_list = gates_to_download_list(gates)

        if not dl_list:
            self._empty_label = wx.StaticText(
                holder,
                label=(
                    "Everything you chose is ready. Nothing to download.\n"
                    "You can change your feature choices on the "
                    "Editing features and TTS engines pages."
                ),
            )
            self._empty_label.SetName(
                "All selected features are ready, nothing to download. "
                "You can change your feature choices on the previous pages."
            )
            holder_sizer.Add(
                self._empty_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16
            )
            holder_sizer.AddStretchSpacer(1)
        else:
            self._dl_all = wx.Button(holder, wx.ID_ANY, "Download all")
            self._dl_all.SetName("Download all missing models")
            self._dl_all.Bind(wx.EVT_BUTTON, self._on_download_all)
            holder_sizer.Add(self._dl_all, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

            for feature, asset_name in dl_list:
                row = self._build_row_in_holder(holder, feature, asset_name)
                self._rows.append(row)

            holder_sizer.AddStretchSpacer(1)

        holder_sizer.Layout()
        self.Layout()

    def _build_ui(self) -> None:
        from feature_toggling import build_gates, gates_to_download_list

        title = wx.StaticText(self, label="Download ready")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Download ready, heading")
        self._heading = title
        self._sizer.Add(title, 0, wx.ALL, 16)

        intro = wx.StaticText(
            self,
            label=(
                "Some of the features you chose download model files "
                "on first use. Download them now so they're ready to "
                "go. You can skip this and come back later from the "
                "wizard (Help, Personalise SpeechCraft). If the list "
                "looks empty, go back and check the Editing features "
                "and TTS engines pages."
            ),
        )
        intro.SetName(
            "Download models for your chosen features, or skip and "
            "download later from the wizard."
        )
        intro.Wrap(560)
        self._sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Live-rebuilding holder panel
        self._list_holder = wx.Panel(self)
        holder_sizer = wx.BoxSizer(wx.VERTICAL)
        self._list_holder.SetSizer(holder_sizer)
        self._sizer.Add(self._list_holder, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Populate on first show
        self.refresh()

    def _build_row_in_holder(self, holder: wx.Panel, feature: str, asset_name: str) -> dict:
        """Build one download row inside ``holder`` (the live list panel)."""
        from feature_manager import (
            get_asset,
            is_downloadable,
            total_asset_bytes,
        )

        asset = get_asset(feature, asset_name)
        row_sizer = wx.BoxSizer(wx.VERTICAL)

        desc = wx.StaticText(holder, label=asset.description or asset.key)
        desc.SetName(f"{asset.key} description")
        row_sizer.Add(desc, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        hz = wx.BoxSizer(wx.HORIZONTAL)
        gauge = wx.Gauge(holder, range=100, size=(200, 20))
        gauge.SetName(f"{asset.key} download progress")
        hz.Add(gauge, 0, wx.RIGHT, 8)

        status = wx.StaticText(holder, label="Not downloaded")
        status.SetName(f"{asset.key} status")
        hz.Add(status, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        btn = wx.Button(holder, wx.ID_ANY, "Download")
        btn.SetName(f"Download {asset.key}")
        if not is_downloadable(feature, asset_name):
            btn.Disable()
        hz.Add(btn, 0)
        row_sizer.Add(hz, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        cancel = wx.Button(holder, wx.ID_ANY, "Cancel")
        cancel.SetName(f"Cancel download of {asset.key}")
        cancel.Hide()
        cancel.Bind(
            wx.EVT_BUTTON,
            lambda e, f=feature, a=asset_name: self._cancel_row(f, a),
        )
        row_sizer.Add(cancel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        (holder.GetSizer()).Add(row_sizer, 0, wx.EXPAND)

        cancel_event = threading.Event()
        return {
            "feature": feature,
            "asset": asset_name,
            "gauge": gauge,
            "status": status,
            "button": btn,
            "cancel": cancel,
            "cancel_event": cancel_event,
            "total_bytes": total_asset_bytes(feature, asset_name),
        }

    # ------------------------------------------------------------------
    # Public test hook
    # ------------------------------------------------------------------

    def get_row_count(self) -> int:
        """How many download rows does this page have?"""
        return len(self._rows)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_download_all(self, event: wx.Event) -> None:
        for row in self._rows:
            if row["button"].IsEnabled():
                self._start_download(row)

    def _start_download(self, row: dict) -> None:
        from feature_manager import FeatureDownloadError, download_asset
        from prefs import PREFS_DIR

        feature = row["feature"]
        asset = row["asset"]
        cancel_event = row["cancel_event"]
        row["button"].Disable()
        row["cancel"].Show()
        row["status"].SetLabel("Starting download…")
        row["gauge"].SetValue(0)

        def _progress(asset_key: str, done: int, total: int) -> None:
            if total > 0:
                pct = int(100 * done / total)
                wx.CallAfter(row["gauge"].SetValue, min(pct, 100))
                label = f"Downloading… ({done // (1024 * 1024)} of {total // (1024 * 1024)} MB)"
                wx.CallAfter(row["status"].SetLabel, label)

        def _worker() -> None:
            try:
                download_asset(
                    feature,
                    asset,
                    dest_dir=PREFS_DIR / "models",
                    progress_cb=_progress,
                    cancel_check=cancel_event.is_set,
                    state_file=self._state_file,
                )
                wx.CallAfter(row["button"].SetLabel, "Ready")
                wx.CallAfter(row["status"].SetLabel, "Downloaded and verified.")
                wx.CallAfter(row["gauge"].SetValue, 100)
            except FeatureDownloadError as exc:
                wx.CallAfter(row["button"].Enable)
                wx.CallAfter(row["button"].SetLabel, "Retry")
                wx.CallAfter(row["status"].SetLabel, f"Failed: {exc.reason}")
            finally:
                wx.CallAfter(row["cancel"].Hide)

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        self._workers.append(worker)

    def _cancel_row(self, feature: str, asset_name: str, event: wx.Event | None = None) -> None:
        for row in self._rows:
            if row["feature"] == feature and row["asset"] == asset_name:
                row["cancel_event"].set()

    def collect(self) -> FeatureFlags:
        # The download page acts on flags; it never changes them.
        return self._flags


class DataLocationPage(_WizardPage):
    """Read-only display of where SpeechCraft stores its data.

    Per v1.3.0-wizard-shell scope: no editing. Future PRs may add a
    Browse button. For now the page just tells the user where things
    live, so they can find their files.
    """

    def __init__(
        self,
        parent: wx.Window,
        *,
        settings_dir: Path,
        projects_dir: Path,
    ) -> None:
        self._settings_dir = settings_dir
        self._projects_dir = projects_dir
        super().__init__(parent, name="Where your files live")

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Where your files live")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Where your files live, heading")
        self._heading = title
        self._sizer.Add(title, 0, wx.ALL, 16)

        intro = wx.StaticText(
            self,
            label=(
                "SpeechCraft keeps its settings and your projects in "
                "standard locations so they're easy to back up."
            ),
        )
        intro.SetName("SpeechCraft keeps its settings and projects in standard locations.")
        intro.Wrap(560)
        self._sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        # Settings path row
        settings_label = wx.StaticText(self, label="Settings and preferences:")
        settings_label.SetName("Settings location label")
        self._sizer.Add(settings_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        settings_path = wx.StaticText(self, label=str(self._settings_dir))
        settings_path.SetName(f"Settings location: {self._settings_dir}")
        settings_path.SetFont(
            wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        )
        self._sizer.Add(settings_path, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        # Projects path row
        projects_label = wx.StaticText(self, label="Projects (audio files):")
        projects_label.SetName("Projects location label")
        self._sizer.Add(projects_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)

        projects_path = wx.StaticText(self, label=str(self._projects_dir))
        projects_path.SetName(f"Projects location: {self._projects_dir}")
        projects_path.SetFont(
            wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        )
        self._sizer.Add(projects_path, 0, wx.LEFT | wx.RIGHT, 16)


class SummaryPage(_WizardPage):
    """Summary of every flag and its current state, with Finish button.

    The Finish button is wired by the parent SetupWizardDialog, not
    here. This page just renders the summary text and exposes the
    flags for the dialog to read at Finish time.
    """

    def __init__(self, parent: wx.Window, *, flags: FeatureFlags) -> None:
        self._flags = flags
        super().__init__(parent, name="Summary")
        self._refresh_summary()

    def update_flags(self, flags: FeatureFlags) -> None:
        """Refresh the summary text with new flags (called as pages
        are navigated backwards to)."""
        self._flags = flags
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        # Replace the summary body if it already exists.
        if hasattr(self, "_summary_text"):
            self._summary_text.SetLabel(self._render_text())
            self._summary_text.SetName(self._accessible_summary())
            self._summary_text.Wrap(560)
            return
        # Otherwise nothing yet — body is built in _build_ui.

    def _render_text(self) -> str:
        lines = ["Here's what you've chosen:"]
        for name in FEATURE_NAMES:
            on = getattr(self._flags, name)
            mark = "ON " if on else "OFF"
            status = status_for_feature(name)
            lines.append(f"  [{mark}]  {_humanize(name):<20}  {status}")
        lines.append("")
        lines.append(
            "Click Finish to apply these settings. You can change "
            "them later from Help → Personalise SpeechCraft."
        )
        return "\n".join(lines)

    def _accessible_summary(self) -> str:
        parts = ["Summary of your choices:"]
        for name in FEATURE_NAMES:
            on = getattr(self._flags, name)
            on_text = "enabled" if on else "disabled"
            status = status_for_feature(name)
            parts.append(
                f"{_humanize(name)} is {on_text}, status: {status}."
            )
        return " ".join(parts)

    def _build_ui(self) -> None:
        title = wx.StaticText(self, label="Summary")
        title.SetFont(
            wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        title.SetName("Summary, heading")
        self._heading = title
        self._sizer.Add(title, 0, wx.ALL, 16)

        body = wx.StaticText(self, label=self._render_text())
        body.SetName(self._accessible_summary())
        body.Wrap(560)
        self._summary_text = body
        self._sizer.Add(body, 0, wx.LEFT | wx.RIGHT, 16)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _humanize(name: str) -> str:
    """basic_editing -> Basic editing, line_placing -> Line placing."""
    parts = name.split("_")
    return " ".join(parts).capitalize()


# --- Feature status (v1.3.5) -----------------------------------------------
#
# Each feature has an asset-state derived from
# ``feature_toggling.build_gates(flags)``. We surface the four
# ``GateDecision`` values as short, plain-language labels so the user
# can see at a glance which features are ready to use and which need a
# download. The labels are stable strings so tests can assert on them.


_STATUS_LABELS: dict[str, str] = {
    # feature is off (user disabled it in the wizard)
    "disabled": "Off",
    # feature is on, no downloadable asset — it's always ready
    "enabled": "Ready",
    # feature is on but the asset isn't on disk yet
    "needs_download": "Needs download",
    # feature is on but the asset is a placeholder (not downloadable yet)
    "unavailable": "Not available in this build",
}


def status_for_feature(feature: str, *, state_file: Path | None = None) -> str:
    """Return a short status string for ``feature``.

    Reads the current ``FeatureFlags`` from setup.json, builds the
    gate decisions, and maps the result to one of the ``_STATUS_LABELS``
    keys. Pure function — used by the wizard pages and by tests.

    The ``state_file`` kwarg is forwarded to
    :func:`feature_toggling.build_gates` so tests can drive the asset
    state without touching the real setup.json.
    """
    from feature_flags import load_feature_flags
    from feature_toggling import build_gates

    try:
        flags = load_feature_flags()
    except Exception:
        # Permissive default: all features on, status comes from asset
        # readiness only. The wizard never blocks on flag-load errors.
        from feature_flags import FeatureFlags
        flags = FeatureFlags()

    try:
        gates = build_gates(flags, state_file=state_file)
    except Exception:
        return _STATUS_LABELS["unavailable"]

    gate = gates.get(feature)
    if gate is None:
        return _STATUS_LABELS["unavailable"]
    return _STATUS_LABELS.get(gate.decision, _STATUS_LABELS["unavailable"])


__all__ = (
    "EDITING_PAGE_FEATURES",
    "PAGE_NAMES",
    "TTS_PAGE_FEATURES",
    "TOGGLEABLE_FEATURES",
    "DataLocationPage",
    "DownloadPage",
    "EditingFeaturesPage",
    "SummaryPage",
    "TTSEnginesPage",
    "WelcomePage",
    "status_for_feature",
)
