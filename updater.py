"""SpeechCraft Studio auto-updater.

Checks GitHub for a newer release of SpeechCraft Studio, downloads
the installer with progress reporting, verifies its SHA-256 against
the digest GitHub publishes alongside each asset, and provides a
launch helper for spawning the installer.

Pure logic — no wx dependency so it can be tested in Linux CI.

The check is **manual by default** (Help → Check for updates) and
**automatic on launch** if the user has not disabled it (stored in
``setup.json`` under ``"auto_check_updates": true``). The prompt
itself is always shown when a newer version exists — there is no
silent-install path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Final

#: GitHub repo coordinates. Public repo (MIT), no auth needed for
#: anonymous /releases/latest calls (rate-limited to 60/hr per IP).
REPO_OWNER: Final = "trasles16-ux"
REPO_NAME: Final = "speechcraft-audio"
LATEST_RELEASE_URL: Final = (
    f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
)
#: User-Agent header — GitHub requires a UA on API requests.
USER_AGENT: Final = "SpeechCraft-Studio-UpdateChecker/1.2.0"

#: Network timeout for the API call (seconds).
HTTP_TIMEOUT_S: Final = 10.0
#: Network timeout for the installer download (seconds). Longer than the
#: API call because the installer is ~50 MB and may be slow.
DOWNLOAD_TIMEOUT_S: Final = 1800.0
#: Chunk size when streaming the installer to disk (bytes).
DOWNLOAD_CHUNK_BYTES: Final = 64 * 1024


@dataclass(frozen=True)
class UpdateInfo:
    """A parsed GitHub release."""

    version: str
    """Semver string, no 'v' prefix (e.g. "1.3.0")."""

    url: str
    """Release page URL (GitHub HTML, not the API URL)."""

    title: str
    """Release title (e.g. "SpeechCraft Studio v1.3.0")."""

    notes: str
    """Release notes (markdown body)."""

    published_at: str
    """ISO-8601 timestamp from GitHub."""

    assets: tuple["AssetInfo", ...] = ()
    """All downloadable assets attached to the release."""

    is_prerelease: bool = False

    def is_newer_than(self, current: str) -> bool:
        """Return True if this release is strictly newer than ``current``."""
        return compare_versions(self.version, current) > 0

    def find_installer(self) -> "AssetInfo | None":
        """Return the Windows installer asset, or None if not found.

        Matches ``.exe`` whose name contains ``SpeechCraft`` and ends
        with ``Setup.exe`` — the convention established by v1.0.0.
        """
        for asset in self.assets:
            name = asset.name.lower()
            if name.endswith(".exe") and "speechcraft" in name and "setup" in name:
                return asset
        return None


@dataclass(frozen=True)
class AssetInfo:
    """A single downloadable asset attached to a GitHub release."""

    name: str
    """Filename (e.g. "SpeechCraft_Studio_Setup.exe")."""

    url: str
    """Direct download URL (browser_download_url)."""

    size_bytes: int
    """Asset size in bytes."""

    sha256: str | None = None
    """Expected SHA-256 hex digest, if known."""

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def _strip_v(version: str) -> str:
    """Strip a leading 'v' (GitHub tag convention) and whitespace."""
    return version.strip().lstrip("v")


def _to_parts(version: str) -> tuple[int, ...]:
    """Convert a semver string into a comparable int tuple.

    Stops at the first non-digit/non-dot segment so "1.2.0-rc1"
    becomes (1, 2, 0). Missing components pad to 0: "1.2" -> (1, 2, 0).
    """
    cleaned = _strip_v(version)
    parts: list[int] = []
    for piece in cleaned.split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def compare_versions(a: str, b: str) -> int:
    """Compare two semver strings.

    Returns -1 if ``a < b``, 0 if equal, 1 if ``a > b``.
    Handles 'v' prefix, missing patch numbers, and pre-release tags.
    """
    pa, pb = _to_parts(a), _to_parts(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def parse_release(payload: dict) -> UpdateInfo:
    """Parse a single release dict from GitHub's /releases endpoint."""
    raw_assets = payload.get("assets") or []
    assets = tuple(
        AssetInfo(
            name=str(a.get("name", "")),
            url=str(a.get("browser_download_url", "")),
            size_bytes=int(a.get("size", 0) or 0),
            sha256=_extract_asset_sha256(a),
        )
        for a in raw_assets
        if isinstance(a, dict)
    )
    return UpdateInfo(
        version=_strip_v(payload.get("tag_name", "")),
        url=payload.get("html_url", ""),
        title=payload.get("name", "") or payload.get("tag_name", ""),
        notes=payload.get("body", "") or "",
        published_at=payload.get("published_at", ""),
        assets=assets,
        is_prerelease=bool(payload.get("prerelease", False)),
    )


