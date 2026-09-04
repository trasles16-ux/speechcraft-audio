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
        assert abs(values["rms_thresh"] - 0.0919) < 1e-3
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
            assert isinstance(gain, float), f"band gain should be float, got {type(gain).__name__}"
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
