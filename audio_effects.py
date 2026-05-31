"""
Audio Effects Library for SpeechCraft - Powered by Pedalboard
Provides professional-grade audio processing using Spotify's Pedalboard library.
"""

import numpy as np
from pydub import AudioSegment
import pedalboard
from pedalboard import (
    Pedalboard, Compressor, NoiseGate, Gain, HighpassFilter, LowpassFilter,
    PeakFilter, Limiter
)

class AudioEffect:
    """Base class for all audio effects"""
    def apply(self, audio, sample_rate=None):
        """Apply effect to either AudioSegment or numpy array"""
        if isinstance(audio, AudioSegment):
            return self.apply_to_segment(audio)
        else:
            if sample_rate is None:
                raise ValueError("sample_rate must be provided for numpy arrays")
            return self.apply_to_numpy(audio, sample_rate)

    def apply_to_numpy(self, samples, sample_rate):
        """Should be overridden by subclasses or use the Pedalboard path"""
        raise NotImplementedError

    def apply_to_segment(self, segment):
        # Convert segment to numpy (Float32)
        samples = np.array(segment.get_array_of_samples()).astype(np.float32)

        # Normalize to -1.0 to 1.0 (Pedalboard expects this)
        max_val = float(1 << (8 * segment.sample_width - 1))
        samples = samples / max_val

        # Reshape to (channels, samples) which is what Pedalboard expects
        if segment.channels > 1:
            # Pad with zero if odd number of samples (corrupt/incomplete frame)
            if samples.size % segment.channels != 0:
                samples = np.pad(samples, (0, segment.channels - samples.size % segment.channels),
                                mode='constant', constant_values=0)
            samples = samples.reshape((-1, segment.channels)).T
        else:
            samples = samples.reshape((1, -1))

        # Apply effect
        processed = self.apply_to_numpy(samples, segment.frame_rate)

        # Convert back
        if segment.channels > 1:
            processed = processed.T.flatten()
        else:
            processed = processed.flatten()

        processed = (processed * (max_val - 1)).astype(np.int16)
        return segment._spawn(processed.tobytes())

class PedalboardEffect(AudioEffect):
    """Effect wrapper for Pedalboard objects"""
    def __init__(self, board: Pedalboard):
        self.board = board

    def apply_to_numpy(self, samples, sample_rate):
        # samples is (channels, n_samples)
        return self.board(samples, sample_rate)

class PB_Compressor(AudioEffect):
    """Pedalboard-backed Compressor with full parameter control.

    Parameters:
        threshold_db: Sounds louder than this get compressed. Range: -60 to 0 dB.
            Typical voice: -24 (gentle) to -14 (aggressive) dB.
        ratio: How much compression is applied above threshold. Range: 1 to 20.
            2:1 = gentle, 4:1 = moderate, 8:1 = aggressive.
        attack_ms: How fast compression kicks in after exceeding threshold. Range: 0.1 to 200 ms.
            Faster (lower) = more aggressive peak control, can sound unnatural.
            Slower (higher) = more natural, lets transients through.
        release_ms: How fast compression releases after dropping below threshold. Range: 1 to 1000 ms.
            Faster = punchier, can sound pumping. Slower = smoother, more natural.
        makeup_db: Gain added after compression to restore perceived loudness. Range: -24 to 24 dB.
    """
    def __init__(self, threshold_db=-20.0, ratio=4.0, attack_ms=5.0,
                 release_ms=50.0, makeup_db=0.0):
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.makeup_db = makeup_db

    def apply_to_numpy(self, samples, sample_rate):
        board = Pedalboard([
            pedalboard.Compressor(
                threshold_db=self.threshold_db,
                ratio=self.ratio,
                attack_ms=self.attack_ms,
                release_ms=self.release_ms
            ),
            pedalboard.Gain(gain_db=self.makeup_db),
        ])
        return board(samples, sample_rate)

    def __repr__(self):
        return (f"PB_Compressor(threshold_db={self.threshold_db}, ratio={self.ratio}:1, "
                f"attack_ms={self.attack_ms}, release_ms={self.release_ms}, makeup_db={self.makeup_db})")

class PB_NoiseGate(AudioEffect):
    def __init__(self, threshold_db=-40.0):
        self.effect = pedalboard.NoiseGate(threshold_db=threshold_db)

    def apply_to_numpy(self, samples, sample_rate):
        return self.effect(samples, sample_rate)

