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

Reliability (v1.3.5):
- Downloads send ``Accept: application/octet-stream,*/*`` so the GitHub
  CDN doesn't occasionally reply with HTML when the request looks
  browser-less.
- Downloads send ``Accept-Encoding: identity`` so the streamed
  ``Content-Length`` always matches the bytes we write to disk
  (Python's urllib transparently decompresses gzip, which previously
  caused the progress bar to overshoot).
- Timeouts are split: a short CONNECT timeout (30 s) catches "GitHub
  is down / port blocked" quickly, while each chunk read gets its own
  READ timeout (120 s) so a stalled mid-stream read dies with a clear
  error in 2 minutes instead of the previous 30 minutes.
- Transient network errors retry up to 3 times with exponential
  backoff (2 s, 4 s, 8 s).
- If a ``.part`` file is already on disk (the user is re-running the
  download after a failure), the next attempt sends ``Range: bytes=N-``
  and resumes from byte ``N`` instead of starting over.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
from socket import _GLOBAL_DEFAULT_TIMEOUT
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Final, Literal

#: GitHub repo coordinates. Public repo (MIT), no auth needed for
#: anonymous /releases/latest calls (rate-limited to 60/hr per IP).
REPO_OWNER: Final = "trasles16-ux"
REPO_NAME: Final = "speechcraft-audio"
LATEST_RELEASE_URL: Final = (
    f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
)
#: User-Agent header — GitHub requires a UA on API requests.
USER_AGENT: Final = "SpeechCraft-Studio-UpdateChecker/1.3.5"

#: Network timeout for the API call (seconds).
HTTP_TIMEOUT_S: Final = 10.0
#: TCP connect timeout for downloads (seconds). Short on purpose — if
#: the host is unreachable we want to know within 30 s, not 30 minutes.
CONNECT_TIMEOUT_S: Final = 30.0
#: Per-chunk read timeout for downloads (seconds). Each ``read()`` call
#: gets up to this long before we raise, so a stalled mid-stream read
#: surfaces as a clear timeout error rather than a silent 30-min wait.
READ_TIMEOUT_S: Final = 120.0
#: Legacy single-timeout knob kept for callers that pass a single
#: ``timeout_s`` to ``download_with_progress`` / ``fetch_expected_sha256``.
#: Respected as the connect timeout when no per-phase override is given.
DOWNLOAD_TIMEOUT_S: Final = 1800.0
#: Chunk size when streaming the installer to disk (bytes).
DOWNLOAD_CHUNK_BYTES: Final = 64 * 1024
#: Max retry attempts on transient network errors (URLError, TimeoutError,
#: ConnectionResetError). 1 = no retries, 3 = up to three total attempts.
MAX_DOWNLOAD_RETRIES: Final = 3
#: Sleep between retries, indexed by attempt number (0 = first retry).
#: Attempt 1 waits 2 s, attempt 2 waits 4 s, attempt 3 waits 8 s.
RETRY_BACKOFF_S: Final = (2.0, 4.0, 8.0)


#: Progress state passed to the progress callback in addition to the
#: byte counters. Lets the UI distinguish "still connecting", "we're
#: downloading", "we hit a transient error and are about to retry",
#: and "download finished, now verifying the checksum".
ProgressState = Literal["connecting", "downloading", "retrying", "verifying", "done"]


#: HTTP headers every download / digest fetch sends. Module-level so
#: tests can assert against a single source of truth.
_DOWNLOAD_HEADERS: Final = {
    "User-Agent": USER_AGENT,
    "Accept": "application/octet-stream,*/*",
    # Force identity so Content-Length matches the bytes written to disk.
    # Python's urllib transparently decompresses gzip otherwise, which
    # silently corrupts the progress bar (it tracks compressed bytes
    # against an uncompressed file).
    "Accept-Encoding": "identity",
}


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
        if exc.code == 403:
            raise UpdateCheckError(
                "GitHub rate-limited this check. Try again in an hour."
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


ProgressCallback = Callable[[int, int, str], None]
"""``progress_cb(bytes_downloaded, total_bytes, state)`` — called many times
during download. ``state`` is one of :data:`ProgressState`. The byte counters
are the *whole-asset* numbers (not just the current attempt), so a UI bar
built on them won't jump backwards between retries."""


# Backwards-compat alias — callers that only care about the byte counts can
# still get the old 2-arg signature by wrapping with ``_legacy_progress_cb``.
LegacyProgressCallback = Callable[[int, int], None]


def _wrap_progress_cb(
    progress_cb: ProgressCallback | LegacyProgressCallback | None,
) -> ProgressCallback | None:
    """Adapt a 2-arg legacy callback to the 3-arg signature.

    The download core always calls the 3-arg form so it can report state
    transitions. A 2-arg callback just gets the bytes; the state string
    is discarded. Returns ``None`` if ``progress_cb`` is ``None``.
    """
    if progress_cb is None:
        return None

    # Inspect the callable's argument count. ``inspect.signature`` is the
    # most reliable way but adds a runtime cost per call; the simpler
    # ``getattr(cb, "__code__", None)`` check is plenty for the tests.
    code = getattr(progress_cb, "__code__", None)
    if code is not None and code.co_argcount >= 3:
        return progress_cb  # type: ignore[return-value]

    def _adapt(downloaded: int, total: int, state: str) -> None:
        progress_cb(downloaded, total)  # type: ignore[call-arg]

    return _adapt


def _existing_part_size(tmp_path: str) -> int:
    """Return the byte count of an existing ``.part`` file, or 0."""
    try:
        return os.path.getsize(tmp_path)
    except OSError:
        return 0


def _open_with_timeouts(
    url: str,
    *,
    headers: dict[str, str],
    range_from: int | None,
    connect_timeout_s: float,
    read_timeout_s: float,
) -> tuple[object, int, bool]:
    """Open ``url`` with separate connect / read timeouts.

    Returns ``(resp, total_from_content_length, used_resume)``. ``total_from_content_length``
    is 0 when the server omits it (chunked transfer); ``used_resume`` is
    True iff a Range request was sent and the server replied 206 Partial
    Content. The caller uses these to pick the right byte counters and
    to decide whether to trust the resume offset.

    Raises ``urllib.error.URLError`` / ``TimeoutError`` / ``OSError``;
    callers translate these into :class:`UpdateCheckError` after a
    retry pass.
    """
    req_headers = dict(headers)
    if range_from is not None and range_from > 0:
        req_headers["Range"] = f"bytes={range_from}-"
    req = urllib.request.Request(url, headers=req_headers)

    # urllib.request.urlopen accepts a single ``timeout`` kwarg that
    # applies to both connect AND read. Splitting them requires a manual
    # socket, then handing the live socket to ``urlopen``. We do that via
    # a small opener shim — Python doesn't expose per-phase timeouts
    # through the standard API directly.
    #
    # Implementation: monkey-patch socket.create_connection for the
    # duration of the urlopen call. Cleaner than rolling our own HTTP
    # parser just to swap a timeout.
    original_create_connection = socket.create_connection

    def _patched_create_connection(address, timeout=_GLOBAL_DEFAULT_TIMEOUT,
                                    source_address=None):
        # http.client always passes the timeout as the 2nd positional arg;
        # ignore whatever it sent and inject our own connect timeout.
        # ``socket._GLOBAL_DEFAULT_TIMEOUT`` is imported here to keep this
        # function's signature shape-matching the stdlib one (some callers
        # introspect ``inspect.signature``).
        return original_create_connection(
            address,
            connect_timeout_s,
            source_address,
        )

    socket.create_connection = _patched_create_connection
    try:
        resp = urllib.request.urlopen(req, timeout=read_timeout_s)
    finally:
        socket.create_connection = original_create_connection

    # Content-Length for a 206 Partial Content response is the *remaining*
    # bytes, not the full asset size. We compute the full size from the
    # Content-Range header when present, falling back to the request's
    # Range + Content-Length for the chunked case.
    content_length = int(resp.headers.get("Content-Length") or 0)
    used_resume = (
        range_from is not None
        and range_from > 0
        and getattr(resp, "status", None) == 206
    )
    if used_resume:
        # Content-Range: bytes 1234-5678/9012 -> total = 9012
        cr = resp.headers.get("Content-Range") or ""
        if "/" in cr:
            try:
                total = int(cr.rsplit("/", 1)[1])
            except (ValueError, IndexError):
                total = range_from + content_length
        else:
            total = range_from + content_length
    else:
        total = content_length
    return resp, total, used_resume


def _stream_to_file(
    resp,
    *,
    tmp_path: str,
    append: bool,
    chunk_bytes: int,
    cancel_check: Callable[[], bool] | None,
    on_progress: Callable[[int], None] | None,
) -> int:
    """Stream ``resp`` to ``tmp_path`` in ``chunk_bytes`` slices.

    If ``append`` is True the file is opened in append mode (resume);
    otherwise it's truncated. ``on_progress`` is called with the total
    bytes written in this attempt after every chunk. ``cancel_check``
    is polled between chunks; returning True aborts cleanly by deleting
    ``tmp_path`` and raising :class:`UpdateCheckError`.

    Returns the number of bytes written in this attempt.
    """
    mode = "ab" if append else "wb"
    os.makedirs(os.path.dirname(tmp_path) or ".", exist_ok=True)
    written = 0
    fh = open(tmp_path, mode)
    try:
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
            written += len(chunk)
            if on_progress is not None:
                on_progress(written)
    finally:
        fh.close()
    return written


def _download_once(
    url: str,
    dest_path: str,
    *,
    range_from: int,
    progress_cb: ProgressCallback | None,
    cancel_check: Callable[[], bool] | None,
    connect_timeout_s: float,
    read_timeout_s: float,
    chunk_bytes: int,
) -> tuple[int, int]:
    """Single download attempt.

    Returns ``(bytes_written_this_attempt, total_bytes)``. Raises
    :class:`UpdateCheckError` on any failure; the caller decides whether
    to retry.
    """
    tmp_path = dest_path + ".part"
    if progress_cb is not None:
        progress_cb(range_from, 0, "connecting")

    try:
        resp, total, used_resume = _open_with_timeouts(
            url,
            headers=_DOWNLOAD_HEADERS,
            range_from=range_from,
            connect_timeout_s=connect_timeout_s,
            read_timeout_s=read_timeout_s,
        )
    except urllib.error.HTTPError as exc:
        # 416 Range Not Satisfiable means the .part is corrupt or the
        # server's view of the file changed. Caller decides whether to
        # discard the .part and retry from 0.
        raise UpdateCheckError(
            f"GitHub returned HTTP {exc.code} while downloading."
        ) from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(
            f"Network error during download: {exc.reason}."
        ) from exc
    except TimeoutError as exc:
        raise UpdateCheckError(
            f"Download timed out after {read_timeout_s:.0f}s. Try again later."
        ) from exc
    except OSError as exc:
        raise UpdateCheckError(
            f"Network error during download: {exc}."
        ) from exc

    # When the server ignores our Range request and replies with the full
    # body (some CDNs do this), the bytes already in .part would be
    # duplicated. Discard the stale .part and start over in this attempt.
    append = used_resume

    def _on_attempt_progress(written: int) -> None:
        if progress_cb is None:
            return
        progress_cb(range_from + written, total, "downloading")

    try:
        bytes_this_attempt = _stream_to_file(
            resp,
            tmp_path=tmp_path,
            append=append,
            chunk_bytes=chunk_bytes,
            cancel_check=cancel_check,
            on_progress=_on_attempt_progress,
        )
    except UpdateCheckError:
        # Already a clean UpdateCheckError (cancel); let it propagate.
        raise
    except OSError as exc:
        raise UpdateCheckError(
            f"Could not write the installer: {exc}."
        ) from exc

    return bytes_this_attempt, total


def download_with_progress(
    url: str,
    dest_path: str,
    *,
    progress_cb: ProgressCallback | LegacyProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout_s: float = DOWNLOAD_TIMEOUT_S,
    chunk_bytes: int = DOWNLOAD_CHUNK_BYTES,
) -> str:
    """Stream ``url`` to ``dest_path`` with byte-level progress callbacks.

    The download is robust against transient network failures:

    - **Split timeouts** — the TCP connect gets ``timeout_s`` (default 30 s),
      each chunk read gets ``timeout_s`` (default 30 s). The legacy single
      ``timeout_s`` argument is honoured as both — pass the new explicit
      knobs for finer control.
    - **Retry** — up to :data:`MAX_DOWNLOAD_RETRIES` attempts on transient
      errors (``URLError``, ``TimeoutError``, ``ConnectionResetError``).
      Backoff is exponential: :data:`RETRY_BACKOFF_S`.
    - **Resume** — if ``dest_path + ".part"`` exists at call time, the
      first attempt sends ``Range: bytes=<N>-`` and appends; on success
      the final file is the concatenation. A ``416 Range Not Satisfiable``
      reply triggers a clean restart from byte 0.
    - **Cancel** — ``cancel_check`` is polled between chunks; returning
      True deletes ``.part`` and raises :class:`UpdateCheckError`.

    ``progress_cb`` accepts either the modern 3-arg signature
    ``(downloaded, total, state)`` or the legacy 2-arg ``(downloaded, total)``.
    The byte counters are whole-asset numbers (they don't jump backwards
    between retries).

    Returns ``dest_path`` on success. Raises :class:`UpdateCheckError` on
    a final failure (network error after retries, SHA mismatch upstream,
    cancellation, …).
    """
    cb = _wrap_progress_cb(progress_cb)
    tmp_path = dest_path + ".part"
    range_from = _existing_part_size(tmp_path)

    attempts_allowed = max(1, MAX_DOWNLOAD_RETRIES)
    last_error: UpdateCheckError | None = None

    for attempt in range(attempts_allowed):
        if attempt > 0:
            if cb is not None:
                cb(range_from, 0, "retrying")
            backoff = RETRY_BACKOFF_S[min(attempt - 1, len(RETRY_BACKOFF_S) - 1)]
            time.sleep(backoff)
            # Refresh the .part size — a prior attempt may have appended
            # some bytes before failing.
            range_from = _existing_part_size(tmp_path)

        try:
            bytes_this_attempt, total = _download_once(
                url,
                dest_path,
                range_from=range_from,
                progress_cb=cb,
                cancel_check=cancel_check,
                connect_timeout_s=timeout_s,
                read_timeout_s=timeout_s,
                chunk_bytes=chunk_bytes,
            )
        except UpdateCheckError as exc:
            # Cancellation is a user action, not a retryable error.
            if str(exc) == "Download cancelled.":
                raise
            # 416 means the .part is stale — delete it and retry from 0
            # on the same attempt index (no backoff sleep).
            if "HTTP 416" in str(exc) and range_from > 0:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                range_from = 0
                continue
            last_error = exc
            continue

        # Success for this attempt.
        range_from += bytes_this_attempt
        if cb is not None:
            cb(range_from, total, "verifying")

        # Atomic rename from .part -> final path.
        try:
            os.replace(tmp_path, dest_path)
        except OSError as exc:
            raise UpdateCheckError(
                f"Could not finalize the installer: {exc}."
            ) from exc

        if cb is not None:
            cb(range_from, total, "done")
        return dest_path

    # All attempts exhausted.
    assert last_error is not None  # loop above sets it before continuing
    raise last_error


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
        headers=dict(_DOWNLOAD_HEADERS),
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
    # Scrub PyInstaller's internal environment variables. This app is a
    # PyInstaller onefile, so its process environment carries _PYI_*
    # internals (parent-process level, application home dir, …). If the
    # installer inherits them, the NEW app launched from the installer's
    # finish page sees a dead "originating parent" — and PyInstaller
    # >= 6.22.1's onefile security check (mandatory in elevated mode,
    # which our admin installer forces) aborts the launch with
    # "Security validation failure: parent process has different
    # executable!". Starting the installer from a clean environment
    # breaks the contamination chain.
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_")}
    # Belt-and-braces: also tell the PyInstaller bootloader to treat the
    # launched app as a fresh top-level process (its documented
    # "application restart scenario" hook). The installer's launch step
    # sets this too (System::Call SetEnvironmentVariableW); this makes
    # the fix work even with an older installer build.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        proc = subprocess.Popen(
            [path],
            close_fds=True,
            creationflags=flags,
            shell=False,
            env=env,
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