"""Tests for piper_tts_engine + transcription wiring to feature_manager."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Piper engine ─────────────────────────────────────────────────────────

def test_piper_engine_uses_gb_voices():
    """PiperTTSEngine should expose en_GB voices backed by feature_manager."""
    import piper_tts_engine

    voices = piper_tts_engine.PiperTTSEngine.get_voices()
    assert "English GB (Female — Cori)" in voices
    assert "English GB (Male — Alan)" in voices
    # Each maps to a real feature_manager asset
    for info in voices.values():
        assert info["feature"] == "piper_tts"
        assert info["asset"] in ("en_GB.cori", "en_GB.alan")


def test_piper_engine_resolves_voice_files_from_feature_manager(tmp_path, monkeypatch):
    """When feature_manager says an asset is ready, _resolve_voice_files
    returns the on-disk paths without downloading."""
    import feature_manager
    import piper_tts_engine

    # Build a fake on-disk layout
    asset_dir = tmp_path / "piper_tts" / "en_GB.cori"
    asset_dir.mkdir(parents=True)
    model = asset_dir / "model"
    config = asset_dir / "config"
    model.write_text("onnx-fake")
    config.write_text("{}")

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **k: True)

    engine = piper_tts_engine.PiperTTSEngine.__new__(
        piper_tts_engine.PiperTTSEngine)
    engine.models_dir = tmp_path

    model_path, config_path = engine._resolve_voice_files("English GB (Female — Cori)")
    assert model_path == model
    assert config_path == config


def test_piper_engine_default_models_dir_points_at_prefs():
    """Default models_dir lives under PREFS_DIR, not the CWD."""
    import piper_tts_engine
    import prefs

    p = piper_tts_engine._default_models_dir()
    assert str(p).startswith(str(prefs.PREFS_DIR))
    assert p.name == "feature_assets"


# ── Whisper local model resolution ───────────────────────────────────────

def test_resolve_local_whisper_returns_none_when_not_ready(tmp_path, monkeypatch):
    import feature_manager
    import transcription

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **k: False)
    monkeypatch.setattr(feature_manager, "load_feature_state", lambda *a, **k: {})
    result = transcription._resolve_local_whisper_model("tiny")
    assert result is None


def test_resolve_local_whisper_maps_unknown_size_to_none():
    """Model sizes not in the registry (small/medium/large) fall through."""
    import transcription
    result = transcription._resolve_local_whisper_model("small")
    assert result is None


def test_resolve_local_whisper_returns_dir_when_ready(tmp_path, monkeypatch):
    """When feature_manager reports ready + a valid model.bin path, the
    directory is returned for WhisperModel to load."""
    import feature_manager
    import transcription

    model_bin = tmp_path / "local_transcription" / "tiny.en" / "model.bin"
    model_bin.parent.mkdir(parents=True)
    model_bin.write_bytes(b"fake")

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **k: True)
    monkeypatch.setattr(
        feature_manager, "load_feature_state",
        lambda *a, **k: {"local_transcription/tiny.en":
                         {"ready": True,
                          "paths": {"model.bin": str(model_bin)}}})
    result = transcription._resolve_local_whisper_model("tiny")
    assert result is not None
    assert result == str(model_bin.parent)