class PB_Normalizer(AudioEffect):
    def __init__(self, target_db=-1.0):
        self.target = target_db

    def apply_to_numpy(self, samples, sample_rate):
        current_peak = np.max(np.abs(samples))
        if current_peak == 0: return samples

        target_linear = 10 ** (self.target / 20.0)
        gain_amount = target_linear / current_peak
        gain_db = 20 * np.log10(gain_amount)
        effect = pedalboard.Gain(gain_db=gain_db)
        return effect(samples, sample_rate)

class PB_VoiceEnhancer(AudioEffect):
    """Chain for voice clarity"""
    def __init__(self):
        self.board = Pedalboard([
            pedalboard.HighpassFilter(cutoff_frequency_hz=80),
            pedalboard.NoiseGate(threshold_db=-35),
            pedalboard.Compressor(threshold_db=-18, ratio=3),
            pedalboard.Gain(gain_db=2),
            pedalboard.Limiter(threshold_db=-1)
        ])

    def apply_to_numpy(self, samples, sample_rate):
        return self.board(samples, sample_rate)

# Keep names compatible for existing code
Compressor = PB_Compressor
NoiseGate = PB_NoiseGate
Normalizer = PB_Normalizer
VoiceEnhancer = PB_VoiceEnhancer

class TrimSilence(AudioEffect):
    """Removes silence from the beginning of the audio (uses pydub)"""
    def __init__(self, threshold_db=-50.0, chunk_size=10):
        self.threshold = threshold_db
        self.chunk_size = chunk_size

    def apply_to_segment(self, segment):
        from pydub.silence import detect_leading_silence
        trim_ms = detect_leading_silence(segment, silence_threshold=self.threshold, chunk_size=self.chunk_size)
        return segment[trim_ms:], trim_ms

class RoomToneRemover(AudioEffect):
    """Remove room tone/background noise"""
    def __init__(self, sensitivity=0.5):
        self.sensitivity = sensitivity

    def apply_to_numpy(self, samples, sample_rate):
        gate = pedalboard.NoiseGate(threshold_db=-40 + (self.sensitivity * 20))
        return gate(samples, sample_rate)

class DeEsser(AudioEffect):
    """Reduce harsh sibilant sounds"""
    def __init__(self, threshold_db=-20.0):
        self.threshold_db = threshold_db

    def apply_to_numpy(self, samples, sample_rate):
        board = Pedalboard([
            pedalboard.HighpassFilter(cutoff_frequency_hz=5000),
            pedalboard.Compressor(threshold_db=self.threshold_db, ratio=8.0),
            pedalboard.LowpassFilter(cutoff_frequency_hz=8000)
        ])
        return board(samples, sample_rate)

class Equalizer(AudioEffect):
    """5-band parametric equalizer for voice.

    Each band is a PeakFilter at a specific frequency. Bands (Hz):
      Band 1: 100 Hz  — rumble, voice body, warmth
      Band 2: 300 Hz  — low-mids, warmth vs honkiness
      Band 3: 1000 Hz — clarity and presence
      Band 4: 3000 Hz — articulation, "punch"
      Band 5: 8000 Hz — air, sibilance, brightness

    Args:
        bands: List of (frequency_hz, gain_db) tuples. Use (freq, 0) to skip a band.
               Pass None to use flat defaults (all 0 dB).
    """
    BAND_FREQUENCIES = [100, 300, 1000, 3000, 8000]
    BAND_LABELS = [
        "100 Hz (bass/rumble)",
        "300 Hz (warmth/honkiness)",
        "1000 Hz (clarity/presence)",
        "3000 Hz (articulation/punch)",
        "8000 Hz (air/sibilance)"
    ]

    def __init__(self, bands=None):
        if bands is None:
            bands = [(f, 0) for f in self.BAND_FREQUENCIES]
        self.bands = bands

    def apply_to_numpy(self, samples, sample_rate):
        effects = []
        for freq, gain in self.bands:
            if gain != 0:
                effects.append(pedalboard.PeakFilter(
                    cutoff_frequency_hz=freq,
                    gain_db=gain,
                    q=1.0
                ))

        if effects:
            board = Pedalboard(effects)
            return board(samples, sample_rate)
        return samples

    def get_band_gains(self):
        """Return a dict of {label: gain_db} for each band."""
        return dict(zip(self.BAND_LABELS, [g for _, g in self.bands]))

    def __repr__(self):
        return f"Equalizer(bands={self.bands})"