def _extract_asset_sha256(asset: dict) -> str | None:
    """Pull a SHA-256 hex digest from a release asset dict, if present.

    GitHub's API does not currently return a digest on the asset object
    itself, but releases commonly include a sibling ``.sha256`` file
    uploaded alongside the binary. We do not fetch that here — the
    digest is populated by the caller when known. This function exists
    for forward-compat: if GitHub ever returns a digest on the asset,
    we honour it.
    """
    digest = asset.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    return None


class UpdateCheckError(Exception):
    """Raised when the update check cannot complete."""


def fetch_latest_release(
    *,
    url: str = LATEST_RELEASE_URL,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> UpdateInfo:
    """Fetch and parse the latest GitHub release.

    Raises ``UpdateCheckError`` on any network or parse failure. Callers
    should catch and surface a friendly dialog — never let the error
    bubble up uncaught.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateCheckError(
                "No releases have been published yet on GitHub."
            ) from exc
        raise UpdateCheckError(
            f"GitHub returned HTTP {exc.code}. Try again later."
        ) from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(
            f"Could not reach GitHub: {exc.reason}. Check your network."
        ) from exc
    except TimeoutError as exc:
        raise UpdateCheckError(
            "GitHub did not respond within the timeout. Try again later."
        ) from exc
    except OSError as exc:
        raise UpdateCheckError(
            f"Network error: {exc}. Try again later."
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateCheckError(
            "GitHub returned an unexpected response. Try again later."
        ) from exc

    if not isinstance(payload, dict):
        raise UpdateCheckError(
            "GitHub returned an unexpected response. Try again later."
        )

    return parse_release(payload)


# --- Download + verification -------------------------------------------------


ProgressCallback = Callable[[int, int], None]
"""``progress_cb(bytes_downloaded, total_bytes)`` — called many times during download."""


def download_with_progress(
    url: str,
    dest_path: str,
    *,
    progress_cb: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout_s: float = DOWNLOAD_TIMEOUT_S,
    chunk_bytes: int = DOWNLOAD_CHUNK_BYTES,
) -> str:
    """Stream ``url`` to ``dest_path`` with byte-level progress callbacks.

    ``cancel_check`` is polled between chunks; if it returns True the
    partial file is deleted and ``UpdateCheckError`` is raised.

    Returns ``dest_path`` on success. Raises ``UpdateCheckError`` on
    any network error.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            tmp_path = dest_path + ".part"
            # Ensure the destination directory exists. On a fresh install
            # the staging folder (%LOCALAPPDATA%\SpeechCraft\updates\) may
            # not exist yet, so open() would raise FileNotFoundError.
            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            downloaded = 0
            with open(tmp_path, "wb") as fh:
                while True:
                    if cancel_check is not None and cancel_check():
                        fh.close()
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                        raise UpdateCheckError("Download cancelled.")
                    chunk = resp.read(chunk_bytes)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        progress_cb(downloaded, total)
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(
            f"GitHub returned HTTP {exc.code} while downloading."
        ) from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(
            f"Network error during download: {exc.reason}."
        ) from exc
    except TimeoutError as exc:
        raise UpdateCheckError(
            "Download timed out. Try again later."
        ) from exc
    except OSError as exc:
        raise UpdateCheckError(
            f"Could not write the installer: {exc}."
        ) from exc

    # Atomic rename from .part -> final path.
    try:
        os.replace(tmp_path, dest_path)
    except OSError as exc:
        raise UpdateCheckError(
            f"Could not finalize the installer: {exc}."
        ) from exc
    return dest_path


def sha256_of_file(path: str, *, chunk_bytes: int = DOWNLOAD_CHUNK_BYTES) -> str:
    """Return the lowercase hex SHA-256 digest of ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_bytes)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_asset_sha256(path: str, expected_hex: str) -> bool:
    """Return True iff SHA-256 of ``path`` matches ``expected_hex``.

    Comparison is constant-time to avoid timing side-channels.
    """
    actual = sha256_of_file(path)
    return hmac.compare_digest(actual.lower(), expected_hex.lower())


def fetch_expected_sha256(
    *,
    digest_url: str,
    asset_name: str,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> str | None:
    """Fetch a ``.sha256`` sibling file and return the digest for ``asset_name``.

    Release authors often upload a sidecar ``<asset>.sha256`` containing
    lines like::

        abc123... *SpeechCraft_Studio_Setup.exe

    This function downloads that sidecar (if the URL exists) and pulls
    out the digest for the given asset. Returns None if no matching
    line is found or the sidecar cannot be fetched — callers should
    treat that as "no digest available" and either skip verification or
    warn the user, never silently pass.
    """
    req = urllib.request.Request(
        digest_url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None
    target = asset_name.strip().lower()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Two common formats:
        #   "<digest>  <filename>"   (sha256sum -b output)
        #   "<digest> *<filename>"   (sha256sum default; * marks binary)
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, filename = parts
        filename = filename.lstrip("*").strip().lower()
        if filename == target and len(digest) == 64 and all(
            c in "0123456789abcdef" for c in digest.lower()
        ):
            return digest.lower()
    return None


# --- Installer launch --------------------------------------------------------


def default_installer_dir() -> str:
    """Folder the downloaded installer is staged into.

    ``%TEMP%`` is wiped occasionally by the OS / cleanup tools, so we
    prefer the user's local app data folder (persistent across launches
    within a release cycle).
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "SpeechCraft", "updates")
    return os.path.join(tempfile.gettempdir(), "speechcraft-updates")


