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


def test_piper_executable_is_a_registered_asset():
    """The Piper executable itself is a feature_manager asset so the
    lazy-install flow can offer to download it on Core installs."""
    import feature_manager

    # The asset exists in the registry
    assert "executable" in feature_manager.list_assets("piper_tts")
    asset = feature_manager.get_asset("piper_tts", "executable")
    assert asset.feature == "piper_tts"
    assert asset.asset_name == "executable"
    # It's marked downloadable
    assert feature_manager.is_downloadable("piper_tts", "executable") is True
    # The URL points at a real Piper release (not a TODO placeholder)
    raw = feature_manager.FEATURE_ASSETS["piper_tts"]["executable"]
    for f in raw["files"]:
        assert not f["url"].startswith("TODO_")
        assert "rhasspy/piper" in f["url"]


def test_piper_engine_find_piper_returns_none_when_missing(tmp_path, monkeypatch):
    """With nothing on disk, CWD-empty, and no PATH hit, _find_piper
    returns None (it's the caller's job to raise / prompt)."""
    import feature_manager
    import piper_tts_engine

    monkeypatch.setattr("piper_tts_engine.os.path.exists", lambda p: False)
    monkeypatch.setattr(
        feature_manager, "is_ready", lambda *a, **kw: False
    )

    # Stub out the PATH-lookup branch (subprocess.run) so the test
    # doesn't depend on whatever piper happens to be on the test box.
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 1})(),
    )

    engine = piper_tts_engine.PiperTTSEngine.__new__(
        piper_tts_engine.PiperTTSEngine
    )
    engine.models_dir = tmp_path
    engine._parent = None
    engine._allow_prompt = False

    assert engine._find_piper() is None


def test_piper_engine_init_raises_clean_error_when_no_prompt(
    tmp_path, monkeypatch,
):
    """With allow_prompt=False, a missing piper.exe raises the legacy
    RuntimeError so tests + headless callers don't see a UI."""
    import feature_manager
    import piper_tts_engine

    monkeypatch.setattr("piper_tts_engine.os.path.exists", lambda p: False)
    monkeypatch.setattr(
        feature_manager, "is_ready", lambda *a, **kw: False
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 1})(),
    )

    with pytest.raises(RuntimeError, match="Piper executable not found"):
        piper_tts_engine.PiperTTSEngine(
            models_dir=str(tmp_path),
            parent=None,
            allow_prompt=False,
        )


def test_piper_engine_find_piper_prefers_feature_manager(tmp_path, monkeypatch):
    """If the lazy-installed piper.exe exists at the feature_manager
    path, _find_piper returns it instead of falling back to PATH/CWD."""
    import feature_manager
    import piper_tts_engine

    # Plant a fake piper.exe where feature_manager expects it.
    exe_dir = tmp_path / "feature_assets" / "piper_tts" / "executable"
    exe_dir.mkdir(parents=True)
    fake = exe_dir / "piper.exe"
    fake.write_bytes(b"FAKE")

    monkeypatch.setattr(
        feature_manager, "is_ready",
        lambda *a, **kw: True,
    )
    # v1.3.7: the engine reads feature_manager.ASSETS_ROOT (which used
    # to be derived from DEFAULT_STATE_FILE.parent); point it at the
    # feature_assets tree inside tmp where the fake piper.exe is
    # planted.
    monkeypatch.setattr(feature_manager, "ASSETS_ROOT", tmp_path / "feature_assets")

    engine = piper_tts_engine.PiperTTSEngine.__new__(
        piper_tts_engine.PiperTTSEngine
    )
    engine.models_dir = tmp_path
    engine._parent = None
    engine._allow_prompt = False

    found = engine._find_piper()
    assert found == str(fake.resolve())


def test_piper_engine_resolve_voice_calls_prompt_when_missing(tmp_path, monkeypatch):
    """When the voice isn't on disk and a parent is supplied, the engine
    goes through prompt_and_install (not silent ensure_ready)."""
    import feature_manager
    import piper_tts_engine

    # is_ready returns False so the engine has to ask for a download.
    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **kw: False)
    # is_downloadable returns True so the engine doesn't short-circuit.
    monkeypatch.setattr(
        feature_manager, "is_downloadable", lambda *a, **kw: True,
    )

    prompt_called_with: list[tuple[str, str]] = []

    def _fake_prompt(feature, asset_name, *, parent=None, **kw):
        prompt_called_with.append((feature, asset_name))
        # Plant the files so the engine thinks the install succeeded.
        asset_dir = tmp_path / feature / asset_name
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "model").write_bytes(b"FAKE")
        (asset_dir / "config").write_bytes(b"{}")
        return True

    monkeypatch.setattr(
        "dialogs.lazy_install.prompt_and_install", _fake_prompt,
    )

    engine = piper_tts_engine.PiperTTSEngine.__new__(
        piper_tts_engine.PiperTTSEngine
    )
    engine.models_dir = tmp_path
    engine._parent = object()  # any truthy wx-window stand-in
    engine._allow_prompt = True

    model_path, config_path = engine._resolve_voice_files(
        "English GB (Female — Cori)",
        parent=engine._parent,
        allow_prompt=True,
    )
    assert prompt_called_with == [("piper_tts", "en_GB.cori")]
    assert model_path.exists()
    assert config_path.exists()


