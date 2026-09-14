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