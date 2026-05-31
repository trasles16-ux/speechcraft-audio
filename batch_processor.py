"""
Batch Processor for SpeechCraft Studio.

Applies audio effects to all supported files in a folder, with progress reporting.
"""
import os
import glob
from pydub import AudioSegment
import audio_effects
import breath_smoothing
import config

# Supported audio file extensions
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}


def get_audio_files(folder_path):
    """Return sorted list of audio file paths in a folder (non-recursive)."""
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(glob.glob(os.path.join(folder_path, f"*{ext}")))
        files.extend(glob.glob(os.path.join(folder_path, f"*{ext.upper()}")))
    return sorted(set(files))


def apply_effect_to_file(input_path, output_path, effect_type, params):
    """Load an audio file, apply the given effect, and save to output_path.
    
    Args:
        input_path: Path to input audio file
        output_path: Path to write processed audio (same format as input)
        effect_type: str — 'breath', 'compressor', 'eq', 'normalize', 'denoise', 'room', 'deesser'
        params: dict — effect-specific parameters
    
    Returns:
        (success: bool, message: str)
    """
    try:
        seg = AudioSegment.from_file(input_path)
    except Exception as e:
        return False, f"Could not load: {e}"

    try:
        if effect_type == "breath":
            seg = _apply_breath(seg, params)
        elif effect_type == "compressor":
            seg = _apply_compressor(seg, params)
        elif effect_type == "eq":
            seg = _apply_eq(seg, params)
        elif effect_type == "normalize":
            seg = _apply_normalize(seg, params)
        elif effect_type == "denoise":
            seg = _apply_denoise(seg, params)
        elif effect_type == "room":
            seg = _apply_room(seg, params)
        elif effect_type == "deesser":
            seg = _apply_deesser(seg, params)
        else:
            return False, f"Unknown effect type: {effect_type}"

        # Determine output format from extension
        ext = os.path.splitext(output_path)[1].lower()
        seg.export(output_path, format=_ext_to_format(ext))
        return True, "OK"
    except Exception as e:
        return False, f"Processing error: {e}"


def _ext_to_format(ext):
    """Map file extension to pydub export format string."""
    mapping = {
        ".wav": "wav",
        ".mp3": "mp3",
        ".flac": "flac",
        ".ogg": "ogg",
        ".m4a": "mp4",
        ".aac": "mp4",
        ".wma": "wma",
    }
    return mapping.get(ext, "wav")


def _apply_breath(seg, params):
    """Apply breath smoothing using isolated temp files."""
    import tempfile

    # Use isolated temp files — not hardcoded names (avoids cross-process collisions)
    fd_in, temp_in = tempfile.mkstemp(suffix=".wav")
    fd_out, temp_out = tempfile.mkstemp(suffix=".wav")
    os.close(fd_in)
    os.close(fd_out)

    try:
        seg.export(temp_in, format="wav")
        breath_smoothing.process_file(
            temp_in,
            temp_out,
            reduction_db=params.get("reduction_db", 6),
            rms_thresh=params.get("rms_thresh", 0.02),
            dry_wet=params.get("dry_wet", 1.0),
        )
        result = AudioSegment.from_file(temp_out)
    finally:
        # Always clean up, even on error
        for path in (temp_in, temp_out):
            try:
                os.remove(path)
            except OSError:
                pass

    return result


def _apply_compressor(seg, params):
    eff = audio_effects.PB_Compressor(
        threshold_db=params.get("threshold_db", -20),
        ratio=params.get("ratio", 4.0),
        attack_ms=params.get("attack_ms", 5.0),
        release_ms=params.get("release_ms", 50.0),
        makeup_db=params.get("makeup_db", 0.0),
    )
    return eff.apply(seg)


def _apply_eq(seg, params):
    bands = params.get("bands", [(100, 0), (300, 0), (1000, 0), (3000, 0), (8000, 0)])
    eff = audio_effects.Equalizer(bands=bands)
    return eff.apply(seg)


def _apply_normalize(seg, params):
    eff = audio_effects.PB_Normalizer(target_db=params.get("target_db", -1.0))
    return eff.apply(seg)


def _apply_denoise(seg, params):
    eff = audio_effects.PB_NoiseGate(threshold_db=params.get("threshold_db", -40.0))
    return eff.apply(seg)


def _apply_room(seg, params):
    eff = audio_effects.RoomToneRemover(sensitivity=params.get("sensitivity", 0.5))
    return eff.apply(seg)


def _apply_deesser(seg, params):
    eff = audio_effects.DeEsser(threshold_db=params.get("threshold_db", -20.0))
    return eff.apply(seg)


# ---------------------------------------------------------------------------
# Effect definitions for the UI
# ---------------------------------------------------------------------------
EFFECT_DEFINITIONS = {
    "breath": {
        "label": "Breath Smoothing",
        "presets": {k: v for k, v in config.BREATH_SMOOTHING_LEVELS.items() if k != "Disabled"},
        "default_params": {"reduction_db": 6, "rms_thresh": 0.02, "dry_wet": 1.0},
        "uses_preset_system": True,
    },
    "compressor": {
        "label": "Compressor",
        "presets": {k: v for k, v in config.COMPRESSOR_PRESETS.items() if k != "Custom"},
        "default_params": {"threshold_db": -20, "ratio": 4.0, "attack_ms": 5.0, "release_ms": 50.0, "makeup_db": 0.0},
        "uses_preset_system": True,
    },
    "eq": {
        "label": "Equalizer",
        "presets": {k: v for k, v in config.EQ_PRESETS.items() if k != "Custom"},
        "default_params": {"bands": [(100, 0), (300, 0), (1000, 0), (3000, 0), (8000, 0)]},
        "uses_preset_system": True,
    },
    "normalize": {
        "label": "Normalize",
        "presets": {},
        "default_params": {"target_db": -1.0},
        "uses_preset_system": False,
    },
    "denoise": {
        "label": "Denoise / Noise Gate",
        "presets": {},
        "default_params": {"threshold_db": -40.0},
        "uses_preset_system": False,
    },
    "room": {
        "label": "Room Tone Remover",
        "presets": {},
        "default_params": {"sensitivity": 0.5},
        "uses_preset_system": False,
    },
    "deesser": {
        "label": "De-esser",
        "presets": {},
        "default_params": {"threshold_db": -20.0},
        "uses_preset_system": False,
    },
}
