"""Tests for the shared prefs module.

The prefs module is pure logic — no wx dependency — so these tests run
on Linux smoke CI as well as Windows full CI.

What we're testing:
- load_prefs / save_prefs are the canonical read/write helpers,
  formerly duplicated as _load_prefs / _save_prefs in onboarding_dialog
- PREFS_DIR / PREFS_FILE are the canonical path constants
- The helpers are tolerant of missing/empty/corrupt files
- Concurrent writes to other top-level keys are preserved
  (preferred_bundle, auto_check_updates, skipped_versions,
  wizard_completed, features)
"""

from __future__ import annotations

import json

import pytest

from prefs import (
    PREFS_DIR,
    PREFS_FILE,
    load_prefs,
    save_prefs,
)


def test_prefs_file_lives_under_known_dir():
    """PREFS_FILE must live under PREFS_DIR."""
    assert str(PREFS_FILE).startswith(str(PREFS_DIR))


def test_load_returns_empty_when_file_missing(tmp_path):
    """No file yet -> empty dict, never raises."""
    target = tmp_path / "speechcraft" / "setup.json"
    assert load_prefs(prefs_file=target) == {}


def test_load_returns_empty_when_file_corrupt(tmp_path):
    """Bad JSON -> empty dict, never raises (permissive read)."""
    target = tmp_path / "setup.json"
    target.write_text("{not valid", encoding="utf-8")
    assert load_prefs(prefs_file=target) == {}


def test_save_then_load_round_trip(tmp_path):
    """save then load returns the same dict."""
    target = tmp_path / "setup.json"
    save_prefs(prefs_file=target, prefs={"preferred_bundle": "Core", "n": 7})
    assert load_prefs(prefs_file=target) == {
        "preferred_bundle": "Core",
        "n": 7,
    }


def test_save_creates_parent_dir(tmp_path):
    """Save into a fresh SpeechCraft/ folder works."""
    target = tmp_path / "SpeechCraft" / "setup.json"
    save_prefs(prefs_file=target, prefs={"x": 1})
    assert target.exists()
    assert target.parent.is_dir()


def test_save_silent_on_oserror(tmp_path, monkeypatch):
    """Permission errors don't crash - we silently no-op."""
    target = tmp_path / "setup.json"

    def _boom_write_text(*args, **kwargs):
        raise PermissionError("simulated permission denied")

    monkeypatch.setattr("pathlib.Path.write_text", _boom_write_text)
    # Should NOT raise.
    save_prefs(prefs_file=target, prefs={"x": 1})


def test_save_does_not_silently_drop_other_keys_but_does_not_merge_them_either(tmp_path):
    """``save_prefs`` is a write-what-you-say. It does NOT merge with
    existing on-disk keys. If a caller wants to preserve other modules'
    keys, they must ``load_prefs`` first, mutate, then ``save_prefs``
    the full dict back.

    All current callers (onboarding, feature_flags, auto-update)
    already follow this read-modify-write pattern. This test pins the
    behaviour so nobody accidentally makes ``save_prefs`` do an
    implicit merge later (which would hide caller bugs).
    """
    target = tmp_path / "setup.json"
    save_prefs(
        prefs_file=target,
        prefs={
            "preferred_bundle": "Core",
            "auto_check_updates": True,
            "skipped_versions": ["1.2.0"],
            "features": {"piper_tts": False},
        },
    )
    # Naive caller forgets to load_prefs first.
    save_prefs(prefs_file=target, prefs={"wizard_completed": True})
    loaded = load_prefs(prefs_file=target)
    # Only wizard_completed survived. The other keys are gone -
    # that's the documented contract.
    assert loaded == {"wizard_completed": True}

    # But the correct read-modify-write pattern preserves them:
    merged = {**load_prefs(prefs_file=target), "x": 1}
    save_prefs(prefs_file=target, prefs=merged)
    assert load_prefs(prefs_file=target) == {
        "wizard_completed": True,
        "x": 1,
    }


def test_save_replaces_dict_at_top_level_not_deep_merge(tmp_path):
    """save_prefs does a top-level replace for the keys you pass.
    If you save ``features={'a': True}`` then save
    ``features={'b': True}``, the second wins - we don't deep-merge.

    Documenting this so callers know to send the full dict each time,
    not a partial update. (For per-flag mutation, use
    feature_flags.set_feature_flag, which does the read-modify-write
    internally.)
    """
    target = tmp_path / "setup.json"
    save_prefs(prefs_file=target, prefs={"features": {"a": True, "b": True}})
    save_prefs(prefs_file=target, prefs={"features": {"c": True}})
    loaded = load_prefs(prefs_file=target)
    assert loaded["features"] == {"c": True}


def test_load_handles_non_object_root(tmp_path):
    """If the JSON root is a list/number/string rather than an object,
    treat as empty (permissive)."""
    target = tmp_path / "setup.json"
    target.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert load_prefs(prefs_file=target) == {}
    target.write_text("42", encoding="utf-8")
    assert load_prefs(prefs_file=target) == {}


def test_save_uses_indent_for_human_readability(tmp_path):
    """Output JSON is indented so users can hand-edit safely."""
    target = tmp_path / "setup.json"
    save_prefs(prefs_file=target, prefs={"a": 1})
    raw = target.read_text(encoding="utf-8")
    # Indented JSON has newlines between keys.
    assert "\n" in raw
    assert json.loads(raw) == {"a": 1}