def installer_staging_path(version: str) -> str:
    """Where the installer for ``version`` should be staged on disk."""
    return os.path.join(default_installer_dir(), f"SpeechCraft-Setup-{version}.exe")


def launch_installer(path: str) -> "subprocess.Popen":
    """Spawn the installer EXE detached from the current process.

    Use ``subprocess.Popen`` with no shell, no window, and don't wait.
    SpeechCraft should quit immediately after calling this so the
    installer can replace the running EXE.

    Returns the ``Popen`` handle so the caller can verify the installer
    actually started (``poll()`` stays ``None`` for a few seconds)
    before SpeechCraft exits. A detached installer that is about to
    quit the parent must be confirmed alive — otherwise a spawn that
    failed (e.g. UAC not allowed in a remote-desktop session) looks
    like "clicked install, then nothing happened".

    Raises :class:`UpdateCheckError` if the installer EXE is missing.
    A spawn-time ``OSError`` (access denied, UAC blocked) is
    re-raised as :class:`UpdateCheckError` with the WinError detail,
    so callers have a single exception type to handle.
    """
    if sys.platform != "win32":
        raise UpdateCheckError(
            "Auto-install is only supported on Windows."
        )
    if not os.path.isfile(path):
        raise UpdateCheckError(
            f"Installer not found at {path}."
        )
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so SpeechCraft exiting
    # doesn't kill the installer.
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(
            [path],
            close_fds=True,
            creationflags=flags,
            shell=False,
        )
    except OSError as exc:
        raise UpdateCheckError(
            f"Could not start the installer ({path}). "
            f"Windows error: {exc}. The installer may need elevation "
            f"(right-click, Run as administrator) or you may be in a "
            f"remote session where UAC prompts cannot be shown. "
            f"You can run the installer manually: {path}"
        ) from exc
    # Give the spawn a beat to fail-fast (e.g. immediate Win32 error),
    # then return the live handle so the caller can poll().
    import time as _time
    _time.sleep(1.0)
    if proc.poll() is not None:
        raise UpdateCheckError(
            f"The installer started but exited immediately "
            f"(code {proc.returncode}) — {path}. It may have been "
            f"blocked by Windows SmartScreen or Antivirus. Try running "
            f"it manually."
        )
    return proc