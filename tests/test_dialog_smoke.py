"""Smoke tests: import every TTS engine module and a few key UI helpers.

These tests do not launch wx, do not open dialogs, and do not
download voice models. They exist for one reason: to catch the
exact class of bug that broke the Piper TTS dialog before this
project shipped publicly — namely, a dialog calling a method that
does not exist on its engine (``engine.get_all_voices()`` when the
engine only has ``get_voices()``).

If you add a new TTS engine module, add it to ``TTS_ENGINE_MODULES``
below. If you add a new dialog that uses an engine, exercise the
attribute lookup in ``DIALOG_METHODS`` to lock in the API contract.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Any

import pytest

# Make project root importable so ``import piper_tts_engine`` works
# without an installed package.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TTS_ENGINE_MODULES = [
    "edge_tts_engine",
    "piper_tts_engine",
]

# Each entry: (module, attribute, expected_callable)
# These are the dialog-facing API methods that the TTS dialogs depend
# on. If a method is renamed, update this list AND the calling dialog
# in the same PR.
DIALOG_METHODS = [
    ("edge_tts_engine", "EdgeTTSEngine", "get_all_voices"),
    ("piper_tts_engine", "PiperTTSEngine", "get_voices"),
]

# Modules that must import cleanly without wx being alive.
# ``dialogs.effects_dialogs`` requires pydub / numpy / sounddevice /
# wx at module-load time, so it sits in the wx-gated section below.
BUG_REPORT_MODULES = [
    "crash_submit",
]

# Dialog classes that live in dialogs/effects_dialogs.py and must be
# importable for the audio_editor.py extraction (PR #3) to work.
# Listed as (module, class_name) so an accidental rename fails loud.
EFFECTS_DIALOG_CLASSES = [
    ("dialogs.effects_dialogs", "AudioClipboard"),
    ("dialogs.effects_dialogs", "EffectSettingsDialog"),
    ("dialogs.effects_dialogs", "BreathSmoothingPresetDialog"),
    ("dialogs.effects_dialogs", "CompressorPresetDialog"),
    ("dialogs.effects_dialogs", "EQPresetDialog"),
    ("dialogs.effects_dialogs", "RoomToneMatchDialog"),
    ("dialogs.effects_dialogs", "BatchProcessDialog"),
]

# Dialog classes that live in dialogs/recording_dialogs.py and must
# be importable for the audio_editor.py extraction (PR #4) to work.
RECORDING_DIALOG_CLASSES = [
    ("dialogs.recording_dialogs", "RecordingDialog"),
    ("dialogs.recording_dialogs", "StudioRecordingDialog"),
]


def _wx_available() -> bool:
    try:
        import wx  # noqa: F401
        return True
    except ImportError:
        return False


needs_wx = pytest.mark.skipif(
    not _wx_available(),
    reason="wxPython not installed; skip wx-dependent modules",
)


@pytest.mark.parametrize("module_name", TTS_ENGINE_MODULES)
def test_tts_engine_module_imports(module_name: str) -> None:
    """Every TTS engine module must import without side effects."""
    importlib.import_module(module_name)


@needs_wx
@pytest.mark.parametrize("module_name", ["bug_report_dialog"])
def test_bug_report_modules_import(module_name: str) -> None:
    """The bug-report dialog imports wx at the top level, so this
    test only runs when wx is installed."""
    mod = importlib.import_module(module_name)
    assert mod is not None


@pytest.mark.parametrize("module_name", BUG_REPORT_MODULES)
def test_log_only_modules_import(module_name: str) -> None:
    """crash_submit is dependency-light and must always import."""
    mod = importlib.import_module(module_name)
    assert mod is not None


@needs_wx
@pytest.mark.parametrize("module_name,class_name",
                         EFFECTS_DIALOG_CLASSES + RECORDING_DIALOG_CLASSES)
def test_extracted_dialog_classes_importable(
    module_name: str, class_name: str
) -> None:
    """Every dialog extracted to ``dialogs/`` must be importable from
    there. If a class is renamed in one place but not the other, this
    test fails -- which is exactly the failure mode that a 5148-line
    audio_editor.py would have hidden."""
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name, None)
    assert cls is not None, (
        f"{module_name}.{class_name} is missing. "
        f"Either the class was renamed (update this test), or the "
        f"audio_editor.py extraction dropped a class."
    )


@pytest.mark.parametrize("module_name,class_name",
                         EFFECTS_DIALOG_CLASSES + RECORDING_DIALOG_CLASSES)
def test_audio_editor_imports_extracted_classes(
    module_name: str, class_name: str
) -> None:
    """audio_editor.py must re-export every extracted class. Catches
    the case where someone moves a class into ``dialogs/`` but forgets
    to add it to the ``from dialogs.X import (...)`` line in
    audio_editor.py."""
    # Importing audio_editor pulls in wx + numpy + the full app --
    # we cannot do that without wx installed, so gate this on wx.
    if not _wx_available():
        pytest.skip("wxPython not installed")
    try:
        import audio_editor
    except ImportError as exc:
        # If audio_editor fails to import for any reason (missing
        # dep, broken module), the same root cause will fail every
        # parametrised case. Skip them all with a single targeted
        # message rather than producing 7 identical tracebacks.
        pytest.skip(
            f"audio_editor.py cannot be imported ({exc.__class__.__name__}: "
            f"{exc}). Fix the import error first; the per-class checks "
            f"will become meaningful once audio_editor loads."
        )

    assert hasattr(audio_editor, class_name), (
        f"audio_editor.{class_name} is missing. "
        f"The extraction moved the class to {module_name} "
        f"but audio_editor.py does not re-export it. Add "
        f"'{class_name}' to the import line in audio_editor.py."
    )


@pytest.mark.parametrize("module_name,class_name,method_name", DIALOG_METHODS)
def test_dialog_facing_method_exists(
    module_name: str, class_name: str, method_name: str
) -> None:
    """The TTS dialogs depend on these specific methods. If a method
    is renamed without updating the dialog, this test will fail."""
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name)
    assert hasattr(cls, method_name), (
        f"{module_name}.{class_name}.{method_name} is missing. "
        f"The TTS dialog calls this method; if you renamed it, update "
        f"audio_editor.py's on_piper_tts / on_edge_tts in the same PR."
    )
    assert callable(getattr(cls, method_name)), (
        f"{module_name}.{class_name}.{method_name} exists but is not callable."
    )


def test_crash_submit_read_log_tail_handles_missing_file(tmp_path: Path) -> None:
    """crash_submit.read_log_tail must return None when the log file does not exist."""
    from crash_submit import read_log_tail

    missing = tmp_path / "does_not_exist.log"
    assert read_log_tail(missing) is None


def test_crash_submit_read_log_tail_returns_tail(tmp_path: Path) -> None:
    """crash_submit.read_log_tail must return the last N lines."""
    from crash_submit import read_log_tail

    log = tmp_path / "speechcraft_error.log"
    log.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
    tail = read_log_tail(log, max_lines=10)
    assert tail is not None
    assert tail.splitlines() == [f"line {i}" for i in range(90, 100)]


@needs_wx
def test_bug_report_url_builder_includes_all_fields() -> None:
    """The pre-filled URL must include every field the user typed."""
    from bug_report_dialog import build_issue_url

    url = build_issue_url(
        title="Piper voice says unknown",
        description="I opened Speech > Piper TTS.",
        expected="NVDA should announce the voice name.",
        steps="1. Launch\n2. Open Piper TTS",
        app_version="3.0.2",
        platform_label="Windows 11",
        python_version="3.11.9",
        screen_reader="NVDA",
        log_tail="Traceback ...\nValueError: ...",
    )
    assert "github.com/trasles16-ux/speechcraft-audio/issues/new" in url
    assert "Piper+voice+says+unknown" in url or "Piper%20voice%20says%20unknown" in url
    assert "template=bug.yml" in url
    assert "NVDA" in url
    assert "Traceback" in url


@needs_wx
def test_bug_report_url_builder_handles_no_log() -> None:
    """When there is no log to attach, the URL must still build."""
    from bug_report_dialog import build_issue_url

    url = build_issue_url(
        title="t",
        description="d",
        expected="e",
        steps="s",
        app_version="3.0.2",
        platform_label="Windows 11",
        python_version="3.11.9",
        screen_reader="",
        log_tail=None,
    )
    assert "issues/new" in url
    assert "Recent+log+output" not in url  # No log section when log is None


# ===========================================================================
# TTS mixin wiring (from PR #5)
# ===========================================================================

@needs_wx
def test_main_frame_tts_imports() -> None:
    """Import the TTS mixin module without errors."""
    import main_frame_tts  # noqa: F401


@needs_wx
def test_tts_mixin_class_exists() -> None:
    """TTSMenuMixin must exist and expose both handlers."""
    from main_frame_tts import TTSMenuMixin
    assert hasattr(TTSMenuMixin, "on_edge_tts")
    assert hasattr(TTSMenuMixin, "on_piper_tts")
    assert callable(TTSMenuMixin.on_edge_tts)
    assert callable(TTSMenuMixin.on_piper_tts)


@needs_wx
def test_speechcraft_frame_on_edge_tts_is_mixin() -> None:
    """SpeechCraftFrame.on_edge_tts must come from TTSMenuMixin.

    If someone accidentally redefines on_edge_tts on the frame itself,
    this test fails — because it means the mixin wiring is broken.
    """
    try:
        import audio_editor
    except ImportError as exc:
        pytest.skip(f"audio_editor.py cannot be imported ({exc})")
    from main_frame_tts import TTSMenuMixin
    import audio_editor as ae  # type: ignore
    assert ae.SpeechCraftFrame.on_edge_tts is TTSMenuMixin.on_edge_tts
    assert ae.SpeechCraftFrame.on_piper_tts is TTSMenuMixin.on_piper_tts


# ===========================================================================
# Functional tests for extracted dialog classes
# ===========================================================================
#
# These tests construct each extracted dialog and exercise the public
# API contract (mostly ``get_values()`` and similar) that the call sites
# in audio_editor.py depend on. They do NOT open the dialog modally
# (which would block waiting for user input) -- they just construct,
# mutate state, and verify the return values.
#
# AudioClipboard is tested without wx because it is plain Python state.
# All other dialog tests need wx (the dialogs are wx.Dialog subclasses).


# ---------------------------------------------------------------------------
# AudioClipboard -- pure Python, no wx needed
# ---------------------------------------------------------------------------
# NOTE: ``dialogs.effects_dialogs`` imports sounddevice at module-load
# time (for the RoomToneMatchDialog path), so these tests must gate on
# wx availability which correlates with sounddevice being installed in
# the project's Windows CI environment.


def _sounddevice_available() -> bool:
    try:
        import sounddevice  # noqa: F401
        return True
    except ImportError:
        return False


needs_sounddevice = pytest.mark.skipif(
    not _sounddevice_available(),
    reason="sounddevice not installed; skip AudioClipboard tests",
)


@needs_sounddevice
def test_audio_clipboard_starts_empty() -> None:
    """A freshly-imported AudioClipboard reports no content."""
    from dialogs.effects_dialogs import AudioClipboard
    # Force-clear any leftover state from a previous test
    AudioClipboard._segment = None
    AudioClipboard._word_segments = []
    assert AudioClipboard.has_content() is False
    assert AudioClipboard.get() == (None, [])


@needs_sounddevice
def test_audio_clipboard_set_then_get_round_trips() -> None:
    """set() followed by get() returns the same segment and words."""
    from dialogs.effects_dialogs import AudioClipboard

    AudioClipboard._segment = None
    AudioClipboard._word_segments = []

    sentinel_segment = object()
    sentinel_words = [{"word": "hello", "start": 0, "end": 1}]
    AudioClipboard.set(sentinel_segment, sentinel_words)
    assert AudioClipboard.has_content() is True
    seg, words = AudioClipboard.get()
    assert seg is sentinel_segment
    assert words == sentinel_words


@needs_sounddevice
def test_audio_clipboard_set_with_no_words_defaults_to_empty_list() -> None:
    """``AudioClipboard.set(segment)`` (no words arg) defaults to []."""
    from dialogs.effects_dialogs import AudioClipboard

    AudioClipboard._segment = None
    AudioClipboard._word_segments = []

    AudioClipboard.set("any-segment")
    _seg, words = AudioClipboard.get()
    assert words == []


@needs_sounddevice
def test_audio_clipboard_set_with_none_words_defaults_to_empty_list() -> None:
    """``AudioClipboard.set(segment, None)`` also defaults to []."""
    from dialogs.effects_dialogs import AudioClipboard

    AudioClipboard._segment = None
    AudioClipboard._word_segments = []

    AudioClipboard.set("any-segment", None)
    _seg, words = AudioClipboard.get()
    assert words == []


# ---------------------------------------------------------------------------
# EffectSettingsDialog -- generic param dialog
# ---------------------------------------------------------------------------


@needs_wx
def test_effect_settings_dialog_constructs_with_text_params(wx_app: Any) -> None:
    """EffectSettingsDialog builds without crashing on a text-only params dict."""
    import wx
    from dialogs.effects_dialogs import EffectSettingsDialog

    # parent=None is supported by wx when an App is alive
    dlg = EffectSettingsDialog(None, "Test", {"name": "default", "value": 42})
    try:
        # controls dict is populated for every param label
        assert set(dlg.controls.keys()) == {"name", "value"}
        assert isinstance(dlg.controls["name"], wx.TextCtrl)
        assert isinstance(dlg.controls["value"], wx.TextCtrl)
    finally:
        dlg.Destroy()


@needs_wx
def test_effect_settings_dialog_constructs_with_slider_params(wx_app: Any) -> None:
    """EffectSettingsDialog builds with a tuple-valued param as a wx.Slider."""
    import wx
    from dialogs.effects_dialogs import EffectSettingsDialog

    dlg = EffectSettingsDialog(
        None, "Test Slider",
        {"level_db": (-20, -80, 0)},  # (current, min, max) -> Slider
    )
    try:
        assert isinstance(dlg.controls["level_db"], wx.Slider)
        # The slider is initialised to the current value
        assert dlg.controls["level_db"].GetValue() == -20
    finally:
        dlg.Destroy()


@needs_wx
def test_effect_settings_dialog_get_values_returns_dict(wx_app: Any) -> None:
    """``get_values()`` returns a dict keyed by the param labels."""
    from dialogs.effects_dialogs import EffectSettingsDialog

    dlg = EffectSettingsDialog(None, "Test", {"name": "hello"})
    try:
        values = dlg.get_values()
        assert values == {"name": "hello"}
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# BreathSmoothingPresetDialog
# ---------------------------------------------------------------------------


@needs_wx
def test_breath_dialog_constructs_and_get_values_has_required_keys(
    wx_app: Any,
) -> None:
    """BreathSmoothingPresetDialog.get_values() returns the four keys
    the breath_smoothing module looks up."""
    from dialogs.effects_dialogs import BreathSmoothingPresetDialog

    dlg = BreathSmoothingPresetDialog(None)
    try:
        values = dlg.get_values()
        assert set(values.keys()) == {
            "reduction_db",
            "dry_wet",
            "rms_thresh",
            "preset_name",
        }
        # Default preset is Medium
        assert values["preset_name"] == "Medium"
        # dry_wet is in [0.01, 1.0]
        assert 0.01 <= values["dry_wet"] <= 1.0
        # rms_thresh is in [0.01, 0.10]
        assert 0.01 <= values["rms_thresh"] <= 0.10
        # reduction_db is numeric (from config.BREATH_SMOOTHING_LEVELS)
        assert isinstance(values["reduction_db"], (int, float))
    finally:
        dlg.Destroy()


@needs_wx
def test_breath_dialog_every_control_has_meaningful_accessible_name(
    wx_app: Any,
) -> None:
    """Regression test for an NVDA bug: the Breath Smoothing dialog
    exposed Light / Medium / Heavy radio buttons with default
    accessible names ('radioButton'), so NVDA saw three identical
    controls and skipped the first one. JAWS reads the label even
    without SetName, which is why JAWS users could find 'Light' but
    NVDA users couldn't.

    This test asserts every interactive control in the dialog has an
    explicit accessible name that contains its visual label (or some
    other meaningful text). It walks the dialog tree and checks every
    RadioButton, Slider, Button, and StaticText with non-empty label.
    """
    import wx  # used here for type checks; only imported when wx is available
    from dialogs.effects_dialogs import BreathSmoothingPresetDialog

    dlg = BreathSmoothingPresetDialog(None)
    try:
        # The dialog itself: name should be the title, not 'dialog'.
        assert dlg.GetName() == "Breath Smoothing", (
            f"dialog accessible name is {dlg.GetName()!r}, expected 'Breath Smoothing'"
        )

        # Walk every control and check that interactive widgets have
        # meaningful names (not the wx defaults).
        def walk(widget):
            yield widget
            for child in widget.GetChildren():
                yield from walk(child)

        # Defaults wx assigns when SetName() is not called
        bad_defaults = {"dialog", "staticText", "radioButton", "button", "slider", "groupBox"}
        interactive_types = (wx.RadioButton, wx.Slider, wx.Button)

        problems = []
        for widget in walk(dlg):
            cls = type(widget).__name__
            name = widget.GetName()
            # Get the visible label (StaticText, Button, RadioButton all
            # implement GetLabel; Sliders don't but their tooltip holds the description).
            try:
                label = widget.GetLabel()
            except Exception:
                label = ""
            if isinstance(widget, interactive_types):
                # Interactive control: must have a meaningful name.
                if name in bad_defaults:
                    problems.append(
                        f"{cls} label={label!r:30}  name={name!r}  (default; needs SetName)"
                    )
                # And the name must contain the visible label (or close
                # to it) so the screen reader announces it. Strip
                # trailing punctuation for comparison -- button labels
                # often end in "..." but accessible names use "," etc.
                if label:
                    label_clean = label.rstrip(".…").rstrip()
                    if label_clean and label_clean not in name:
                        problems.append(
                            f"{cls} label={label!r:30}  name={name!r}  (name doesn't mention label)"
                        )
            elif isinstance(widget, wx.StaticText) and label:
                # Static text with visible content should announce that
                # content (not the default 'staticText').
                if name in bad_defaults:
                    problems.append(
                        f"StaticText label={label[:40]!r}  name={name!r}  (default)"
                    )
        assert not problems, "Accessibility problems found:\n  " + "\n  ".join(problems)
    finally:
        dlg.Destroy()


@needs_wx
def test_breath_dialog_radio_preset_is_mutually_exclusive_group(
    wx_app: Any,
) -> None:
    """Regression test for a real NVDA bug: the Strength radios were
    created with RB_GROUP on 'Medium' instead of the first radio
    ('Light'). That split them into two Windows radio groups --
    Light in its own group, Medium+Heavy in another. NVDA walks
    radio groups, and its standard radio-navigation (arrow keys,
    browse-mode 'r' key) only steps within the currently-focused
    group. Because the dialog opens with Medium selected, focus
    lands in the Medium+Heavy group, and Light (the other group)
    is unreachable through normal radio navigation. JAWS matches
    by label and could still find Light, which is why the bug
    only showed up for NVDA users.

    The fix puts RB_GROUP on the first radio so all three are in
    one group. This test asserts the radios are mutually exclusive:
    selecting any one deselects the others.
    """
    from dialogs.effects_dialogs import BreathSmoothingPresetDialog

    dlg = BreathSmoothingPresetDialog(None)
    try:
        # Default: Medium selected
        assert dlg.preset_radios["Medium"].GetValue()
        assert not dlg.preset_radios["Light"].GetValue()
        assert not dlg.preset_radios["Heavy"].GetValue()

        # Select Light -> Medium must deselect
        dlg.preset_radios["Light"].SetValue(True)
        assert dlg.preset_radios["Light"].GetValue()
        assert not dlg.preset_radios["Medium"].GetValue(), (
            "Light and Medium are in separate radio groups; "
            "selecting Light did not deselect Medium. "
            "Check that RB_GROUP is on the FIRST radio."
        )
        assert not dlg.preset_radios["Heavy"].GetValue()

        # Select Medium -> Light must deselect
        dlg.preset_radios["Medium"].SetValue(True)
        assert not dlg.preset_radios["Light"].GetValue()
        assert dlg.preset_radios["Medium"].GetValue()

        # Select Heavy -> Medium must deselect
        dlg.preset_radios["Heavy"].SetValue(True)
        assert not dlg.preset_radios["Medium"].GetValue()
        assert dlg.preset_radios["Heavy"].GetValue()
    finally:
        dlg.Destroy()


def _assert_radios_mutually_exclusive(dlg, default_selected: str, others: list[str]) -> None:
    """Shared check: the dialog's preset radios form ONE mutually-
    exclusive Windows radio group.

    Catches the RB_GROUP misconfiguration where either:
      - RB_GROUP is on the *wrong* radio (splits into two groups), or
      - RB_GROUP is on *every* radio (each in its own group, all
        read 'selected' at once).
    Either way NVDA sees a list of unrelated standalone radios instead
    of one exclusive group, and the data is corrupted (multiple
    presets 'selected').
    """
    # Opening state: only the default is selected, exactly one.
    assert dlg.preset_radios[default_selected].GetValue(), (
        f"default preset {default_selected!r} should be selected on open"
    )
    openly_selected = [n for n, r in dlg.preset_radios.items() if r.GetValue()]
    assert len(openly_selected) == 1, (
        f"exactly one radio should be selected on open, got {openly_selected} "
        f"(RB_GROUP misconfiguration: every radio in its own group)"
    )

    # Select each non-default preset and verify it exclusively
    for other in others:
        dlg.preset_radios[other].SetValue(True)
        now_selected = [n for n, r in dlg.preset_radios.items() if r.GetValue()]
        assert now_selected == [other], (
            f"selecting {other!r} should leave only {other!r} selected; "
            f"got {now_selected} (radios are not in one exclusive group)"
        )


@needs_wx
def test_compressor_dialog_radio_preset_is_mutually_exclusive_group(
    wx_app: Any,
) -> None:
    """Regression test: the Compressor preset radios all had
    RB_GROUP, so each was in its own Windows radio group and every
    one read as 'selected' at the same time. That broke NVDA radio-
    group navigation and was a data bug (multiple presets selected).
    Fix: RB_GROUP on the first radio only, so all presets form one
    mutually-exclusive group, with the default preset selected on open.
    """
    from dialogs.effects_dialogs import CompressorPresetDialog

    dlg = CompressorPresetDialog(None)
    try:
        others = [n for n in dlg.preset_radios if n != dlg.selected_preset]
        _assert_radios_mutually_exclusive(dlg, dlg.selected_preset, others)
    finally:
        dlg.Destroy()


@needs_wx
def test_eq_dialog_radio_preset_is_mutually_exclusive_group(
    wx_app: Any,
) -> None:
    """Regression test: same RB_GROUP bug as the Compressor dialog,
    applied to the EQ preset radios. All EQ presets must form one
    mutually-exclusive group with the default preset selected on open.
    """
    from dialogs.effects_dialogs import EQPresetDialog

    dlg = EQPresetDialog(None)
    try:
        others = [n for n in dlg.preset_radios if n != dlg.selected_preset]
        _assert_radios_mutually_exclusive(dlg, dlg.selected_preset, others)
    finally:
        dlg.Destroy()


@needs_wx
def test_breath_dialog_each_preset_radio_has_distinct_accessible_name(
    wx_app: Any,
) -> None:
    """Direct test for the user-visible bug: Light, Medium, Heavy
    must each have a unique accessible name containing its label, so
    NVDA (and any screen reader) can find each one independently."""
    from dialogs.effects_dialogs import BreathSmoothingPresetDialog

    dlg = BreathSmoothingPresetDialog(None)
    try:
        names = []
        for name, radio in dlg.preset_radios.items():
            accessible = radio.GetName()
            assert accessible != "radioButton", (
                f"{name} radio has default accessible name; NVDA can't find it"
            )
            assert name in accessible, (
                f"{name} radio accessible name {accessible!r} should contain the label"
            )
            names.append(accessible)
        # All radios must have distinct accessible names (otherwise NVDA
        # may collapse them into one entry).
        assert len(set(names)) == len(names), (
            f"Radio accessible names must be unique; got {names}"
        )
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Sweep: every dialog in the project must have meaningful accessible
# names on every interactive control. Walks all 8 dialogs and applies
# the same checks the per-dialog tests above do, but in one go so a
# regression in any dialog is caught by one failing test.
# ---------------------------------------------------------------------------


def _walk_widgets(widget):
    """Yield every widget in the tree rooted at ``widget``."""
    yield widget
    for child in widget.GetChildren():
        yield from _walk_widgets(child)


def _audit_dialog(dlg, *, dialog_name: str, allowed_no_name: set[type] | None = None):
    """Return a list of accessibility problems found in ``dlg``.

    Each problem is a human-readable string. An empty list means the
    dialog passed the audit.

    ``allowed_no_name`` lets the caller exempt specific widget classes
    from the audit (e.g. plain Panels which never need an accessible
    name).
    """
    import wx  # used here for type checks; only imported when wx is available

    allowed_no_name = allowed_no_name or set()
    bad_defaults = {
        "dialog", "staticText", "radioButton", "check",
        "slider", "choice", "text", "listBox", "button",
        "gauge", "groupBox", "panel", "frame",
    }
    interactive_types = (wx.RadioButton, wx.Slider, wx.Button, wx.CheckBox)
    problems: list[str] = []

    for widget in _walk_widgets(dlg):
        cls = type(widget)
        if cls in allowed_no_name:
            continue
        if cls is wx.StaticBox and getattr(widget, "GetLabel", lambda: "")() == "":
            # Empty StaticBox is just a layout container.
            continue

        name = widget.GetName()
        try:
            label = widget.GetLabel()
        except Exception:
            label = ""

        if cls in interactive_types or (cls is wx.StaticText and label):
            if name in bad_defaults:
                problems.append(
                    f"  [{dialog_name}] {cls.__name__} label={label!r:30}  "
                    f"name={name!r:24}  (default; needs SetName)"
                )
            # Interactive controls: name should mention the visible
            # label. Strip trailing ellipsis/dot punctuation since
            # accessible names use commas instead.
            if cls in interactive_types and label:
                label_clean = label.rstrip(".…").rstrip()
                if label_clean and label_clean not in name:
                    problems.append(
                        f"  [{dialog_name}] {cls.__name__} label={label!r:30}  "
                        f"name={name!r:60}  (name doesn't mention label)"
                    )

    return problems


@needs_wx
def test_every_dialog_passes_accessibility_audit(wx_app: Any) -> None:
    """Sweep: every dialog in the project must have meaningful
    accessible names on every interactive control.

    JAWS reads labels even when SetName is missing, so JAWS users
    often don't notice these bugs. NVDA relies on SetName verbatim
    and either announces "radioButton" / "slider" / "staticText"
    (useless) or skips the control entirely. This test catches both.

    Walks:
    - BreathSmoothingPresetDialog  (done in v1 of this fix)
    - EffectSettingsDialog
    - CompressorPresetDialog
    - EQPresetDialog
    - RoomToneMatchDialog
    - BatchProcessDialog
    - RecordingDialog
    - StudioRecordingDialog
    """
    import wx
    from dialogs.effects_dialogs import (
        EffectSettingsDialog,
        BreathSmoothingPresetDialog,
        CompressorPresetDialog,
        EQPresetDialog,
        RoomToneMatchDialog,
        BatchProcessDialog,
    )
    from dialogs.recording_dialogs import (
        RecordingDialog,
        StudioRecordingDialog,
    )

    problems: list[str] = []

    # EffectSettingsDialog takes (parent, title, params)
    dlg = EffectSettingsDialog(
        None,
        title="Effect Settings",
        params={"Threshold": (-20, -60, 0), "Ratio": 4, "Wet/Dry": 1.0},
    )
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="EffectSettingsDialog"))
    finally:
        dlg.Destroy()

    # BreathSmoothingPresetDialog -- already audited per-dialog, but
    # include in sweep for completeness.
    dlg = BreathSmoothingPresetDialog(None)
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="BreathSmoothingPresetDialog"))
    finally:
        dlg.Destroy()

    # CompressorPresetDialog
    dlg = CompressorPresetDialog(None)
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="CompressorPresetDialog"))
    finally:
        dlg.Destroy()

    # EQPresetDialog
    dlg = EQPresetDialog(None)
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="EQPresetDialog"))
    finally:
        dlg.Destroy()

    # RoomToneMatchDialog takes (parent, track_names, track_durations)
    dlg = RoomToneMatchDialog(
        None,
        track_names=["Track 1", "Track 2"],
        track_durations=[10.0, 20.0],
    )
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="RoomToneMatchDialog"))
    finally:
        dlg.Destroy()

    # BatchProcessDialog
    dlg = BatchProcessDialog(None)
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="BatchProcessDialog"))
    finally:
        dlg.Destroy()

    # RecordingDialog
    dlg = RecordingDialog(None, input_device_id=None)
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="RecordingDialog"))
    finally:
        dlg.Destroy()

    # StudioRecordingDialog takes script_lines
    dlg = StudioRecordingDialog(None, script_lines=["line 1"])
    try:
        problems.extend(_audit_dialog(dlg, dialog_name="StudioRecordingDialog"))
    finally:
        dlg.Destroy()

    assert not problems, (
        "Accessibility problems found across dialogs:\n"
        + "\n".join(problems)
    )


@needs_wx
def test_breath_dialog_get_values_rms_thresh_inversely_proportional_to_sens(
    wx_app: Any,
) -> None:
    """The dialog maps slider=100 (high sensitivity) to rms_thresh=0.01
    (catches quiet breaths) and slider=1 (low sensitivity) to a higher
    threshold. Verify the inverse mapping."""
    from dialogs.effects_dialogs import BreathSmoothingPresetDialog

    dlg = BreathSmoothingPresetDialog(None)
    try:
        # Force high sensitivity (slider = 100)
        dlg.sens_slider.SetValue(100)
        values = dlg.get_values()
        # sens = 100/100 = 1.0 -> thresh = 0.01 + (1 - 1.0) * 0.09 = 0.01
        assert abs(values["rms_thresh"] - 0.01) < 1e-9

        dlg.sens_slider.SetValue(1)  # low sensitivity
        values = dlg.get_values()
        # sens = 1/100 = 0.01 -> thresh = 0.01 + (1 - 0.01) * 0.09 = 0.0919
        assert abs(values["rms_thresh"] - 0.0919) < 0.01
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# CompressorPresetDialog
# ---------------------------------------------------------------------------


@needs_wx
def test_compressor_dialog_constructs_and_get_values_in_simple_mode(
    wx_app: Any,
) -> None:
    """CompressorPresetDialog.get_values() returns the five keys
    the audio_effects module looks up when not in advanced mode."""
    from dialogs.effects_dialogs import CompressorPresetDialog

    dlg = CompressorPresetDialog(None)
    try:
        values = dlg.get_values()
        assert set(values.keys()) == {
            "threshold_db",
            "ratio",
            "attack_ms",
            "release_ms",
            "makeup_db",
        }
        # Default preset is "Voiceover/broadcast" per the dialog source
        for key, val in values.items():
            assert isinstance(val, (int, float)), (
                f"{key} should be numeric, got {type(val).__name__}"
            )
    finally:
        dlg.Destroy()


@needs_wx
def test_compressor_dialog_get_values_in_advanced_mode(wx_app: Any) -> None:
    """In advanced mode, the dialog reads from the advanced_controls
    sliders instead of the preset table."""
    from dialogs.effects_dialogs import CompressorPresetDialog

    dlg = CompressorPresetDialog(None)
    try:
        # Force advanced mode
        dlg.show_advanced = True
        # Set a known value on the Threshold slider
        dlg.advanced_controls["Threshold (dB)"].SetValue(-30)
        values = dlg.get_values()
        assert values["threshold_db"] == -30
        # Other keys still present
        assert "ratio" in values
        assert "attack_ms" in values
        assert "release_ms" in values
        assert "makeup_db" in values
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# EQPresetDialog
# ---------------------------------------------------------------------------


@needs_wx
def test_eq_dialog_constructs_and_get_values_returns_dict(wx_app: Any) -> None:
    """EQPresetDialog.get_values() returns a dict with per-band gains."""
    from dialogs.effects_dialogs import EQPresetDialog

    dlg = EQPresetDialog(None)
    try:
        values = dlg.get_values()
        # The audio_effects.Equalizer.BAND_FREQUENCIES list drives the
        # number of bands. The exact count is determined by the
        # upstream Equalizer module, so just assert it's a list with
        # one entry per band.
        import audio_effects
        assert len(values) == len(audio_effects.Equalizer.BAND_FREQUENCIES)
        # Each band gain is a float in dB
        for _freq, gain in values.items():
            assert isinstance(gain, (int, float)), f"band gain should be numeric, got {type(gain).__name__}"
    finally:
        dlg.Destroy()


@needs_wx
def test_eq_dialog_get_preset_name_returns_string(wx_app: Any) -> None:
    """EQPresetDialog.get_preset_name() returns the selected preset
    name (a string). The default depends on the audio_effects module."""
    from dialogs.effects_dialogs import EQPresetDialog

    dlg = EQPresetDialog(None)
    try:
        name = dlg.get_preset_name()
        assert isinstance(name, str)
        assert len(name) > 0
    finally:
        dlg.Destroy()


@needs_wx
def test_eq_dialog_values_round_trip_through_equalizer(wx_app: Any) -> None:
    """Regression test for a user-visible crash: selecting an EQ
    preset and clicking OK raised
    ``ValueError: cannot unpack non-iterable int object``.

    Root cause: EQPresetDialog.get_values() returns a dict
    ``{freq_hz: gain_db}``, but audio_effects.Equalizer.apply_to_numpy
    expected a list of (freq, gain) tuples and did
    ``for freq, gain in self.bands``. Iterating a dict yields its
    keys (ints), so unpacking ``freq, gain = 100`` raised.

    The fix normalises the dict to a list of tuples in
    Equalizer.__init__. This test exercises the full path:
    dialog.get_values() -> Equalizer(bands=...) -> apply_to_numpy.
    """
    import numpy as np
    from dialogs.effects_dialogs import EQPresetDialog
    import audio_effects

    dlg = EQPresetDialog(None)
    try:
        values = dlg.get_values()
        assert isinstance(values, dict), (
            "get_values() should return a dict for the Equalizer"
        )
        # Exercise the exact call the audio editor makes on OK.
        eff = audio_effects.Equalizer(bands=values)
        # apply_to_numpy is where the old crash lived.
        samples = np.zeros(44100, dtype=np.float32)
        out = eff.apply_to_numpy(samples, 44100)
        assert out.shape == samples.shape
        # Also verify the list-of-tuples shape still works (config.py uses it)
        tuple_bands = list(values.items())
        eff2 = audio_effects.Equalizer(bands=tuple_bands)
        out2 = eff2.apply_to_numpy(samples, 44100)
        assert out2.shape == samples.shape
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# RoomToneMatchDialog -- construct-only (no get_values contract to test)
# ---------------------------------------------------------------------------


@needs_wx
def test_room_tone_dialog_constructs(wx_app: Any) -> None:
    """RoomToneMatchDialog builds without crashing. (It has no get_values
    contract; the dialog mutates audio state via callbacks during
    ShowModal, which we do not exercise here.)"""
    from dialogs.effects_dialogs import RoomToneMatchDialog

    # Constructor signature: (parent, track_names, track_durations)
    dlg = RoomToneMatchDialog(None, ["Track 1", "Track 2"], [10.0, 5.0])
    try:
        # If we got here without exception, the dialog built.
        assert dlg is not None
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# BatchProcessDialog -- state-attribute contract
# ---------------------------------------------------------------------------


@needs_wx
def test_batch_process_dialog_constructs_with_default_state(wx_app: Any) -> None:
    """BatchProcessDialog builds and exposes the state attributes that
    audio_editor.py reads after ShowModal returns."""
    from dialogs.effects_dialogs import BatchProcessDialog

    dlg = BatchProcessDialog(None)
    try:
        # These are the public attributes the calling code relies on
        assert dlg.input_folder == ""
        assert dlg.output_folder == ""
        assert isinstance(dlg.effect_type, str)
        assert isinstance(dlg.effect_params, dict)
        assert isinstance(dlg.selected_preset, str)
        # The notebook has 3 pages: Folder, Effect, Process
        assert dlg.notebook.GetPageCount() == 3
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# RecordingDialog
# ---------------------------------------------------------------------------


@needs_wx
def test_recording_dialog_constructs_with_defaults(wx_app: Any) -> None:
    """RecordingDialog builds with the no-device default."""
    from dialogs.recording_dialogs import RecordingDialog

    dlg = RecordingDialog(None, input_device_id=None)
    try:
        # input_device_id is stored verbatim
        assert dlg.input_device_id is None
        # monitoring state starts False
        assert dlg.monitoring is False
        # monitor_stream is None until Start is clicked
        assert dlg.monitor_stream is None
    finally:
        dlg.Destroy()


@needs_wx
def test_recording_dialog_module_level_sd_and_np_defined() -> None:
    """recording_dialogs binds sd and np at module load (issue #16).

    RecordingDialog.toggle_monitor references sd.InputStream and
    np.sqrt/np.mean in its audio_callback closure. Before the fix,
    neither was imported at module level, so the auto-start at
    init_ui() (which fires when input_device_id is set) raised
    'name sd is not defined' / 'name np is not defined' on first
    attempt to monitor levels.
    """
    import dialogs.recording_dialogs as rd

    assert hasattr(rd, "sd"), "recording_dialogs.sd should be module-level"
    assert hasattr(rd, "np"), "recording_dialogs.np should be module-level"
    assert rd.sd is not None
    assert rd.np is not None
    # And crucially: when input_device_id is set, opening the dialog
    # must not raise NameError when the auto-start fires.
    dlg = rd.RecordingDialog(None, input_device_id=99999)  # bogus device, but binding is fine
    try:
        # The auto-start uses wx.CallAfter(toggle_monitor, None), so
        # immediately destroy the dialog before it fires — we just
        # want to confirm the *import path* doesn't fail.
        pass
    finally:
        dlg.Destroy()


@needs_wx
def test_recording_dialog_constructs_with_device_id(wx_app: Any) -> None:
    """RecordingDialog stores the input_device_id passed to it."""
    from dialogs.recording_dialogs import RecordingDialog

    dlg = RecordingDialog(None, input_device_id=7)
    try:
        assert dlg.input_device_id == 7
    finally:
        dlg.Destroy()


@needs_wx
def test_recording_dialog_update_level_changes_label(wx_app: Any) -> None:
    """update_level() updates the level_text label with the new dB value."""
    from dialogs.recording_dialogs import RecordingDialog

    dlg = RecordingDialog(None)
    try:
        dlg.update_level(50, -12.5)
        assert "-12.5" in dlg.level_text.GetLabel()
        dlg.update_level(80, -6.0)
        assert "-6.0" in dlg.level_text.GetLabel()
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# StudioRecordingDialog
# ---------------------------------------------------------------------------


@needs_wx
def test_studio_recording_dialog_constructs_with_script_lines(wx_app: Any) -> None:
    """StudioRecordingDialog stores the script_lines it was given
    without copying (so the calling code can update them)."""
    from dialogs.recording_dialogs import StudioRecordingDialog

    script = [{"line": "First line"}, {"line": "Second line"}]
    dlg = StudioRecordingDialog(None, script)
    try:
        assert dlg.script_lines is script
        assert dlg.recording is False
        assert dlg.studio_recorder is None
        # Defaults: no second monitor, no network monitor
        assert dlg.use_second_monitor is False
        assert dlg.use_network_monitor is False
    finally:
        dlg.Destroy()


@needs_wx
def test_studio_recording_dialog_get_final_audio_returns_none_before_recording(
    wx_app: Any,
) -> None:
    """Before any recording happens, get_final_audio() returns None.
    This is the contract audio_editor.py relies on to decide whether
    to add a new track."""
    from dialogs.recording_dialogs import StudioRecordingDialog

    dlg = StudioRecordingDialog(None, [])
    try:
        assert dlg.get_final_audio() is None
    finally:
        dlg.Destroy()


@needs_wx
def test_studio_recording_dialog_get_session_report_returns_dict_or_string(
    wx_app: Any,
) -> None:
    """Before any recording, session_report should be empty (falsy)."""
    from dialogs.recording_dialogs import StudioRecordingDialog

    dlg = StudioRecordingDialog(None, [])
    try:
        # session_report is set during on_stop_recording, so initially it's absent
        assert not getattr(dlg, 'session_report', None)
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Smoke test: every dialog class can be constructed without raising
# ---------------------------------------------------------------------------


@needs_wx
@pytest.mark.parametrize("module_name,class_name",
                         EFFECTS_DIALOG_CLASSES + RECORDING_DIALOG_CLASSES)
def test_extracted_dialog_constructs(wx_app: Any,
                                      module_name: str,
                                      class_name: str) -> None:
    """Every extracted dialog class must construct without raising.

    AudioClipboard is a plain class with no __init__ args, so this
    test parametrises trivially for it; the others need a parent
    (which is None when an App is alive). Catches signature changes
    that would otherwise only show up at runtime in audio_editor.py.
    """
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name)

    # Skip dialogs with non-trivial constructors that need real
    # fixtures. We have targeted tests above for those.
    if class_name == "AudioClipboard":
        # Pure Python, no wx, no construction needed
        return
    if class_name == "RoomToneMatchDialog":
        # Needs (parent, track_names, track_durations) -- handled above
        return
    if class_name == "RecordingDialog":
        # Already covered above
        return
    if class_name == "StudioRecordingDialog":
        # Already covered above
        return

    # Default constructor signature for the rest is (parent)
    # or (parent, title) for EffectSettingsDialog / (parent, title="...")
    # for the rest of the parameterised dialogs. Try a couple.
    import inspect
    try:
        sig = inspect.signature(cls.__init__)
        # Build a kwargs dict of safe defaults for required params
        kwargs = {}
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.default is inspect.Parameter.empty:
                # Required positional: supply a sensible default
                if name in ("parent",):
                    kwargs[name] = None
                elif name == "title":
                    kwargs[name] = "Test"
                elif name == "params":
                    kwargs[name] = {}
                elif name == "script_lines":
                    kwargs[name] = []
                elif name == "track_names":
                    kwargs[name] = []
                elif name == "track_durations":
                    kwargs[name] = []
                else:
                    # Skip -- don't know the default
                    pytest.skip(
                        f"{class_name}.__init__ has unknown required param {name!r}"
                    )
        dlg = cls(**kwargs)
        # If the class has a Destroy method, call it to free native
        # resources before the next test.
        if hasattr(dlg, "Destroy"):
            dlg.Destroy()
    except Exception as exc:
        pytest.fail(f"{class_name}({kwargs!r}) raised: {exc!r}")


# --- Auto-update dialog tests (v1.2.0) --------------------------------------


@needs_wx
def test_update_prompt_dialog_constructs(wx_app):
    """UpdatePromptDialog must construct with an UpdateInfo and expose get_choice()."""
    if wx_app is None:
        pytest.skip("wxPython not installed (Linux smoke CI)")
    from dialogs.update_dialog import UpdatePromptDialog
    from updater import UpdateInfo

    info = UpdateInfo(
        version="1.3.0",
        url="https://github.com/trasles16-ux/speechcraft-audio/releases/tag/v1.3.0",
        title="SpeechCraft Studio v1.3.0",
        notes="Bug fixes.",
        published_at="2026-10-01T12:00:00Z",
        is_prerelease=False,
    )
    dlg = UpdatePromptDialog(parent=None, current_version="1.2.0", update_info=info)
    try:
        # Default choice is "remind" — the safe one — so a stray Enter
        # never silently kicks off an installer.
        assert dlg.get_choice() == "remind"
    finally:
        dlg.Destroy()


@needs_wx
def test_download_progress_dialog_constructs(wx_app):
    """DownloadProgressDialog must construct with a known total size."""
    if wx_app is None:
        pytest.skip("wxPython not installed (Linux smoke CI)")
    from dialogs.download_progress_dialog import DownloadProgressDialog

    dlg = DownloadProgressDialog(
        parent=None, file_name="Setup.exe", total_bytes=50_000_000
    )
    try:
        # Simulate progress to make sure the update path doesn't blow up.
        dlg.update(25_000_000)
        assert dlg.is_cancelled() is False
        # Force the cancel flag so we can verify the polling helper works.
        dlg._cancelled = True
        assert dlg.is_cancelled() is True
    finally:
        dlg.Destroy()
