"""
Configuration and Constants for Accessible Audio Editor

This module contains all configurable parameters for the audio processing
pipeline and GUI behavior.
"""

# ============================================================================
# Audio Processing Parameters
# ============================================================================

# Breath Detection Settings
BREATH_DETECTION = {
    'frame_ms': 50,              # Size of analysis frames in milliseconds
    'hop_ms': 25,                # Hop size between frames in milliseconds
    'rms_threshold': 0.02,       # Normalized RMS threshold (0-1)
    'max_duration_ms': 700,      # Maximum breath duration in milliseconds
}

# Breath Smoothing Strengths
# reduction_db: How much to reduce breath volume. Higher = more reduction.
# cutoff_hz: Lowpass filter cutoff. Lower = duller/more muffled breath sound.
# fade_ms: Crossfade duration for smooth edits.
# description: When to use each level.

BREATH_SMOOTHING_LEVELS = {
    'Disabled': {
        'reduction_db': 0,
        'cutoff_hz': 8000,
        'fade_ms': 0,
        'description': 'No breath processing applied.',
    },
    'Light': {
        'reduction_db': 3,
        'cutoff_hz': 6000,
        'fade_ms': 10,
        'description': 'Subtle smoothing. Keeps most breath character. Good for natural, unprocessed sound.',
    },
    'Medium': {
        'reduction_db': 6,
        'cutoff_hz': 5000,
        'fade_ms': 15,
        'description': 'Balanced. Noticeably softer breaths without sounding dull. Good general-purpose setting.',
    },
    'Heavy': {
        'reduction_db': 10,
        'cutoff_hz': 4000,
        'fade_ms': 20,
        'description': 'Aggressive smoothing. Removes most breath sounds. Use when breaths are very distracting.',
    }
}

# ============================================================================
# Equalizer Presets (5-band for voice)
# ============================================================================
# Each preset is a list of (frequency_hz, gain_db) tuples for 5 bands:
# Band 1: 100 Hz  - rumble/voice body
# Band 2: 300 Hz  - warmth vs honkiness
# Band 3: 1000 Hz - clarity/presence
# Band 4: 3000 Hz - articulation/punch
# Band 5: 8000 Hz - air/sibilance/brightness

EQ_PRESETS = {
    "Warm and rich": {
        "bands": [(100, 2), (300, 1), (1000, 1), (3000, 2), (8000, -1)],
        "description": "Adds body and warmth. Best for deeper male voices or recordings that sound thin or harsh."
    },
    "Bright and clear": {
        "bands": [(100, -2), (300, 0), (1000, 1), (3000, 3), (8000, 4)],
        "description": "Adds presence and clarity. Best for muffled recordings or softer voices."
    },
    "Radio/podcast ready": {
        "bands": [(100, -3), (300, -1), (1000, 1), (2500, 2), (10000, -2)],
        "description": "Professional broadcast sound. Reduces rumble, enhances voice warmth, gentle treble. Good all-purpose setting."
    },
    "Reduce boominess": {
        "bands": [(100, -6), (200, -4), (1000, 0), (3000, 1), (8000, 0)],
        "description": "Cuts low frequencies to reduce boomy or distant-sounding recordings. Good for USB microphones."
    },
    "Add presence": {
        "bands": [(100, -1), (300, 0), (1000, 1), (4000, 4), (8000, 1)],
        "description": "Adds punch and articulation around 4 kHz. Helps voice cut through music or background noise."
    },
    "Smooth harshness": {
        "bands": [(100, 0), (300, 0), (1000, -1), (3000, -4), (6000, -3)],
        "description": "Reduces harshness and sibilance. Good for recordings with sharp or tinny sound."
    },
    "Custom": {
        "bands": [(100, 0), (300, 0), (1000, 0), (3000, 0), (8000, 0)],
        "description": "Adjust the 5 frequency bands manually using the sliders."
    }
}

# ============================================================================
# Compressor Presets
# ============================================================================
# threshold_db: Sounds louder than this get compressed (typical: -24 to -14 dB)
# ratio: How much compression (higher = more squashed, typical: 2.5:1 to 6:1)
# attack_ms: How fast compression kicks in (slower = more natural)
# release_ms: How fast compression releases (slower = smoother)
# makeup_db: Gain added after compression to restore loudness

