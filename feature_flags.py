"""SpeechCraft Studio feature flags.

Single source of truth for "is this feature enabled?" across the app.
Persists to ``~/.speechcraft/setup.json`` under the ``features`` key,
alongside the existing onboarding + auto-update keys.

Pure logic - no wx dependency so it can be tested in Linux CI.

Why a module instead of just reading the JSON dict inline?
- One place that defines what flags exist (FEATURE_NAMES, defaults)
- One place that normalises user input (load) so the rest of the app
  can trust the type of every value
- One mutation API (set_feature_flag) so we never race on stale reads
- Type-safe accessor pattern: ``flags.pedalboard_effects`` instead of
  ``flags_dict["pedalboard_effects"]`` everywhere

Read/write helpers are shared via :mod:`prefs` (used by
``onboarding_dialog``, ``audio_editor``'s auto-update wrappers, and
future ``feature_manager``). This module is just the schema + API.

Lifecycle:
- First launch -> defaults (everything on)
- Help -> Personalise SpeechCraft... reopens the wizard (v1.3.0+)
  and may toggle any flag
- A flag change takes effect on the next app launch; runtime code
  caches the value at frame construction time. The wizard pages that
  need immediate effect re-read flags after each toggle.

See docs/plans/2026-09-14-v1.3.0-roadmap.md for the broader v1.3.0 story.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Final

from prefs import load_prefs, save_prefs


# --- Paths ------------------------------------------------------------------

#: Where ``setup.json`` lives. ``%APPDATA%\\SpeechCraft`` on Windows,
#: ``~/.speechcraft`` on Linux/macOS dev runs. Mirrors onboarding_dialog.
if sys.platform == "win32":
    PREFS_DIR: Final = Path(os.environ.get("APPDATA", str(Path.home()))) / "SpeechCraft"
else:
    PREFS_DIR: Final = Path.home() / ".speechcraft"

PREFS_FILE: Final = PREFS_DIR / "setup.json"

#: Top-level key in setup.json where these flags live. Other keys
#: (``preferred_bundle``, ``skipped_versions``, ``auto_check_updates``)
#: continue to exist alongside it.
_FEATURES_KEY: Final = "features"

#: Top-level key in setup.json that records the wizard completing at
#: least once. v1.3.0-wizard-shell writes this; v1.2.0 callers keep
#: working unchanged because load_feature_flags() never reads it.
_WIZARD_COMPLETED_KEY: Final = "wizard_completed"


# --- Schema -----------------------------------------------------------------

#: Human-readable descriptions used in the wizard UI. Keep them short -
#: the wizard layout assumes one or two lines per feature.
FEATURE_DESCRIPTIONS: Final = {
    "basic_editing": (
        "Basic audio editing and effects. Always on - this is the "
        "foundation of SpeechCraft."
    ),
    "pedalboard_effects": (
        "Advanced effects from the Pedalboard library (EQ, compressors, "
        "reverb). Larger download."
    ),
    "local_transcription": (
        "Local AI transcription with faster-whisper. Runs on your "
        "machine - no cloud. Downloads a model on first use."
    ),
    "cloud_transcription": (
        "Cloud transcription via SpeechRecognition. Lighter than local, "
        "needs an internet connection."
    ),
    "destructive_editing": (
        "Destructive edit mode: lets you overwrite audio in place. "
        "Requires some form of transcription to align edits to words."
    ),
    "line_placing": (
        "Auto Line Placer: drop script lines onto the timeline "
        "automatically. Requires transcription."
    ),
    "edge_tts": (
        "Microsoft Edge TTS - many voices, free, needs internet."
    ),
    "piper_tts": (
        "Piper offline TTS - downloads voices on demand, runs locally."
    ),
}


def _build_defaults() -> dict[str, bool]:
    """All defaults for v1.3.0. Everything on - the wizard's job is to
    let the user opt out, not to surprise them with opt-in dialogs.
    """
    return {name: True for name in FEATURE_DESCRIPTIONS.keys()}


DEFAULT_FEATURE_FLAGS: Final = _build_defaults()

#: Public list of feature names. Ordered roughly by the wizard's
#: presentation: foundation, then effects, then transcription-derived,
#: then TTS. Callers iterate over this for UI construction.
FEATURE_NAMES: Final = (
    "basic_editing",
    "pedalboard_effects",
    "local_transcription",
    "cloud_transcription",
    "destructive_editing",
    "line_placing",
    "edge_tts",
    "piper_tts",
)


@dataclass(frozen=True)
class FeatureFlags:
    """The current state of every feature flag.

    Frozen so the only way to change a flag is through
    :func:`set_feature_flag`, which writes the new state to disk and
    returns the boolean. Frozen also gives us free ``__eq__`` for
    round-trip tests.
    """

    basic_editing: bool = True
    pedalboard_effects: bool = True
    local_transcription: bool = True
    cloud_transcription: bool = True
    destructive_editing: bool = True
    line_placing: bool = True
    edge_tts: bool = True
    piper_tts: bool = True

    def as_dict(self) -> dict[str, bool]:
        """Return as a plain dict (handy for JSON serialisation tests)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


