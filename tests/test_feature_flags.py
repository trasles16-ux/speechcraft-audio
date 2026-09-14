"""Tests for feature_flags.py.

The feature flags module is pure logic — no wx dependency — so these
tests run on Linux smoke CI as well as Windows full CI.

What we're testing:
- A `FeatureFlags` dataclass holds the schema for v1.3.0 toggles
- `load_feature_flags(prefs_file)` reads + normalises against defaults
- `save_feature_flags(prefs_file, flags)` writes back to JSON
- `set_feature_flag(prefs_file, name, value)` is the single-mutation API
- Unknown feature names raise (loud) so typos in callers are caught
- Missing/corrupt setup.json falls back to defaults, never raises
- Toggleable defaults are correct for a "vanilla" SpeechCraft install:
  basic editing on, everything else on, since v1.3.0 ships everything
  enabled and the wizard's job is to let the user *opt out*.

See docs/plans/2026-09-14-v1.3.0-roadmap.md for the broader v1.3.0 story.
"""

from __future__ import annotations

import json

import pytest

from feature_flags import (
    DEFAULT_FEATURE_FLAGS,
    FeatureFlags,
    FEATURE_DESCRIPTIONS,
    FEATURE_NAMES,
    load_feature_flags,
    save_feature_flags,
    set_feature_flag,
)


# --- Defaults --------------------------------------------------------------


def test_default_flags_keys():
    """Every feature should be in the defaults dict, even if just True."""
    expected = {
        "basic_editing",
        "pedalboard_effects",
        "local_transcription",
        "cloud_transcription",
        "destructive_editing",
        "line_placing",
        "edge_tts",
        "piper_tts",
    }
    assert set(DEFAULT_FEATURE_FLAGS.keys()) == expected


def test_default_flags_basic_editing_on():
    """Basic editing is the foundation - always on by default."""
    assert DEFAULT_FEATURE_FLAGS["basic_editing"] is True


def test_default_flags_destructive_requires_transcription():
    """Destructive editing + line-placing default on; they're paired with
    local_transcription in the wizard UI but each is its own flag here
    so the user can mix-and-match (e.g. destructive with cloud
    transcription)."""
    assert DEFAULT_FEATURE_FLAGS["destructive_editing"] is True
    assert DEFAULT_FEATURE_FLAGS["line_placing"] is True


def test_default_flags_tts_both_on():
    """Both TTS engines default on - user opts out if not wanted."""
    assert DEFAULT_FEATURE_FLAGS["edge_tts"] is True
    assert DEFAULT_FEATURE_FLAGS["piper_tts"] is True


def test_feature_names_constant_matches_defaults():
    """FEATURE_NAMES is the public list callers iterate over."""
    assert set(FEATURE_NAMES) == set(DEFAULT_FEATURE_FLAGS.keys())


def test_feature_descriptions_cover_every_name():
    """Every feature has a description shown in the wizard UI."""
    missing = [n for n in FEATURE_NAMES if n not in FEATURE_DESCRIPTIONS]
    assert missing == [], f"Features without descriptions: {missing}"


# --- Load / save round-trip -------------------------------------------------


def test_load_returns_defaults_when_file_missing(tmp_path):
    """First run: no setup.json -> defaults."""
    target = tmp_path / "setup.json"
    flags = load_feature_flags(prefs_file=target)
    assert flags.basic_editing is True
    assert flags.piper_tts is True


def test_load_returns_defaults_when_file_empty(tmp_path):
    """Empty file is treated the same as missing."""
    target = tmp_path / "setup.json"
    target.write_text("", encoding="utf-8")
    flags = load_feature_flags(prefs_file=target)
    assert flags.basic_editing is True


def test_load_returns_defaults_when_file_corrupt(tmp_path):
    """Corrupt JSON never crashes - falls back to defaults.

    A user editing setup.json by hand and breaking it shouldn't lock
    them out of SpeechCraft. Defaults are recoverable.
    """
    target = tmp_path / "setup.json"
    target.write_text("{not valid json", encoding="utf-8")
    flags = load_feature_flags(prefs_file=target)
    assert flags.basic_editing is True


def test_save_then_load_round_trip(tmp_path):
    """save() then load() returns the same flags."""
    target = tmp_path / "setup.json"
    flags = FeatureFlags(
        basic_editing=True,
        pedalboard_effects=False,
        local_transcription=True,
        cloud_transcription=False,
        destructive_editing=False,
        line_placing=False,
        edge_tts=True,
        piper_tts=False,
    )
    save_feature_flags(prefs_file=target, flags=flags)
    loaded = load_feature_flags(prefs_file=target)
    assert loaded == flags


