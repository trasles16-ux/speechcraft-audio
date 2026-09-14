"""Tests for feature_toggling (pure logic, no wx, no network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from feature_flags import FeatureFlags
from feature_toggling import (
    FEATURE_ASSET_MAP,
    FeatureGate,
    build_gates,
    feature_uses_asset,
    gates_to_download_list,
)


# --- feature_uses_asset -----------------------------------------------------


def test_feature_uses_asset_maps_local_transcription_to_tiny_en() -> None:
    assert feature_uses_asset("local_transcription") == [
        ("local_transcription", "tiny.en")
    ]


def test_feature_uses_asset_maps_piper_tts_to_both_voices() -> None:
    assert feature_uses_asset("piper_tts") == [
        ("piper_tts", "en_GB.cori"),
        ("piper_tts", "en_GB.alan"),
    ]


def test_feature_uses_asset_none_for_edge_tts() -> None:
    assert feature_uses_asset("edge_tts") is None


def test_feature_uses_asset_none_for_pedalboard() -> None:
    assert feature_uses_asset("pedalboard_effects") is None


def test_feature_uses_asset_none_for_basic_editing() -> None:
    assert feature_uses_asset("basic_editing") is None


def test_feature_uses_asset_unknown_feature_returns_none() -> None:
    assert feature_uses_asset("does_not_exist") is None


# --- build_gates ------------------------------------------------------------


def test_basic_editing_is_always_enabled() -> None:
    flags = FeatureFlags(
        basic_editing=True,
        pedalboard_effects=False,
        local_transcription=False,
        cloud_transcription=False,
        destructive_editing=False,
        line_placing=False,
        edge_tts=False,
        piper_tts=False,
    )
    gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    assert gates["basic_editing"].decision == "enabled"
    assert gates["basic_editing"].enabled is True


def test_disabled_feature_gate_is_disabled() -> None:
    flags = FeatureFlags(piper_tts=False, edge_tts=False,
                         local_transcription=False, cloud_transcription=False,
                         pedalboard_effects=False, destructive_editing=False,
                         line_placing=False, basic_editing=True)
    gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    assert gates["piper_tts"].decision == "disabled"
    assert gates["piper_tts"].enabled is False


def test_enabled_no_asset_feature_is_enabled() -> None:
    flags = FeatureFlags(
        edge_tts=True,
        basic_editing=True, pedalboard_effects=False,
        local_transcription=False, cloud_transcription=False,
        destructive_editing=False, line_placing=False, piper_tts=False,
    )
    gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    assert gates["edge_tts"].decision == "enabled"
    assert gates["edge_tts"].has_asset is False
    assert gates["edge_tts"].asset_ready is True


def test_enabled_feature_with_missing_asset_is_needs_download() -> None:
    flags = FeatureFlags(
        local_transcription=True,
        basic_editing=True, pedalboard_effects=False,
        cloud_transcription=False, destructive_editing=False,
        line_placing=False, edge_tts=False, piper_tts=False,
    )
    # is_ready returns False for the missing asset
    with patch("feature_toggling.is_ready", return_value=False):
        gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    assert gates["local_transcription"].decision == "needs_download"
    assert gates["local_transcription"].enabled is True
    assert gates["local_transcription"].has_asset is True
    assert gates["local_transcription"].asset_ready is False


def test_enabled_feature_with_ready_asset_is_enabled() -> None:
    flags = FeatureFlags(
        local_transcription=True,
        basic_editing=True, pedalboard_effects=False,
        cloud_transcription=False, destructive_editing=False,
        line_placing=False, edge_tts=False, piper_tts=False,
    )
    with patch("feature_toggling.is_ready", return_value=True):
        gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    assert gates["local_transcription"].decision == "enabled"
    assert gates["local_transcription"].asset_ready is True


def test_piper_needs_download_when_either_voice_missing() -> None:
    flags = FeatureFlags(
        piper_tts=True,
        basic_editing=True, pedalboard_effects=False,
        local_transcription=False, cloud_transcription=False,
        destructive_editing=False, line_placing=False, edge_tts=False,
    )
    # cori ready, alan missing → overall needs_download
    def _ready_side(f, a, **kw):
        return a == "en_GB.cori"  # only cori is ready
    with patch("feature_toggling.is_ready", side_effect=_ready_side):
        gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    assert gates["piper_tts"].decision == "needs_download"
    assert gates["piper_tts"].asset_ready is False


def test_piper_enabled_when_both_voices_ready() -> None:
    flags = FeatureFlags(
        piper_tts=True,
        basic_editing=True, pedalboard_effects=False,
        local_transcription=False, cloud_transcription=False,
        destructive_editing=False, line_placing=False, edge_tts=False,
    )
    with patch("feature_toggling.is_ready", return_value=True):
        gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    assert gates["piper_tts"].decision == "enabled"
    assert gates["piper_tts"].asset_ready is True


# --- gates_to_download_list -------------------------------------------------


def test_gates_to_download_list_returns_empty_when_nothing_missing() -> None:
    flags = FeatureFlags(
        local_transcription=True, piper_tts=True,
        pedalboard_effects=False, cloud_transcription=False,
        destructive_editing=False, line_placing=False,
        edge_tts=False, basic_editing=True,
    )
    with patch("feature_toggling.is_ready", return_value=True):
        gates = build_gates(flags, state_file=Path("/tmp/never.json"))
        assert gates_to_download_list(gates) == []


def test_gates_to_download_list_returns_missing_assets() -> None:
    flags = FeatureFlags(
        local_transcription=True, piper_tts=True,
        pedalboard_effects=False, cloud_transcription=False,
        destructive_editing=False, line_placing=False,
        edge_tts=False, basic_editing=True,
    )
    with patch("feature_toggling.is_ready", return_value=False):
        gates = build_gates(flags, state_file=Path("/tmp/never.json"))
        pairs = gates_to_download_list(gates)
    # tiny.en + cori + alan = 3 pairs
    assert ("local_transcription", "tiny.en") in pairs
    assert ("piper_tts", "en_GB.cori") in pairs
    assert ("piper_tts", "en_GB.alan") in pairs
    assert len(pairs) == 3


def test_gates_to_download_list_excludes_disabled_features() -> None:
    """A disabled feature's assets never appear in the download list,
    even if they aren't ready."""
    flags = FeatureFlags(
        piper_tts=False,  # disabled
        local_transcription=True,
        pedalboard_effects=False, cloud_transcription=False,
        destructive_editing=False, line_placing=False,
        edge_tts=False, basic_editing=True,
    )
    with patch("feature_toggling.is_ready", return_value=False):
        gates = build_gates(flags, state_file=Path("/tmp/never.json"))
        pairs = gates_to_download_list(gates)
    # piper_tts is disabled → its voices must NOT be in the list
    assert ("piper_tts", "en_GB.cori") not in pairs
    assert ("piper_tts", "en_GB.alan") not in pairs
    # local_transcription is enabled + missing → it IS in the list
    assert ("local_transcription", "tiny.en") in pairs


def test_build_gates_returns_gate_for_every_feature() -> None:
    flags = FeatureFlags()
    gates = build_gates(flags, state_file=Path("/nonexistent/state.json"))
    for feature in FEATURE_ASSET_MAP:
        assert feature in gates, f"missing gate for {feature}"
        assert isinstance(gates[feature], FeatureGate)


def test_feature_gate_is_frozen() -> None:
    g = FeatureGate("x", True, False, True, "enabled")
    with pytest.raises(Exception):
        g.feature = "y"  # type: ignore
