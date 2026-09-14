"""SpeechCraft Studio feature asset manager.

Pure logic — no wx, no pedalboard, no whisper, no piper. Reuses the
download + SHA-256 machinery from :mod:`updater`.

What this module does:
- Define FEATURE_ASSETS: the registry of every downloadable feature
  asset (Piper voices, faster-whisper models).
- Persist per-asset state to ``PREFS_DIR/feature_state.json``
  (ready / not-ready / last error / paths).
- Download + verify + atomically install one asset, updating state.

What this module does NOT do:
- No GUI. No progress dialog. No auto-download-on-launch.
- No gating of menu items (that's v1.3.0-feature-toggling).
- No queue / concurrency. One asset at a time, caller-driven.

See docs/plans/2026-09-14-v1.3.0-feature-manager.md for the design.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final

from prefs import PREFS_DIR


# --- Registry ----------------------------------------------------------------

@dataclass(frozen=True)
class FeatureAsset:
    """One downloadable thing the user might want.

    ``feature`` is the high-level capability (``piper_tts``,
    ``local_transcription``). ``asset_name`` is the specific asset
    within that feature (``en.za.carina``, ``tiny.en``).
    """
    feature: str
    asset_name: str
    description: str

    @property
    def key(self) -> str:
        return f"{self.feature}/{self.asset_name}"


#: The registry. Unified multi-file shape: each asset has a ``files``
#: list of ``{"name", "url", "sha256", "size_bytes"}`` dicts. Adding
#: a voice or model is a data edit, not a code change.
FEATURE_ASSETS: Final = {
    # Piper TTS voices (South African set)
    # URLs are placeholders until the SA community voice repo is
    # identified (see research findings in the plan doc).
    "piper_tts": {
        "en.za.carina": {
            "files": [
                {"name": "model", "url": "TODO_CARINA_MODEL_URL",
                 "sha256": "0" * 64, "size_bytes": 0},
                {"name": "config", "url": "TODO_CARINA_CONFIG_URL",
                 "sha256": "0" * 64, "size_bytes": 0},
            ],
            "description": "English (South Africa) — female, medium quality",
        },
        "en.za.tildar": {
            "files": [
                {"name": "model", "url": "TODO_TILDAR_MODEL_URL",
                 "sha256": "0" * 64, "size_bytes": 0},
                {"name": "config", "url": "TODO_TILDAR_CONFIG_URL",
                 "sha256": "0" * 64, "size_bytes": 0},
            ],
            "description": "English (South Africa) — male, medium quality",
        },
    },
    # Local transcription (faster-whisper)
    # All SHAs verified 14 Sep 2026 from Hugging Face.
    "local_transcription": {
        "tiny.en": {
            "files": [
                {"name": "model.bin",
                 "url": "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/model.bin",
                 "sha256": "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1",
                 "size_bytes": 75_538_270},
                {"name": "tokenizer.json",
                 "url": "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/tokenizer.json",
                 "sha256": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
                 "size_bytes": 2_203_239},
                {"name": "vocabulary.txt",
                 "url": "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/vocabulary.txt",
                 "sha256": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
                 "size_bytes": 459_861},
                {"name": "config.json",
                 "url": "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/config.json",
                 "sha256": "a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8",
                 "size_bytes": 2_249},
            ],
            "description": "faster-whisper tiny.en — fastest, lightest (77 MB total)",
        },
        "base.en": {
            "files": [
                {"name": "model.bin",
                 "url": "https://huggingface.co/Systran/faster-whisper-base/resolve/main/model.bin",
                 "sha256": "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
                 "size_bytes": 145_217_532},
                {"name": "tokenizer.json",
                 "url": "https://huggingface.co/Systran/faster-whisper-base/resolve/main/tokenizer.json",
                 "sha256": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
                 "size_bytes": 2_203_239},
                {"name": "vocabulary.txt",
                 "url": "https://huggingface.co/Systran/faster-whisper-base/resolve/main/vocabulary.txt",
                 "sha256": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
                 "size_bytes": 459_861},
                {"name": "config.json",
                 "url": "https://huggingface.co/Systran/faster-whisper-base/resolve/main/config.json",
                 "sha256": "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a",
                 "size_bytes": 2_309},
            ],
            "description": "faster-whisper base.en — good quality/speed tradeoff (148 MB total)",
        },
    },
}


def asset_key(feature: str, asset_name: str) -> str:
    """Stable key used in feature_state.json and progress callbacks."""
    return f"{feature}/{asset_name}"


def list_features() -> tuple[str, ...]:
    return tuple(FEATURE_ASSETS.keys())


def list_assets(feature: str) -> tuple[str, ...]:
    if feature not in FEATURE_ASSETS:
        raise KeyError(f"unknown feature {feature!r}")
    return tuple(FEATURE_ASSETS[feature].keys())


def get_asset(feature: str, asset_name: str) -> FeatureAsset:
    """Return the FeatureAsset for (feature, asset_name), or raise KeyError."""
    try:
        raw = FEATURE_ASSETS[feature][asset_name]
    except KeyError as exc:
        raise KeyError(f"unknown asset {asset_key(feature, asset_name)!r}") from exc
    return FeatureAsset(
        feature=feature,
        asset_name=asset_name,
        description=raw.get("description", ""),
    )


def is_downloadable(feature: str, asset_name: str) -> bool:
    """True if all files in the asset have real (non-TODO) URLs.

    Piper assets ship with placeholder URLs until the SA community
    voice repo is identified — this function gates the wizard's
    Download button so it is disabled for those.
    """
    raw = FEATURE_ASSETS[feature][asset_name]
    return all(not f["url"].startswith("TODO_") for f in raw["files"])


def total_asset_bytes(feature: str, asset_name: str) -> int:
    """Sum of size_bytes across all files in the asset.

    Used to drive a single progress bar spanning the whole download.
    """
    raw = FEATURE_ASSETS[feature][asset_name]
    return sum(f["size_bytes"] for f in raw["files"])


# --- State file ---------------------------------------------------------------

#: Default location: ``PREFS_DIR/feature_state.json``
DEFAULT_STATE_FILE: Final = PREFS_DIR / "feature_state.json"


def _empty_state_entry() -> dict[str, Any]:
    return {"ready": False, "paths": {}, "downloaded_at": None, "last_error": None}


def load_feature_state(*, state_file: Path | None = None) -> dict[str, dict]:
    """Read feature_state.json; return {} if the file doesn't exist.

    Tolerates a corrupt or partial file (returns {} rather than raising)
    so a crashed download mid-write never blocks the app at startup.
    """
    target = state_file if state_file is not None else DEFAULT_STATE_FILE
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Normalise: every value must be a dict
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def save_feature_state(state: dict[str, dict], *, state_file: Path | None = None) -> None:
    """Atomically write feature_state.json (``.part`` + ``os.replace``).

    Mirrors the crash-safety pattern in ``prefs.save_prefs``.
    """
    target = state_file if state_file is not None else DEFAULT_STATE_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(".json.part")
        part.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        import os
        os.replace(str(part), str(target))
    except OSError:
        pass  # read-only filesystem / permission denied — not fatal


def is_ready(feature: str, asset_name: str, *, state_file: Path | None = None) -> bool:
    """True if the state file says this asset is ready AND every
    recorded path still exists on disk."""
    state = load_feature_state(state_file=state_file)
    entry = state.get(asset_key(feature, asset_name))
    if not entry:
        return False
    if not entry.get("ready"):
        return False
    # Verify the files are actually on disk (not just in the state file)
    for path_str in entry.get("paths", {}).values():
        if not Path(path_str).exists():
            return False
    return True


def _state_entry_path(feature: str, asset_name: str, *, dest_dir: Path) -> Path:
    """Where one asset's files land: ``dest_dir/feature/asset_name/``."""
    return dest_dir / feature / asset_name