# --- Read / write -----------------------------------------------------------



def _coerce_flag(name: str, raw: Any) -> bool:
    """Return a bool flag value, falling back to the default if ``raw``
    is not a real boolean.

    Rationale: a user who hand-edits setup.json and writes
    ``"piper_tts": "yes"`` should NOT have that flag silently enabled
    by a permissive truthiness check. We treat unknown types as
    "default" so the next wizard run shows the feature in its
    intended state and the user can re-decide explicitly.
    """
    if isinstance(raw, bool):
        return raw
    return DEFAULT_FEATURE_FLAGS[name]


def load_feature_flags(*, prefs_file: Path | None = None) -> FeatureFlags:
    """Load the current FeatureFlags from setup.json.

    Any flag missing from the file is defaulted. Any flag with a
    non-boolean value is defaulted (see :func:`_coerce_flag`). Unknown
    keys under ``features`` are silently ignored so a future version
    can add new flags without breaking older SpeechCraft installs.

    Always returns a valid :class:`FeatureFlags` - this is the contract
    every other module can rely on.
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    prefs = load_prefs(prefs_file=target)
    raw_features = prefs.get(_FEATURES_KEY) or {}
    if not isinstance(raw_features, dict):
        raw_features = {}

    kwargs: dict[str, bool] = {}
    for name in FEATURE_NAMES:
        kwargs[name] = _coerce_flag(name, raw_features.get(name))
    return FeatureFlags(**kwargs)


def save_feature_flags(
    *, prefs_file: Path | None = None, flags: FeatureFlags
) -> None:
    """Persist a complete :class:`FeatureFlags` to setup.json.

    Preserves any other top-level keys (preferred_bundle, auto_check_updates,
    skipped_versions) that other modules write. Only the ``features`` key
    is replaced.
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    prefs = load_prefs(prefs_file=target)
    prefs[_FEATURES_KEY] = flags.as_dict()
    save_prefs(prefs_file=target, prefs=prefs)


def set_feature_flag(
    *,
    prefs_file: Path | None = None,
    name: str,
    value: bool,
) -> bool:
    """Toggle a single flag and persist.

    Returns the new value (which equals ``value``). Raises
    :class:`KeyError` if ``name`` is not a known feature - typos in
    callers should fail loud, not silently no-op.

    Reads-modifies-writes the prefs file so concurrent writes from
    onboarding / auto-update code (preferred_bundle, auto_check_updates,
    skipped_versions) are preserved rather than stomped.
    """
    if name not in FEATURE_NAMES:
        raise KeyError(
            f"Unknown feature flag {name!r}. "
            f"Known flags: {sorted(FEATURE_NAMES)}"
        )

    target = prefs_file if prefs_file is not None else PREFS_FILE
    prefs = load_prefs(prefs_file=target)
    features = prefs.get(_FEATURES_KEY)
    if not isinstance(features, dict):
        features = {}
    features[name] = bool(value)
    prefs[_FEATURES_KEY] = features
    save_prefs(prefs_file=target, prefs=prefs)
    return bool(value)


# --- Wizard-completed marker (used by v1.3.0-wizard-shell) ------------------


def mark_wizard_completed(*, prefs_file: Path | None = None) -> None:
    """Record that the user has completed the setup wizard at least once.

    v1.3.0-wizard-shell calls this when the user clicks Finish on the
    wizard. v1.3.0-feature-manager uses the marker to decide whether
    to show the wizard on first launch (yes) versus only from the Help
    menu (no).
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    prefs = load_prefs(prefs_file=target)
    prefs[_WIZARD_COMPLETED_KEY] = True
    save_prefs(prefs_file=target, prefs=prefs)


def is_wizard_completed(*, prefs_file: Path | None = None) -> bool:
    """Return True iff :func:`mark_wizard_completed` has been called.

    Equivalent to ``prefs.get('wizard_completed', False)`` but exposes
    the schema key in one place.
    """
    target = prefs_file if prefs_file is not None else PREFS_FILE
    prefs = load_prefs(prefs_file=target)
    return bool(prefs.get(_WIZARD_COMPLETED_KEY, False))


__all__ = (
    "DEFAULT_FEATURE_FLAGS",
    "FEATURE_DESCRIPTIONS",
    "FEATURE_NAMES",
    "FeatureFlags",
    "PREFS_FILE",
    "is_wizard_completed",
    "load_feature_flags",
    "mark_wizard_completed",
    "save_feature_flags",
    "set_feature_flag",
)