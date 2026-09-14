"""SpeechCraft Studio feature gate logic.

Pure logic — no wx, no downloads. Decides, per feature, whether the
menu should show it and whether the wizard should offer a download.

Two inputs:
- ``flags`` — a :class:`feature_flags.FeatureFlags` (user choices)
- asset readiness — from :mod:`feature_manager` (is the download done?)

One output per feature: a :class:`FeatureGate`.

The gate layer is the single source of truth the menu bar and the
wizard both read, so they can't disagree about which features are
available.

See docs/plans/2026-09-14-v1.3.0-feature-toggling.md for the design.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from feature_flags import FeatureFlags
from feature_manager import is_downloadable, is_ready

#: The four possible states a feature can be in.
GateDecision = Literal["enabled", "needs_download", "disabled", "unavailable"]


#: Maps a feature flag to the feature_manager asset(s) it downloads.
#:
#: - ``None``          = no download (cloud feature, pip package, or
#:                       pure-logic capability).
#: - a 2-tuple ``(f,a)`` = one asset.
#: - a tuple of pairs    = multiple assets (e.g. piper_tts ships two
#:                       voices).
FEATURE_ASSET_MAP: Final = {
    "basic_editing": None,
    "pedalboard_effects": None,
    "local_transcription": ("local_transcription", "tiny.en"),
    "cloud_transcription": None,
    "destructive_editing": None,
    "line_placing": None,
    "edge_tts": None,
    "piper_tts": (
        ("piper_tts", "en_GB.cori"),
        ("piper_tts", "en_GB.alan"),
    ),
}


def feature_uses_asset(feature: str) -> list[tuple[str, str]] | None:
    """Return the ``(feature, asset)`` pair(s) for a feature, or None.

    - No download  -> None
    - One asset    -> [("local_transcription", "tiny.en")]
    - Two assets   -> [("piper_tts", "en_GB.cori"), ("piper_tts", "en_GB.alan")]

    The map stores a single asset as a 2-tuple of two strings, and a
    multi-asset feature as a tuple of pairs. This normalises both
    shapes to a list so callers can always iterate.
    """
    raw = FEATURE_ASSET_MAP.get(feature)
    if raw is None:
        return None
    # A 2-element tuple of two str values is ONE (feature, asset) pair.
    if (
        isinstance(raw, tuple)
        and len(raw) == 2
        and isinstance(raw[0], str)
        and isinstance(raw[1], str)
    ):
        return [raw]
    # A tuple of pairs (multi-asset feature).
    return [pair for pair in raw]


@dataclass(frozen=True)
class FeatureGate:
    """The gate decision for one feature.

    - ``feature``     the feature flag name.
    - ``enabled``     the user's choice (from ``FeatureFlags``).
    - ``has_asset``   whether this feature downloads anything.
    - ``asset_ready`` whether all its assets are on disk + verified.
    - ``decision``    the combined state the UI should act on.
    """
    feature: str
    enabled: bool
    has_asset: bool
    asset_ready: bool
    decision: GateDecision


def build_gates(
    flags: FeatureFlags,
    *,
    state_file: Path | None = None,
) -> dict[str, FeatureGate]:
    """Build a gate for every feature in :data:`FEATURE_ASSET_MAP`.

    Decision logic:

    - feature off                      -> ``disabled``
    - feature on, no asset             -> ``enabled``
    - feature on, all assets ready     -> ``enabled``
    - feature on, assets missing +
      downloadable                     -> ``needs_download``
    - feature on, assets missing +
      not downloadable (placeholder)   -> ``unavailable``
    """
    gates: dict[str, FeatureGate] = {}
    for feature in FEATURE_ASSET_MAP:
        enabled = bool(getattr(flags, feature, False))
        assets = feature_uses_asset(feature)
        has_asset = bool(assets)

        if not enabled:
            gates[feature] = FeatureGate(
                feature, False, has_asset, False, "disabled"
            )
            continue

        if not has_asset:
            gates[feature] = FeatureGate(
                feature, True, False, True, "enabled"
            )
            continue

        ready = all(is_ready(f, a, state_file=state_file) for f, a in assets)
        downloadable = all(is_downloadable(f, a) for f, a in assets)

        if ready:
            decision: GateDecision = "enabled"
        elif downloadable:
            decision = "needs_download"
        else:
            decision = "unavailable"

        gates[feature] = FeatureGate(feature, True, True, ready, decision)
    return gates


def gates_to_download_list(
    gates: dict[str, FeatureGate],
) -> list[tuple[str, str]]:
    """Return the ``(feature, asset)`` pairs the wizard should download.

    Only features that are enabled AND whose assets are not ready.
    Disabled features never appear (the user didn't ask for them).
    Order follows :data:`FEATURE_ASSET_MAP` (stable, deterministic).
    """
    result: list[tuple[str, str]] = []
    for gate in gates.values():
        if gate.decision != "needs_download":
            continue
        assets = feature_uses_asset(gate.feature)
        if assets:
            result.extend(assets)
    return result


__all__ = (
    "FEATURE_ASSET_MAP",
    "FeatureGate",
    "GateDecision",
    "build_gates",
    "feature_uses_asset",
    "gates_to_download_list",
)