def test_save_creates_parent_dir(tmp_path):
    """Save into a fresh %APAPDATA% should not crash if SpeechCraft/ doesn't exist yet."""
    target = tmp_path / "SpeechCraft" / "setup.json"
    flags = FeatureFlags()
    save_feature_flags(prefs_file=target, flags=flags)
    assert target.exists()


def test_load_partial_file_uses_defaults_for_missing_keys(tmp_path):
    """If setup.json has only some keys, missing ones default in."""
    target = tmp_path / "setup.json"
    target.write_text(
        json.dumps({"features": {"piper_tts": False}}),
        encoding="utf-8",
    )
    flags = load_feature_flags(prefs_file=target)
    assert flags.piper_tts is False
    # Everything else stays at default
    assert flags.basic_editing is True
    assert flags.edge_tts is True


def test_load_ignores_unknown_keys(tmp_path):
    """If setup.json has a key we don't recognise, ignore it (forward-compat)."""
    target = tmp_path / "setup.json"
    target.write_text(
        json.dumps(
            {
                "features": {
                    "basic_editing": True,
                    "future_feature_added_in_v2": "ignored",
                }
            }
        ),
        encoding="utf-8",
    )
    flags = load_feature_flags(prefs_file=target)
    assert flags.basic_editing is True


def test_load_coerces_non_bool_values(tmp_path):
    """Non-bool values for flags default rather than crashing.

    e.g. a user wrote "piper_tts": "yes" by hand. Treat as the default
    (True) rather than coercing, so we never silently enable/disable
    based on a typo.
    """
    target = tmp_path / "setup.json"
    target.write_text(
        json.dumps({"features": {"piper_tts": "yes", "edge_tts": 1}}),
        encoding="utf-8",
    )
    flags = load_feature_flags(prefs_file=target)
    assert flags.piper_tts == DEFAULT_FEATURE_FLAGS["piper_tts"]
    assert flags.edge_tts == DEFAULT_FEATURE_FLAGS["edge_tts"]


# --- set_feature_flag mutation API -----------------------------------------


def test_set_feature_flag_toggles_a_value(tmp_path):
    """set_feature_flag(name, value) updates the file and returns the new state."""
    target = tmp_path / "setup.json"
    # File doesn't exist yet -> starts at defaults
    assert set_feature_flag(
        prefs_file=target, name="piper_tts", value=False
    ) is False
    flags = load_feature_flags(prefs_file=target)
    assert flags.piper_tts is False
    # And again to flip it back
    assert set_feature_flag(
        prefs_file=target, name="piper_tts", value=True
    ) is True
    flags = load_feature_flags(prefs_file=target)
    assert flags.piper_tts is True


def test_set_feature_flag_preserves_other_flags(tmp_path):
    """Toggling one flag must not stomp on the others."""
    target = tmp_path / "setup.json"
    save_feature_flags(
        prefs_file=target,
        flags=FeatureFlags(piper_tts=False, edge_tts=False),
    )
    set_feature_flag(prefs_file=target, name="basic_editing", value=True)
    flags = load_feature_flags(prefs_file=target)
    assert flags.piper_tts is False  # untouched
    assert flags.edge_tts is False  # untouched


def test_set_feature_flag_unknown_name_raises(tmp_path):
    """Typo in a feature name should fail loud, not silently no-op."""
    target = tmp_path / "setup.json"
    with pytest.raises(KeyError):
        set_feature_flag(prefs_file=target, name="piper_tss", value=False)


def test_set_feature_flag_unknown_name_does_not_corrupt_file(tmp_path):
    """Bad name should raise AND leave the file in its previous state."""
    target = tmp_path / "setup.json"
    save_feature_flags(prefs_file=target, flags=FeatureFlags(piper_tts=False))
    with pytest.raises(KeyError):
        set_feature_flag(prefs_file=target, name="bogus", value=True)
    flags = load_feature_flags(prefs_file=target)
    assert flags.piper_tts is False  # unchanged


# --- FeatureFlags dataclass -------------------------------------------------


def test_feature_flags_dataclass_is_frozen():
    """Flags are immutable - use set_feature_flag() to mutate, not assignment."""
    flags = FeatureFlags()
    with pytest.raises((AttributeError, Exception)):
        flags.piper_tts = False  # type: ignore[misc]


def test_feature_flags_dataclass_equality():
    """Two FeatureFlags with the same values compare equal."""
    a = FeatureFlags()
    b = FeatureFlags()
    assert a == b
    c = FeatureFlags(piper_tts=False)
    assert a != c