COMPRESSOR_PRESETS = {
    "Warm narration": {
        "threshold_db": -20,
        "ratio": 2.5,
        "attack_ms": 12,
        "release_ms": 120,
        "makeup_db": 3,
        "description": "Gentle, natural compression. Good for slow-paced speech, audiobooks, or calming content."
    },
    "Energetic delivery": {
        "threshold_db": -14,
        "ratio": 4.0,
        "attack_ms": 5,
        "release_ms": 50,
        "makeup_db": 4,
        "description": "Punchy and dynamic. Good for fast speech, motivational content, or performances with big volume swings."
    },
    "Gentle/podcast": {
        "threshold_db": -22,
        "ratio": 2.5,
        "attack_ms": 15,
        "release_ms": 150,
        "makeup_db": 2,
        "description": "Light touch. Preserves natural dynamics while evening out loud moments. Good for conversational podcasts."
    },
    "Voiceover/broadcast": {
        "threshold_db": -16,
        "ratio": 3.5,
        "attack_ms": 8,
        "release_ms": 80,
        "makeup_db": 4,
        "description": "Professional, consistent loudness. Good for commercial voiceovers, narration, or instructional videos."
    },
    "Breathy/female voice": {
        "threshold_db": -20,
        "ratio": 3.0,
        "attack_ms": 7,
        "release_ms": 60,
        "makeup_db": 3,
        "description": "Tuned for higher voices. Reduces peaks without squashing delicate breathiness. Good for soft or melodic voices."
    },
    "Custom": {
        "threshold_db": -20,
        "ratio": 4.0,
        "attack_ms": 5,
        "release_ms": 50,
        "makeup_db": 0,
        "description": "Adjust all compressor settings manually using the sliders."
    }
}

# Lowpass Filter Settings
FILTER_SETTINGS = {
    'default_cutoff_hz': 6000,   # Default cutoff frequency
    'filter_order': 4,            # Butterworth filter order
}

# Noise Reduction (future implementation)
NOISE_REDUCTION = {
    'min_value': 0.0,
    'max_value': 10.0,
    'default_value': 0.0,
}

# ============================================================================
# GUI Settings
# ============================================================================

# Window Geometry
WINDOW = {
    'default_width': 1200,
    'default_height': 800,
    'min_width': 800,
    'min_height': 600,
}

# Playback
PLAYBACK = {
    'seek_increment_ms': 5000,   # Seek amount with arrow keys (milliseconds)
    'update_rate_ms': 100,        # UI update rate during playback
}

# Supported Audio Formats
SUPPORTED_FORMATS = [
    'wav', 'mp3', 'ogg', 'flac', 'm4a'
]

AUDIO_FILTERS = "Audio Files (*.wav *.mp3 *.ogg *.flac);;All Files (*)"

# Export Formats
EXPORT_FORMATS = {
    '.wav': 'wav',
    '.mp3': 'mp3',
    '.ogg': 'ogg',
}

# ============================================================================
# Accessibility Settings
# ============================================================================

# Keyboard Shortcuts
SHORTCUTS = {
    'play_pause': 'Space',
    'stop': 'Escape',
    'seek_forward': 'Right',
    'seek_backward': 'Left',
    'open_file': 'Ctrl+O',
    'export_file': 'Ctrl+S',
}

# Control Labels (for screen readers)
ACCESSIBLE_LABELS = {
    'play_button': 'Play audio',
    'stop_button': 'Stop playback',
    'open_button': 'Open audio file',
    'timeline': 'Timeline position',
    'transcript': 'Transcription editor',
    'breath_control': 'Breath smoothing strength',
    'noise_control': 'Noise reduction amount',
}

# ============================================================================
# Transcription Settings
# ============================================================================

# Speech Recognition Engine
TRANSCRIPTION = {
    'engine': 'google',           # 'google', 'azure', 'openai' (future)
    'language': 'en-US',
    'timeout_seconds': 30,
}

# ============================================================================
# Processing Performance
# ============================================================================

# Threading
THREADING = {
    'max_workers': 2,             # Max concurrent processing threads
    'queue_size': 10,
}

# Memory Management
MEMORY = {
    'chunk_size_mb': 50,          # Chunk size for large file processing
    'max_undo_levels': 10,        # Future: undo stack size
}

# ============================================================================
# UI Colors and Styling (Light Theme)
# ============================================================================

COLORS = {
    'background': '#FFFFFF',
    'text': '#000000',
    'accent': '#0078D4',
    'button': '#E8E8E8',
    'button_hover': '#D0D0D0',
    'button_pressed': '#C0C0C0',
    'border': '#CCCCCC',
    'success': '#107C10',
    'error': '#D13438',
    'warning': '#FFB900',
}

# ============================================================================
# Development Settings
# ============================================================================

DEBUG = False                     # Set to True for debug output
LOG_LEVEL = 'INFO'               # DEBUG, INFO, WARNING, ERROR, CRITICAL
VERBOSE = False                  # Verbose output
