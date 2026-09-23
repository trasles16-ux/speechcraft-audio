"""Tests for the SpeechCraft update checker.

The updater is pure logic — no wx dependency — so these tests run on
Linux smoke CI as well as Windows full CI.
"""

from __future__ import annotations

import pytest

from updater import UpdateInfo, compare_versions, parse_release


def test_compare_versions_equal():
    assert compare_versions("1.2.0", "1.2.0") == 0


def test_compare_versions_older():
    assert compare_versions("1.1.4", "1.2.0") == -1


def test_compare_versions_newer():
    assert compare_versions("1.2.0", "1.1.4") == 1


def test_compare_versions_major_bump():
    assert compare_versions("1.9.9", "2.0.0") == -1
    assert compare_versions("2.0.0", "1.9.9") == 1


def test_compare_versions_handles_v_prefix():
    # GitHub release tags are commonly "v1.2.0" — strip the prefix.
    assert compare_versions("v1.2.0", "v1.1.4") == 1


def test_compare_versions_handles_missing_patch():
    # "1.2" should compare equal to "1.2.0".
    assert compare_versions("1.2", "1.2.0") == 0


def test_parse_release_extracts_fields():
    """Parse the JSON shape GitHub's /releases/latest endpoint returns."""
    payload = {
        "tag_name": "v1.3.0",
        "html_url": "https://github.com/trasles16-ux/speechcraft-audio/releases/tag/v1.3.0",
        "name": "SpeechCraft Studio v1.3.0",
        "body": "Bug fixes and a new feature.",
        "published_at": "2026-10-01T12:00:00Z",
        "prerelease": False,
    }
    info = parse_release(payload)
    assert info.version == "1.3.0"
    assert info.url == payload["html_url"]
    assert info.title == "SpeechCraft Studio v1.3.0"
    assert info.is_prerelease is False


def test_update_info_is_newer_property():
    older = UpdateInfo(version="1.1.4", url="x", title="t", notes="", published_at="")
    newer = UpdateInfo(version="1.2.0", url="x", title="t", notes="", published_at="")
    assert newer.is_newer_than("1.1.4") is True
    assert older.is_newer_than("1.2.0") is False
    assert newer.is_newer_than("1.2.0") is False  # equal → not newer


# --- Task 7: download / verify / parse-with-assets ---------------------------

from updater import (  # noqa: E402
    AssetInfo,
    download_with_progress,
    fetch_expected_sha256,
    sha256_of_file,
    verify_asset_sha256,
)


def test_parse_release_includes_assets():
    payload = {
        "tag_name": "v1.3.0",
        "html_url": "https://github.com/x/y/releases/tag/v1.3.0",
        "name": "v1.3.0",
        "body": "notes",
        "published_at": "2026-10-01T00:00:00Z",
        "prerelease": False,
        "assets": [
            {
                "name": "SpeechCraft_Studio_Setup.exe",
                "browser_download_url": "https://example.com/setup.exe",
                "size": 51_234_567,
            }
        ],
    }
    info = parse_release(payload)
    assert len(info.assets) == 1
    assert info.assets[0].name == "SpeechCraft_Studio_Setup.exe"
    assert info.assets[0].size_mb == pytest.approx(48.86, abs=0.01)


def test_find_installer_picks_setup_exe():
    info = UpdateInfo(
        version="1.3.0",
        url="x",
        title="t",
        notes="",
        published_at="",
        assets=(
            AssetInfo(name="CHANGELOG.md", url="x", size_bytes=100),
            AssetInfo(name="SpeechCraft_Studio_Setup.exe", url="y", size_bytes=100),
            AssetInfo(name="SpeechCraft_Studio.zip", url="z", size_bytes=100),
        ),
    )
    installer = info.find_installer()
    assert installer is not None
    assert installer.name == "SpeechCraft_Studio_Setup.exe"


def test_find_installer_returns_none_when_absent():
    info = UpdateInfo(
        version="1.3.0",
        url="x",
        title="t",
        notes="",
        published_at="",
        assets=(AssetInfo(name="CHANGELOG.md", url="x", size_bytes=100),),
    )
    assert info.find_installer() is None


