"""Regression tests: pedalboard effects must stay disabled on Core builds.

Bug #4 (v1.3.2): on a Core build, ``audio_effects`` is a
DummyModule (pedalboard/scipy aren't bundled), but the feature
gate only checked the user's *flag* — so "Room Remover" stayed
enabled and clicking it popped "pedalboard not installed".

Fix: the gate ANDs the flag with actual module availability, and
shows a one-time hint (persisted in setup.json) pointing at the
Full edition.
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


class _FakeItem:
    """Stand-in for a wx menu item; records Enable() calls."""

    def __init__(self):
        self.enabled = True

    def Enable(self, enabled: bool):
        self.enabled = bool(enabled)

    def __bool__(self):
        return True


def _make_frame(monkeypatch, tmp_path, *, audio_effects, pedalboard_flag=True):
    """Build a bare object with just the attributes the gate touches."""
    import audio_editor
    from feature_flags import FeatureFlags

    prefs_file = tmp_path / "setup.json"
    monkeypatch.setattr("prefs.PREFS_FILE", prefs_file)
    monkeypatch.setattr("prefs.PREFS_DIR", tmp_path)
    monkeypatch.setattr(
        "feature_flags.load_feature_flags",
        lambda prefs_file=None: FeatureFlags(
            pedalboard_effects=pedalboard_flag,
        ),
    )

    hint_shown: list = []
    monkeypatch.setattr(
        audio_editor,
        "_show_core_effects_hint_once",
        lambda: hint_shown.append(1),
    )
    monkeypatch.setattr(audio_editor, "audio_effects", audio_effects)

    items = [_FakeItem() for _ in range(5)]

    class Frame:
        transcribe_item = None
        line_placer_item = None
        edge_tts_item = None
        piper_tts_item = None
        edit_mode_item = None
        effects_pedalboard_items = items

    frame = Frame()
    gate = audio_editor.SpeechCraftFrame._apply_feature_gates
    return frame, gate, items, hint_shown


@needs_wx
def test_pedalboard_items_disabled_when_module_missing(wx_app, monkeypatch, tmp_path):
    """Core build (audio_effects is DummyModule) -> items stay off + hint."""
    import audio_editor

    dummy = audio_editor.DummyModule("audio_effects", "pedalboard not installed")
    frame, gate, items, hint_shown = _make_frame(
        monkeypatch, tmp_path, audio_effects=dummy, pedalboard_flag=True
    )
    gate(frame)

    assert all(item.enabled is False for item in items)
    assert hint_shown == [1]


@needs_wx
def test_pedalboard_items_enabled_when_module_present(wx_app, monkeypatch, tmp_path):
    """Full build (real audio_effects) + flag on -> items on, no hint."""
    import audio_editor

    frame, gate, items, hint_shown = _make_frame(
        monkeypatch, tmp_path, audio_effects=audio_editor.audio_effects,
        pedalboard_flag=True,
    )
    gate(frame)

    assert all(item.enabled is True for item in items)
    assert hint_shown == []


@needs_wx
def test_hint_suppressed_when_flag_off(wx_app, monkeypatch, tmp_path):
    """Flag off -> items off, but no hint (user chose not to use them)."""
    import audio_editor

    dummy = audio_editor.DummyModule("audio_effects", "pedalboard not installed")
    frame, gate, items, hint_shown = _make_frame(
        monkeypatch, tmp_path, audio_effects=dummy, pedalboard_flag=False
    )
    gate(frame)

    assert all(item.enabled is False for item in items)
    assert hint_shown == []


def test_hint_persists_once(tmp_path, monkeypatch):
    """core_effects_hint_shown in setup.json prevents repeat hints."""
    import audio_editor
    from prefs import load_prefs

    prefs_file = tmp_path / "setup.json"
    monkeypatch.setattr("prefs.PREFS_FILE", prefs_file)
    monkeypatch.setattr("prefs.PREFS_DIR", tmp_path)

    fired: list = []
    monkeypatch.setattr(
        audio_editor.wx,
        "MessageBox",
        lambda *a, **k: fired.append(1),
    )

    audio_editor._show_core_effects_hint_once()
    assert len(fired) == 1
    assert load_prefs().get("core_effects_hint_shown") is True

    audio_editor._show_core_effects_hint_once()
    assert len(fired) == 1


def test_audio_effects_available_reflects_dummy():
    """_audio_effects_available() is False for DummyModule, True for real."""
    import audio_editor

    real = audio_editor.audio_effects
    try:
        audio_editor.audio_effects = audio_editor.DummyModule(
            "audio_effects", "gone"
        )
        assert audio_editor._audio_effects_available() is False
        audio_editor.audio_effects = real
        assert audio_editor._audio_effects_available() is True
    finally:
        audio_editor.audio_effects = real
