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
@pytest.mark.parametrize("module_name,class_name", EFFECTS_DIALOG_CLASSES)
def test_effects_dialog_classes_importable(
    module_name: str, class_name: str
) -> None:
    """Every dialog extracted to dialogs/effects_dialogs.py must be
    importable from there. If a class is renamed in one place but
    not the other, this test fails -- which is exactly the failure
    mode that a 5148-line audio_editor.py would have hidden."""
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name, None)
    assert cls is not None, (
        f"{module_name}.{class_name} is missing. "
        f"Either the class was renamed (update this test), or the "
        f"audio_editor.py extraction dropped a class."
    )


@pytest.mark.parametrize("module_name,class_name", EFFECTS_DIALOG_CLASSES)
def test_audio_editor_imports_extracted_classes(
    module_name: str, class_name: str
) -> None:
    """audio_editor.py must re-export every extracted class. Catches
    the case where someone moves a class into effects_dialogs.py
    but forgets to add it to the ``from dialogs.effects_dialogs
    import (...)`` line in audio_editor.py."""
    # Importing audio_editor pulls in wx + numpy + the full app --
    # we cannot do that without wx installed, so gate this on wx.
    if not _wx_available():
        pytest.skip("wxPython not installed")
    import audio_editor

    assert hasattr(audio_editor, class_name), (
        f"audio_editor.{class_name} is missing. "
        f"The extraction moved the class to dialogs.effects_dialogs "
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
