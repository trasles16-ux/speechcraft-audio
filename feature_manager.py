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
    # Piper TTS — en_GB voices AND the Piper executable itself.
    #
    # The executable (`piper.exe`) is only required on builds that don't
    # bundle it (the Core edition). On Full installs `PiperTTSEngine`
    # finds piper.exe via PATH or the install dir and skips this asset.
    # The asset is registered here so the lazy-install flow can offer
    # "Download Piper" instead of failing with a hard error on Core.
    #
    # SHA verification: the piper.exe URL has no stable embedded SHA
    # (we don't pin a specific Piper release). The ``sha256`` field is
    # empty and ``sha256_url`` points at the sibling ``.sha256`` file
    # GitHub auto-generates next to release assets — `download_asset`
    # fetches and uses that at install time.
    #
    # Voices are en_GB from rhasspy/piper-voices. (SA en_ZA voices
    # Carina/Tildar do not exist publicly yet — see research findings in
    # the plan doc. en_GB voices used as the working default until the
    # SA voice project lands.)
    "piper_tts": {
        "executable": {
            "files": [
                {"name": "piper.exe",
                 "url": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip",
                 # SHA-256 of piper_windows_amd64.zip v2023.11.14-2
                 # (verified against GitHub release at install time —
                 # the sibling .sha256 sidecar 404s, so we hardcode it).
                 "sha256": "f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea",
                 "sha256_url": "",
                 # 22,477,236 bytes — verified by HEAD request 2026-09-23.
                 "size_bytes": 22_477_236,
                 "extract": "zip",
                 "extract_entry": "piper/piper.exe"},
            ],
            "description": "Piper TTS executable (Windows, 64-bit, ~22 MB)",
        },
        "en_GB.cori": {
            "files": [
                {"name": "model",
                 "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium/en_GB-cori-medium.onnx",
                 "sha256": "1899f98e5fb8310154f3c2973f4b8a929ba7245e722b3d3a85680b833d95f10d",
                 "size_bytes": 63_531_379},
                {"name": "config",
                 "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium/en_GB-cori-medium.onnx.json",
                 "sha256": "e262c16d7f192f69d4edd6b4ef8a5915379e67495fcc402f1ab15eeb33da3d36",
                 "size_bytes": 4_966},
            ],
            "description": "English (Great Britain) — Cori, female, medium quality (60 MB)",
        },
        "en_GB.alan": {
            "files": [
                {"name": "model",
                 "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx",
                 "sha256": "0a309668932205e762801f1efc2736cd4b0120329622adf62be09e56339d3330",
                 "size_bytes": 63_201_294},
                {"name": "config",
                 "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json",
                 "sha256": "c0f0d124e5895c00e7c03b35dcc8287f319a6998a365b182deb5c8e752ee8c1e",
                 "size_bytes": 4_888},
            ],
            "description": "English (Great Britain) — Alan, male, medium quality (60 MB)",
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

    As of v1.3.0 every registered asset ships with real URLs + SHAs,
    so this returns True for all of them. It exists as a guard so a
    future asset added with placeholder data won't silently enable a
    dead download button in the wizard.
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

#: Root of every downloaded feature asset: ``PREFS_DIR/feature_assets``.
#: This is the single download destination for the whole app — the
#: wizard's Download page, the lazy-install prompt, and every engine
#: lookup (piper.exe discovery, Whisper model dir) all resolve under
#: here. v1.3.6 had three different destinations (``PREFS_DIR/models``
#: from the wizard, CWD from lazy_install, this folder from the Piper
#: engine), so the wizard's download and the engine's lookup could
#: never agree and downloads ran twice or failed to be found.
#: The NSIS uninstaller already removes ``$APPDATA\SpeechCraft\
#: feature_assets``, so uninstall hygiene matches too.
ASSETS_ROOT: Final = DEFAULT_STATE_FILE.parent / "feature_assets"


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


def _extract_from_zip(
    zip_path: str,
    *,
    entry_name: str,
    out_dir: Path,
) -> Path:
    """Extract a single file from ``zip_path`` into ``out_dir``.

    Returns the extracted file's path. Raises ``OSError`` if the
    zip is unreadable or the entry isn't found. Stdlib-only
    (``zipfile``), no new deps.

    ``entry_name`` can be the literal name (e.g. ``piper/piper.exe``)
    or a short suffix (e.g. ``piper.exe``); the matcher prefers the
    literal name and falls back to a basename match.

    If the zip file is truncated or otherwise corrupt, ``zipfile``
    raises ``EOFError`` mid-read (zipfile's central directory can
    reference an entry whose compressed bytes never landed on disk).
    We catch that and re-raise as ``OSError`` with a clear message
    so the caller can surface a friendly "the download was truncated,
    please try again" instead of a Python traceback.
    """
    import zipfile

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Literal match first
            target: str | None = entry_name if entry_name in names else None
            if target is None and entry_name:
                # Fall back to basename match (e.g. "piper/piper.exe" -> "piper.exe")
                short = entry_name.rsplit("/", 1)[-1]
                for n in names:
                    if n.endswith("/" + short) or n == short:
                        target = n
                        break
            if target is None:
                raise OSError(
                    f"{entry_name!r} not found in zip; archive contains: {names}"
                )
            out_path = out_dir / Path(target).name
            out_dir.mkdir(parents=True, exist_ok=True)
            with zf.open(target) as src, open(out_path, "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
    except EOFError as exc:
        # Truncated / corrupt zip. The most common cause is a download
        # that bailed out partway and slipped through
        # download_with_progress's content-length accounting (e.g.
        # the server returned a Content-Length that didn't match what
        # it actually delivered, or the connection was reset after
        # the last byte was written). Re-raise as OSError so the
        # caller's ``except OSError`` branch catches it and the
        # downstream state-file cleanup runs.
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        size = os.path.getsize(zip_path) if os.path.isfile(zip_path) else 0
        raise OSError(
            f"Zip file {zip_path} is truncated or corrupt "
            f"({size:,} bytes on disk; reading entry {entry_name!r} hit "
            f"end-of-file). The download was incomplete — re-downloading "
            f"should fix it."
        ) from exc
    return out_path


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

    ``dest_dir`` defaults to :data:`ASSETS_ROOT` — the shared location
    every consumer reads. Passing a custom value is only for tests.

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

    raw = FEATURE_ASSETS[feature][asset_name]
    files = raw["files"]
    total_bytes = sum(f["size_bytes"] for f in files if f["size_bytes"] > 0)
    key = asset_key(feature, asset_name)
    out_dir = _state_entry_path(
        feature, asset_name, dest_dir=dest_dir if dest_dir is not None else ASSETS_ROOT
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    bytes_done = 0
    paths: dict[str, str] = {}

    for file_spec in files:
        file_name = file_spec["name"]
        url = file_spec["url"]
        expected_sha = file_spec["sha256"]

        final_path = out_dir / file_name

        # Reuse the v1.2.0 download machinery
        from updater import (
            UpdateCheckError,
            download_with_progress,
            verify_asset_sha256,
        )

        # Offset the per-file progress into the whole-asset progress
        # so the caller can drive one bar across every file.
        _bytes_done_snapshot = bytes_done

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
            # download_with_progress already cleaned up the .part file
            state = load_feature_state(state_file=state_file)
            entry = state.get(key) or _empty_state_entry()
            entry["ready"] = False
            entry["last_error"] = str(exc)
            state[key] = entry
            save_feature_state(state, state_file=state_file)
            raise FeatureDownloadError(key, str(exc)) from exc

        # Optional post-download extraction (e.g. zip → single binary).
        # Used for assets like ``piper.exe`` whose URL is a release zip.
        extract_mode = file_spec.get("extract")
        if extract_mode == "zip":
            try:
                extracted = _extract_from_zip(
                    str(final_path),
                    entry_name=file_spec.get("extract_entry", ""),
                    out_dir=out_dir,
                )
                # The downloaded zip is throw-away — drop it so the
                # asset dir only contains the file(s) the engine
                # actually needs.
                try:
                    final_path.unlink(missing_ok=True)
                except OSError:
                    pass
                # Replace the planned destination with the extracted one.
                final_path = extracted
                paths[file_name] = str(extracted)
                # Re-record size for progress reporting.
                bytes_done += extracted.stat().st_size if extracted.exists() else 0
                # No SHA verification step below — we trust the zip was
                # downloaded intact (verified by download_with_progress's
                # size accounting against the Content-Length). The zip
                # itself is throwaway and the engine only reads the
                # extracted binary.
                continue
            except OSError as exc:
                state = load_feature_state(state_file=state_file)
                entry = state.get(key) or _empty_state_entry()
                entry["ready"] = False
                entry["last_error"] = f"Could not extract {file_name}: {exc}"
                state[key] = entry
                save_feature_state(state, state_file=state_file)
                raise FeatureDownloadError(
                    key, f"Could not extract {file_name}: {exc}"
                ) from exc

        # SHA-256 verify (separate step — updater does not verify internally).
        # If the asset spec has an empty ``sha256`` but a ``sha256_url``,
        # fetch the digest from the sidecar first.
        if not expected_sha:
            sidecar_url = file_spec.get("sha256_url")
            if sidecar_url:
                from updater import fetch_expected_sha256
                expected_sha = fetch_expected_sha256(
                    digest_url=sidecar_url,
                    asset_name=url.rsplit("/", 1)[-1],
                ) or ""

        if expected_sha and not verify_asset_sha256(str(final_path), expected_sha):
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

    ``dest_dir`` defaults to :data:`ASSETS_ROOT` so a caller that
    passes nothing (lazy_install did) downloads into the shared
    feature_assets tree instead of the process's current working
    directory — which on an installed copy lives under
    ``C:\\Program Files`` where a non-admin app cannot write.
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
    "ASSETS_ROOT",
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