def test_piper_engine_resolve_voice_silent_when_no_parent(tmp_path, monkeypatch):
    """With allow_prompt=False the engine uses the legacy silent path:
    calls feature_manager.ensure_ready directly, no UI."""
    import feature_manager
    import piper_tts_engine

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **kw: False)
    monkeypatch.setattr(
        feature_manager, "is_downloadable", lambda *a, **kw: True,
    )

    ensure_called_with: list[tuple[str, str]] = []

    def _fake_ensure(feature, asset_name, **kw):
        ensure_called_with.append((feature, asset_name))
        # Plant the files so the post-check passes.
        asset_dir = tmp_path / feature / asset_name
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "model").write_bytes(b"FAKE")
        (asset_dir / "config").write_bytes(b"{}")
        return True

    monkeypatch.setattr(feature_manager, "ensure_ready", _fake_ensure)

    engine = piper_tts_engine.PiperTTSEngine.__new__(
        piper_tts_engine.PiperTTSEngine
    )
    engine.models_dir = tmp_path
    engine._parent = None
    engine._allow_prompt = False

    engine._resolve_voice_files(
        "English GB (Female — Cori)",
        parent=None,
        allow_prompt=False,
    )
    assert ensure_called_with == [("piper_tts", "en_GB.cori")]


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


def test_resolve_local_whisper_calls_prompt_when_missing(tmp_path, monkeypatch):
    """v1.3.5: when the model isn't on disk and a parent is supplied,
    _resolve_local_whisper_model asks the user via prompt_and_install
    before falling back to faster-whisper's built-in lookup."""
    import feature_manager
    import transcription

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **k: False)
    monkeypatch.setattr(feature_manager, "load_feature_state", lambda *a, **k: {})

    prompt_calls: list[tuple[str, str]] = []

    def _fake_prompt(feature, asset_name, *, parent=None, **kw):
        prompt_calls.append((feature, asset_name))
        # Plant a fake model.bin so is_ready flips to True on re-check.
        model_bin = tmp_path / feature / asset_name / "model.bin"
        model_bin.parent.mkdir(parents=True, exist_ok=True)
        model_bin.write_bytes(b"FAKE")
        return True

    monkeypatch.setattr(
        "dialogs.lazy_install.prompt_and_install", _fake_prompt,
    )

    # After the fake prompt returns, _resolve should see the planted
    # file and return its parent dir.
    def _ready_after_prompt(feature, asset_name, **kw):
        return (feature, asset_name) in [
            ("local_transcription", "tiny.en"),
        ]

    # Re-bind is_ready to reflect the planted file (it was called once
    # at the top, returning False; the second call needs to be True).
    call_count = {"n": 0}
    def _is_ready(*a, **kw):
        call_count["n"] += 1
        return call_count["n"] >= 2
    monkeypatch.setattr(feature_manager, "is_ready", _is_ready)

    def _state_after_prompt(*a, **kw):
        return {"local_transcription/tiny.en":
                {"ready": True, "paths": {"model.bin":
                    str(tmp_path / "local_transcription" / "tiny.en" / "model.bin")}}}
    monkeypatch.setattr(feature_manager, "load_feature_state", _state_after_prompt)

    result = transcription._resolve_local_whisper_model("tiny", parent=object())
    assert prompt_calls == [("local_transcription", "tiny.en")]
    assert result == str(tmp_path / "local_transcription" / "tiny.en")


def test_resolve_local_whisper_silent_when_no_parent(monkeypatch):
    """No parent → no prompt → returns None (fall back to faster-whisper's
    built-in HF lookup). Same as the v1.3.0 behaviour."""
    import feature_manager
    import transcription

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **k: False)
    monkeypatch.setattr(feature_manager, "load_feature_state", lambda *a, **k: {})

    # If prompt_and_install is somehow called, fail loudly so the test
    # catches a regression where the silent path started prompting.
    def _explode(*a, **kw):
        raise AssertionError("prompt_and_install should not be called when parent is None")

    import dialogs.lazy_install
    monkeypatch.setattr(dialogs.lazy_install, "prompt_and_install", _explode)

    result = transcription._resolve_local_whisper_model("tiny", parent=None)
    assert result is None


def test_resolve_local_whisper_returns_none_when_prompt_declined(monkeypatch):
    """If the user clicks No on the download prompt, return None — we
    don't try to use a model that isn't there."""
    import feature_manager
    import transcription

    monkeypatch.setattr(feature_manager, "is_ready", lambda *a, **k: False)
    monkeypatch.setattr(feature_manager, "load_feature_state", lambda *a, **k: {})

    def _decline(feature, asset_name, *, parent=None, **kw):
        return False

    monkeypatch.setattr("dialogs.lazy_install.prompt_and_install", _decline)

    result = transcription._resolve_local_whisper_model("tiny", parent=object())
    assert result is None