def test_download_creates_missing_staging_dir(tmp_path):
    """Regression: download_with_progress must create the destination
    directory if it doesn't exist. On a fresh install the staging
    folder (%LOCALAPPDATA%\\SpeechCraft\\updates) is absent, so the
    previous open() raised FileNotFoundError and the update died with
    '[Errno 2] No such file or directory'.

    We stand up a tiny local HTTP server that serves a few bytes, then
    point the downloader at a path whose parent doesn't exist yet.
    """
    import http.server
    import threading

    # Serve the bytes from a temp file over a real local socket so the
    # urllib code path is exercised for real (no mocks).
    src = tmp_path / "serve" / "setup.exe"
    src.parent.mkdir()
    payload = b"A" * 2048
    src.write_bytes(payload)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass  # keep test output clean

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        # Destination lives under a NON-EXISTING nested dir.
        dest = tmp_path / "updates" / "speechcraft" / "SpeechCraft-Setup-1.3.0.exe"
        assert not dest.parent.exists()  # precondition

        result = download_with_progress(
            f"http://127.0.0.1:{port}/setup.exe",
            str(dest),
        )

        assert result == str(dest)
        # The dir now exists and holds the full payload
        assert dest.parent.exists()
        assert dest.read_bytes() == payload
        # No leftover .part
        assert not (tmp_path / "updates" / "speechcraft" / "SpeechCraft-Setup-1.3.0.exe.part").exists()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_sha256_of_file_roundtrip(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello world")
    digest = sha256_of_file(str(p))
    # Known SHA-256 of "hello world"
    assert digest == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_verify_asset_sha256_true_on_match(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello world")
    assert verify_asset_sha256(
        str(p), "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )


def test_verify_asset_sha256_false_on_mismatch(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello world")
    assert verify_asset_sha256(str(p), "0" * 64) is False


# --- Task: v1.3.5 update-download reliability --------------------------------


def test_download_sends_accept_headers(tmp_path):
    """The download must include Accept: application/octet-stream and
    Accept-Encoding: identity. Without these, GitHub's CDN sometimes
    responds with HTML (a 'Terms of Service' interstitial) and the
    progress bar sits at 0% while the bytes never land on disk.
    """
    import http.server
    import threading

    captured: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            for k, v in self.headers.items():
                captured[k] = v
            payload = b"x" * 8
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        dest = tmp_path / "out.bin"
        download_with_progress(
            f"http://127.0.0.1:{port}/x",
            str(dest),
            timeout_s=10.0,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert captured.get("Accept") == "application/octet-stream,*/*"
    assert captured.get("Accept-Encoding") == "identity"
    assert "SpeechCraft-Studio-UpdateChecker" in captured.get("User-Agent", "")


def test_download_progress_cb_receives_state(tmp_path):
    """The progress callback gets the new ``state`` string so the UI can
    distinguish "connecting" from "downloading" from "verifying"."""
    import http.server
    import threading

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b"P" * 4096
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    states_seen: list[str] = []

    def _cb(downloaded: int, total: int, state: str) -> None:
        states_seen.append(state)

    try:
        download_with_progress(
            f"http://127.0.0.1:{port}/x",
            str(tmp_path / "out.bin"),
            progress_cb=_cb,
            timeout_s=10.0,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    # At minimum we expect the connecting handshake, at least one
    # downloading chunk, and the final verifying + done transitions.
    assert "connecting" in states_seen
    assert "downloading" in states_seen
    assert "verifying" in states_seen
    assert "done" in states_seen


def test_download_progress_cb_legacy_two_arg_still_works(tmp_path):
    """Old callers using the 2-arg ``(downloaded, total)`` signature must
    keep working — the wrapper drops the state argument for them."""
    import http.server
    import threading

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b"Q" * 512
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    received: list[tuple[int, int]] = []

    def _legacy_cb(downloaded: int, total: int) -> None:
        received.append((downloaded, total))

    try:
        download_with_progress(
            f"http://127.0.0.1:{port}/x",
            str(tmp_path / "out.bin"),
            progress_cb=_legacy_cb,
            timeout_s=10.0,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert received, "legacy 2-arg callback was never invoked"
    # Last tick should have downloaded == total (full payload arrived).
    assert received[-1][0] == received[-1][1] == 512


def test_download_retries_on_transient_url_error(tmp_path, monkeypatch):
    """A single transient error on attempt 1 must be retried; attempt 2
    succeeds. The final on-disk file is the full payload."""
    import http.server
    import threading

    get_count = {"n": 0}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            get_count["n"] += 1
            if get_count["n"] == 1:
                # Hang the connection closed without sending any bytes so
                # urllib raises a URLError.
                self.close_connection = True
                return
            payload = b"R" * 256
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # Patch the retry backoff down to nothing so the test stays fast.
    import updater
    monkeypatch.setattr(updater, "RETRY_BACKOFF_S", (0.0, 0.0, 0.0))

    try:
        dest = tmp_path / "out.bin"
        download_with_progress(
            f"http://127.0.0.1:{port}/x",
            str(dest),
            timeout_s=10.0,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert get_count["n"] >= 2  # we did retry
    assert dest.read_bytes() == b"R" * 256


def test_download_resumes_from_existing_part(tmp_path):
    """If a `.part` file is on disk at call time, the next attempt sends
    ``Range: bytes=N-`` and the final file is the concatenation of the
    .part bytes and the new bytes."""
    import http.server
    import threading

    pre = b"X" * 256
    remaining = b"Y" * 256
    full = pre + remaining

    dest = tmp_path / "setup.exe"
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(pre)

    captured_range: list[str | None] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            captured_range.append(self.headers.get("Range"))
            if self.headers.get("Range"):
                self.send_response(206)
                self.send_header(
                    "Content-Range",
                    f"bytes {len(pre)}-{len(full) - 1}/{len(full)}",
                )
                self.send_header("Content-Length", str(len(remaining)))
                self.end_headers()
                self.wfile.write(remaining)
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(len(full)))
                self.end_headers()
                self.wfile.write(full)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        download_with_progress(
            f"http://127.0.0.1:{port}/x",
            str(dest),
            timeout_s=10.0,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert captured_range and captured_range[0] == f"bytes={len(pre)}-"
    assert dest.read_bytes() == full
    assert not part.exists()


def test_download_restarts_from_zero_on_416(tmp_path):
    """When the server replies 416 Range Not Satisfiable, the downloader
    discards the .part and retries from byte 0."""
    import http.server
    import threading

    payload = b"Z" * 128
    dest = tmp_path / "setup.exe"
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(b"stale-bytes-that-arent-from-this-build" * 100)

    attempt_count = {"n": 0}
    captured_ranges: list[str | None] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            attempt_count["n"] += 1
            rng = self.headers.get("Range")
            captured_ranges.append(rng)
            if attempt_count["n"] == 1 and rng:
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    import updater
    original = updater.RETRY_BACKOFF_S
    updater.RETRY_BACKOFF_S = (0.0, 0.0, 0.0)
    try:
        download_with_progress(
            f"http://127.0.0.1:{port}/x",
            str(dest),
            timeout_s=10.0,
        )
    finally:
        updater.RETRY_BACKOFF_S = original
        httpd.shutdown()
        httpd.server_close()

    assert attempt_count["n"] == 2
    assert dest.read_bytes() == payload
    assert not part.exists()


def test_download_cancel_stops_without_retry(tmp_path):
    """User cancel must NOT trigger a retry — the worker is gone."""
    import http.server
    import threading

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b"C" * 4096
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    cancelled = {"v": False}

    def _is_cancelled() -> bool:
        return cancelled["v"]

    try:
        cancelled["v"] = True
        from updater import UpdateCheckError
        with pytest.raises(UpdateCheckError, match="cancelled"):
            download_with_progress(
                f"http://127.0.0.1:{port}/x",
                str(tmp_path / "out.bin"),
                cancel_check=_is_cancelled,
                timeout_s=10.0,
            )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert not (tmp_path / "out.bin.part").exists()