"""
Auto Ducker Module for SpeechCraft
Automatically ducks background audio when voice is present.

Uses RMS-based voice activity detection to build a ducking envelope,
then applies gain reduction to the background track in 10ms chunks.
"""

import numpy as np
from pydub import AudioSegment


class AutoDucker:
    """Automatic audio ducking for voice-over work.
    
    Takes a voice track and a background track (e.g. music).
    Analyses the voice track for activity above a threshold,
    then applies gain reduction to the background wherever voice is detected.
    
    Args:
        threshold_db:  RMS level in dB above which voice is considered "active".
                        Default -30dB. Silence is around -60 to -50dB.
        reduction_db:   How much to reduce the background by when voice is active.
                        Default -12dB (halves the perceived loudness).
        chunk_ms:       Processing chunk size in milliseconds.
                        Smaller = more precise but slower.
    """
    
    def __init__(
        self,
        threshold_db: float = -30.0,
        reduction_db: float = -12.0,
        attack_ms: int = 10,
        release_ms: int = 100,
        chunk_ms: int = 10
    ):
        if threshold_db >= 0:
            raise ValueError("threshold_db must be negative (it's a reduction from full scale)")
        if reduction_db >= 0:
            raise ValueError("reduction_db must be negative")
        if chunk_ms <= 0:
            raise ValueError("chunk_ms must be positive")
        
        self.threshold_db = threshold_db
        # Convert dB threshold to linear — compare linear values, not dB
        self.threshold_linear = 10 ** (threshold_db / 20.0)
        self.reduction_db = reduction_db
        # Attack and release are available for future envelope shaping
        # (current implementation uses instant on/off at chunk boundaries)
        self.attack_ms = max(1, attack_ms)
        self.release_ms = max(1, release_ms)
        self.chunk_ms = chunk_ms
    
    def duck_audio(self, voice_track, background_track) -> AudioSegment:
        """Duck background audio when voice is present.
        
        Args:
            voice_track:     AudioSegment of the voice recording.
            background_track: AudioSegment of the background audio to be ducked.
        
        Returns:
            A new AudioSegment with ducking applied to the background.
            Returns the original background_track unaltered if either
            input is empty or None.
        """
        if not voice_track or not background_track:
            return background_track
        
        # Build voice activity array — same length as voice track
        voice_activity = self._detect_voice_activity(voice_track)
        
        # Apply ducking to background
        return self._apply_ducking(background_track, voice_activity)
    
    def _detect_voice_activity(self, voice_track) -> list:
        """Return a list of booleans: True where voice is active above threshold.
        
        Walks the voice track in chunk-sized steps, computes RMS per chunk,
        and returns True when RMS exceeds the linear threshold.
        """
        samples = np.array(voice_track.get_array_of_samples(), dtype=np.float64)
        
        # Average stereo to mono if needed
        if voice_track.channels > 1:
            samples = samples.reshape((-1, voice_track.channels)).mean(axis=1)
        
        # Normalise int16 samples to [-1.0, 1.0] range
        samples = samples / 32768.0
        
        chunk_samples = int(voice_track.frame_rate * self.chunk_ms / 1000)
        activity = []
        
        for i in range(0, len(samples), chunk_samples):
            chunk = samples[i:i + chunk_samples]
            if chunk.size == 0:
                activity.append(False)
                continue
            
            # RMS in linear space — compare directly to linear threshold
            rms = np.sqrt(np.mean(chunk ** 2))
            activity.append(rms > self.threshold_linear)
        
        return activity
    
    def _apply_ducking(self, background_track, voice_activity) -> AudioSegment:
        """Apply gain reduction to background wherever voice is active.
        
        Iterates over the voice_activity array (indexed from start of voice track)
        and applies reduction_db to the corresponding region of the background.
        """
        chunk_samples = int(background_track.frame_rate * self.chunk_ms / 1000)
        ducked_segments = []
        
        for i, is_active in enumerate(voice_activity):
            start_ms = i * self.chunk_ms
            end_ms = start_ms + self.chunk_ms
            
            segment = background_track[start_ms:end_ms]
            
            if is_active:
                # pydub supports scalar addition: +N dB raises level, -N dB lowers it
                segment = segment + self.reduction_db
            
            ducked_segments.append(segment)
        
        if not ducked_segments:
            return background_track
        
        # Concatenate all chunks — O(n) using reduce, much faster than sum()
        from functools import reduce
        return reduce(lambda a, b: a + b, ducked_segments)