def _file_path(feature: str, asset_name: str, file_name: str, *, dest_dir: Path) -> Path:
    return _state_entry_path(feature, asset_name, dest_dir=dest_dir) / file_name


# --- Download -----------------------------------------------------------------

class FeatureDownloadError(Exception):
    """Raised when a feature asset download fails (network, SHA, cancel)."""

    def __init__(self, asset_key: str, reason: str):
        self.asset_key = asset_key
        self.reason = reason
        super().__init__(f"{asset_key}: {reason}")


def _sha256_of_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_asset(
    feature: str,
    asset_name: str,
    *,
    dest_dir: Path | None = None,
    progress_cb: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    state_file: Path | None = None,
) -> dict:
    """Download all files in one asset into ``dest_dir``.

    Each file is streamed to a ``.part`` file, SHA-256 verified, then
    atomically renamed. On success the state file is updated. On
    failure the ``.part`` is cleaned up and the state file records
    ``last_error``.

    ``progress_cb(asset_key, bytes_downloaded, total_bytes)`` is called
    after each chunk. The total spans all files in the asset so the
    caller can drive one progress bar.

    Returns the state entry dict that was written.
    Raises FeatureDownloadError on network failure, SHA mismatch, or cancel.
    """
    import time
    from pathlib import Path as _Path

    raw = FEATURE_ASSETS[feature][asset_name]
    files = raw["files"]
    total_bytes = sum(f["size_bytes"] for f in files if f["size_bytes"] > 0)
    key = asset_key(feature, asset_name)
    out_dir = _state_entry_path(feature, asset_name,
                                dest_dir=dest_dir or _Path("."))
    out_dir.mkdir(parents=True, exist_ok=True)

    bytes_done = 0
    paths: dict[str, str] = {}

    for file_spec in files:
        file_name = file_spec["name"]
        url = file_spec["url"]
        expected_sha = file_spec["sha256"]

        if url.startswith("TODO_"):
            raise FeatureDownloadError(
                key,
                f"asset not yet available — URL placeholder: {url!r}",
            )

        final_path = out_dir / file_name
        part_path = out_dir / (file_name + ".part")

        # Reuse the v1.2.0 download machinery
        from updater import (
            UpdateCheckError,
            download_with_progress,
            verify_asset_sha256,
        )

        # progress_cb signature: (asset_key, bytes_done_in_this_file, total_for_asset)
        # download_with_progress gives us (bytes_in_this_file, total_this_file)
        # so we offset by bytes_done to get the whole-asset progress.
        _bytes_done_snapshot = bytes_done
        _total_this_file = file_spec.get("size_bytes", 0)

        def _chunk_cb(done: int, total: int) -> None:
            if progress_cb is not None:
                progress_cb(key, _bytes_done_snapshot + done, total_bytes)

        try:
            download_with_progress(
                url,
                str(final_path),
                progress_cb=_chunk_cb,
                cancel_check=cancel_check,
            )
        except UpdateCheckError as exc:
            # download_with_progress already cleaned up .part on cancel/error
            state = load_feature_state(state_file=state_file)
            entry = state.get(key) or _empty_state_entry()
            entry["ready"] = False
            entry["last_error"] = str(exc)
            state[key] = entry
            save_feature_state(state, state_file=state_file)
            raise FeatureDownloadError(key, str(exc)) from exc

        # SHA-256 verify (separate step — updater does not verify internally)
        if not verify_asset_sha256(str(final_path), expected_sha):
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
            state = load_feature_state(state_file=state_file)
            entry = state.get(key) or _empty_state_entry()
            entry["ready"] = False
            entry["last_error"] = (
                f"SHA-256 mismatch for {file_name} — "
                "file deleted, re-download needed"
            )
            state[key] = entry
            save_feature_state(state, state_file=state_file)
            raise FeatureDownloadError(
                key, f"SHA-256 mismatch for {file_name}"
            )

        paths[file_name] = str(final_path)
        bytes_done += file_spec.get("size_bytes", 0)

    # All files landed — update the state file
    state = load_feature_state(state_file=state_file)
    entry = state.get(key) or _empty_state_entry()
    entry["ready"] = True
    entry["paths"] = paths
    entry["downloaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    entry["last_error"] = None
    state[key] = entry
    save_feature_state(state, state_file=state_file)

    if progress_cb:
        progress_cb(key, bytes_done, total_bytes)

    return entry


def ensure_ready(
    feature: str,
    asset_name: str,
    *,
    dest_dir: Path | None = None,
    progress_cb: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    state_file: Path | None = None,
) -> bool:
    """Return True if the asset is ready (already on disk or just
    downloaded). False on cancel. Raises FeatureDownloadError on
    failure. Idempotent: calling it twice only downloads once.
    """
    if is_ready(feature, asset_name, state_file=state_file):
        return True

    # Download all files
    download_asset(
        feature,
        asset_name,
        dest_dir=dest_dir,
        progress_cb=progress_cb,
        cancel_check=cancel_check,
        state_file=state_file,
    )
    return is_ready(feature, asset_name, state_file=state_file)


__all__ = (
    "FEATURE_ASSETS",
    "FeatureAsset",
    "FeatureDownloadError",
    "DEFAULT_STATE_FILE",
    "asset_key",
    "list_features",
    "list_assets",
    "get_asset",
    "is_downloadable",
    "total_asset_bytes",
    "load_feature_state",
    "save_feature_state",
    "is_ready",
    "download_asset",
    "ensure_ready",
)
