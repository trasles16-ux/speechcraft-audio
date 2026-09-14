"""Tests for feature_manager (pure logic, no wx, no network).

Covers the registry shape, the state file read/write, and the
download path (mocked — no real network in unit tests).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from feature_manager import (
    FEATURE_ASSETS,
    FeatureAsset,
    FeatureDownloadError,
    asset_key,
    download_asset,
    ensure_ready,
    get_asset,
    is_downloadable,
    is_ready,
    list_assets,
    list_features,
    load_feature_state,
    save_feature_state,
    total_asset_bytes,
)


# --- Registry shape -----------------------------------------------------------

def test_list_features_returns_piper_and_local_transcription() -> None:
    assert set(list_features()) >= {"piper_tts", "local_transcription"}


def test_list_assets_piper_returns_sa_voices() -> None:
    names = set(list_assets("piper_tts"))
    assert "en.za.carina" in names
    assert "en.za.tildar" in names


def test_list_assets_local_transcription_returns_tiny_and_base() -> None:
    names = set(list_assets("local_transcription"))
    assert "tiny.en" in names
    assert "base.en" in names


def test_list_assets_unknown_feature_raises_keyerror() -> None:
    with pytest.raises(KeyError, match="unknown feature"):
        list_assets("does_not_exist")


def test_get_asset_returns_frozen_dataclass_with_description() -> None:
    a = get_asset("piper_tts", "en.za.carina")
    assert isinstance(a, FeatureAsset)
    assert a.feature == "piper_tts"
    assert a.asset_name == "en.za.carina"
    assert "South Africa" in a.description
    # Frozen
    with pytest.raises(Exception):
        a.feature = "x"  # type: ignore


def test_get_asset_unknown_raises_keyerror_with_stable_key() -> None:
    with pytest.raises(KeyError, match="piper_tts/nope"):
        get_asset("piper_tts", "nope")


def test_asset_key_is_feature_slash_name() -> None:
    assert asset_key("piper_tts", "en.za.carina") == "piper_tts/en.za.carina"


def test_every_registry_entry_has_files_list() -> None:
    """Shape-check: every asset has a 'files' list with the required keys."""
    for feature, assets in FEATURE_ASSETS.items():
        for asset_name, raw in assets.items():
            assert "files" in raw, f"{feature}/{asset_name} missing 'files'"
            assert "description" in raw
            for f in raw["files"]:
                assert "name" in f
                assert "url" in f
                assert "sha256" in f
                assert "size_bytes" in f


def test_whisper_assets_have_real_urls_and_shas() -> None:
    """The faster-whisper assets must not have TODO placeholders."""
    for asset_name in ("tiny.en", "base.en"):
        raw = FEATURE_ASSETS["local_transcription"][asset_name]
        for f in raw["files"]:
            assert not f["url"].startswith("TODO_"), (
                f"{asset_name}/{f['name']} still has a placeholder URL"
            )
            assert len(f["sha256"]) == 64, (
                f"{asset_name}/{f['name']} sha256 is not 64 hex chars"
            )
            assert f["sha256"] != "0" * 64, (
                f"{asset_name}/{f['name']} sha256 is all-zeros placeholder"
            )
            assert f["size_bytes"] > 0


def test_piper_assets_have_placeholder_urls() -> None:
    """Piper SA voices are not yet downloadable (host repo pending)."""
    for asset_name in ("en.za.carina", "en.za.tildar"):
        raw = FEATURE_ASSETS["piper_tts"][asset_name]
        for f in raw["files"]:
            assert f["url"].startswith("TODO_"), (
                f"piper_tts/{asset_name}/{f['name']} should be a placeholder"
            )


def test_is_downloadable_whisper_assets_is_true() -> None:
    assert is_downloadable("local_transcription", "tiny.en") is True
    assert is_downloadable("local_transcription", "base.en") is True


def test_is_downloadable_piper_assets_is_false() -> None:
    assert is_downloadable("piper_tts", "en.za.carina") is False
    assert is_downloadable("piper_tts", "en.za.tildar") is False


def test_total_asset_bytes_whisper_tiny_is_sum_of_files() -> None:
    expected = sum(
        f["size_bytes"]
        for f in FEATURE_ASSETS["local_transcription"]["tiny.en"]["files"]
    )
    assert total_asset_bytes("local_transcription", "tiny.en") == expected
    # Sanity: should be around 78 MB
    assert 70_000_000 < expected < 90_000_000


def test_total_asset_bytes_whisper_base_is_sum_of_files() -> None:
    expected = sum(
        f["size_bytes"]
        for f in FEATURE_ASSETS["local_transcription"]["base.en"]["files"]
    )
    assert total_asset_bytes("local_transcription", "base.en") == expected
    # Sanity: should be around 148 MB
    assert 140_000_000 < expected < 160_000_000


# --- State file ---------------------------------------------------------------

def test_load_feature_state_returns_empty_dict_when_file_missing(
    tmp_path: Path,
) -> None:
    state = load_feature_state(state_file=tmp_path / "nonexistent.json")
    assert state == {}


def test_load_feature_state_tolerates_corrupt_file(
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "feature_state.json"
    corrupt.write_text("{ this is not valid json ]]]", encoding="utf-8")
    state = load_feature_state(state_file=corrupt)
    assert state == {}


def test_load_feature_state_round_trips_a_valid_file(
    tmp_path: Path,
) -> None:
    sf = tmp_path / "feature_state.json"
    data = {
        "local_transcription/tiny.en": {
            "ready": True,
            "paths": {"model.bin": "/tmp/model.bin"},
            "downloaded_at": "2026-09-14T00:00:00Z",
            "last_error": None,
        }
    }
    sf.write_text(json.dumps(data), encoding="utf-8")
    state = load_feature_state(state_file=sf)
    assert state == data


def test_save_feature_state_writes_atomically(tmp_path: Path) -> None:
    sf = tmp_path / "feature_state.json"
    save_feature_state(
        {"key1": {"ready": True, "paths": {}, "downloaded_at": "x", "last_error": None}},
        state_file=sf,
    )
    assert sf.exists()
    data = json.loads(sf.read_text(encoding="utf-8"))
    assert data["key1"]["ready"] is True


def test_is_ready_returns_false_for_unknown_asset(tmp_path: Path) -> None:
    assert is_ready("local_transcription", "tiny.en", state_file=tmp_path / "nope.json") is False


def test_is_ready_returns_false_when_paths_dont_exist(tmp_path: Path) -> None:
    """A ready entry in the state file is only trusted if the files are on disk."""
    sf = tmp_path / "feature_state.json"
    sf.write_text(
        json.dumps({
            "local_transcription/tiny.en": {
                "ready": True,
                "paths": {"model.bin": str(tmp_path / "definitely_does_not_exist.bin")},
                "downloaded_at": "2026-09-14T00:00:00Z",
                "last_error": None,
            }
        }),
        encoding="utf-8",
    )
    assert is_ready("local_transcription", "tiny.en", state_file=sf) is False


def test_is_ready_returns_true_when_paths_exist(tmp_path: Path) -> None:
    sf = tmp_path / "feature_state.json"
    real_file = tmp_path / "real.bin"
    real_file.write_bytes(b"x")
    sf.write_text(
        json.dumps({
            "local_transcription/tiny.en": {
                "ready": True,
                "paths": {"model.bin": str(real_file)},
                "downloaded_at": "2026-09-14T00:00:00Z",
                "last_error": None,
            }
        }),
        encoding="utf-8",
    )
    assert is_ready("local_transcription", "tiny.en", state_file=sf) is True


# --- download_asset (mocked) -------------------------------------------------

def test_download_asset_raises_for_placeholder_urls(tmp_path: Path) -> None:
    """Piper assets with TODO_ URLs must raise FeatureDownloadError."""
    with pytest.raises(FeatureDownloadError, match="placeholder"):
        download_asset(
            "piper_tts",
            "en.za.carina",
            dest_dir=tmp_path,
            state_file=tmp_path / "feature_state.json",
        )


def test_download_asset_raises_for_unknown_asset() -> None:
    with pytest.raises((KeyError, FeatureDownloadError)):
        download_asset(
            "piper_tts",
            "does_not_exist",
            dest_dir=Path("."),
            state_file=Path("."),
        )


def test_ensure_ready_is_idempotent(tmp_path: Path) -> None:
    """If the asset is already ready, ensure_ready returns True without downloading."""
    sf = tmp_path / "feature_state.json"
    asset_dir = tmp_path / "local_transcription" / "tiny.en"
    asset_dir.mkdir(parents=True)
    for name in ("model.bin", "tokenizer.json", "vocabulary.txt", "config.json"):
        (asset_dir / name).write_bytes(b"x")
    sf.write_text(
        json.dumps({
            "local_transcription/tiny.en": {
                "ready": True,
                "paths": {
                    name: str(asset_dir / name)
                    for name in ("model.bin", "tokenizer.json", "vocabulary.txt", "config.json")
                },
                "downloaded_at": "2026-09-14T00:00:00Z",
                "last_error": None,
            }
        }),
        encoding="utf-8",
    )
    # ensure_ready should short-circuit (is_ready returns True) and not call download_asset
    with patch("feature_manager.download_asset") as mock_dl:
        result = ensure_ready(
            "local_transcription", "tiny.en",
            dest_dir=tmp_path,
            state_file=sf,
        )
    assert result is True
    mock_dl.assert_not_called()


def test_ensure_ready_downloads_when_not_ready(tmp_path: Path) -> None:
    """When not ready, ensure_ready calls download_asset and returns True on success."""
    sf = tmp_path / "feature_state.json"
    # Pre-seed the state file with a "ready" entry whose paths point to
    # real files so the post-download is_ready check passes.
    asset_dir = tmp_path / "local_transcription" / "tiny.en"
    asset_dir.mkdir(parents=True)
    for name in ("model.bin", "tokenizer.json", "vocabulary.txt", "config.json"):
        (asset_dir / name).write_bytes(b"x")
    sf.write_text(
        json.dumps({
            "local_transcription/tiny.en": {
                "ready": True,
                "paths": {name: str(asset_dir / name) for name in ("model.bin", "tokenizer.json", "vocabulary.txt", "config.json")},
                "downloaded_at": "2026-09-14T00:00:00Z",
                "last_error": None,
            }
        }),
        encoding="utf-8",
    )
    # Make is_ready return False initially (as if the asset is not ready),
    # then let download_asset run, then let the final is_ready check pass.
    ready_calls = [False, True]  # first call False (not ready), second True (just downloaded)
    with patch("feature_manager.is_ready", side_effect=lambda *a, **kw: ready_calls.pop(0)) as mock_ir:
        result = ensure_ready(
            "local_transcription", "tiny.en",
            dest_dir=tmp_path,
            state_file=sf,
        )
    assert result is True
    assert mock_ir.call_count == 2


# --- Smoke -------------------------------------------------------------------

def test_feature_manager_imports_cleanly() -> None:
    """Catch a circular import or missing symbol at import time."""
    import feature_manager  # noqa: F401
    assert hasattr(feature_manager, "FEATURE_ASSETS")
    assert hasattr(feature_manager, "ensure_ready")
