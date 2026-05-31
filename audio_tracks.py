"""
Multi-track audio management system for SpeechCraft
Handles multiple audio tracks with independent volume, mute, and solo controls.
Includes a refined Auto-Ducker for Audio Description.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from pydub import AudioSegment
import numpy as np
from enum import Enum

class TrackType(Enum):
    """Types of audio tracks"""
    VOICE = "voice"           # Primary voice/narration track (The "Leader")
    MUSIC = "music"           # Background music
    SOUND_EFFECTS = "effects" # Sound effects
    VIDEO_AUDIO = "video"     # Audio from video/movie
    AMBIENCE = "ambience"     # Ambient background sounds

@dataclass
class AudioTrack:
    """Represents a single audio track"""
    track_id: str
    name: str
    audio_segment: Optional[AudioSegment] = None
    track_type: TrackType = TrackType.VOICE
    volume_db: float = 0.0           # Volume adjustment in dB (-40 to +20)
    muted: bool = False
    solo: bool = False
    pan: float = 0.0                 # -1.0 (left) to 1.0 (right)
    start_offset_ms: int = 0         # When this track starts in timeline (ms)
    visible: bool = True             
    
    def get_display_volume(self) -> float:
        """Get volume as linear ratio"""
        return 10 ** (self.volume_db / 20.0)
    
    def get_duration_ms(self) -> int:
        """Get duration of audio in milliseconds"""
        if self.audio_segment is None:
            return 0
        return len(self.audio_segment)

class TrackManager:
    """Manages multiple audio tracks"""
    
    def __init__(self):
        self.tracks: List[AudioTrack] = []
        self._next_track_id = 1
    
    def add_track(self, name, audio_segment=None, track_type=TrackType.VOICE, start_offset_ms=0):
        """Add a new track to the manager"""
        track_id = f"track_{self._next_track_id}"
        self._next_track_id += 1
        track = AudioTrack(track_id, name, audio_segment, track_type, start_offset_ms=start_offset_ms)
        self.tracks.append(track)
        return track

    def get_track_by_type(self, t_type: TrackType) -> Optional[AudioTrack]:
        """Find the first track of a specific type"""
        for track in self.tracks:
            if track.track_type == t_type:
                return track
        return None

    def apply_auto_ducking(self, reduction_db=-15.0):
        """
        REFINED AUTO-DUCKER:
        Automatically ducks all background tracks whenever the VOICE track is active.
        Useful for Audio Description to ensure the voice-over is always clear.
        """
        voice_track = self.get_track_by_type(TrackType.VOICE)
        if not voice_track or not voice_track.audio_segment:
            return "No voice track found to lead the ducking."

        # Define which tracks are targets for ducking
        targets = [TrackType.MUSIC, TrackType.VIDEO_AUDIO, TrackType.AMBIENCE]
        
        # Calculate the voice interval
        v_start = voice_track.start_offset_ms
        v_end = v_start + len(voice_track.audio_segment)

        for track in self.tracks:
            if track.track_type in targets and track.audio_segment:
                # Split the background track into three parts: Before, During, and After voice
                # This ensures we only lower the volume exactly when you are speaking.
                background = track.audio_segment
                
                # Part 1: Before the description starts
                before = background[:v_start]
                
                # Part 2: During the description (The Ducked Part)
                during = background[v_start:v_end].apply_gain(reduction_db)
                
                # Part 3: After the description ends
                after = background[v_end:]
                
                # Reassemble the track
                track.audio_segment = before + during + after
        
        return f"Successfully ducked background tracks by {reduction_db} dB."

    def get_total_duration_ms(self) -> int:
        """Get longest track duration"""
        if not self.tracks: return 0
        durations = [(t.start_offset_ms + len(t.audio_segment)) for t in self.tracks if t.audio_segment]
        return max(durations) if durations else 0

    def mix_down(self) -> Optional[AudioSegment]:
        """Mix all valid (unmuted, or soloed) tracks into one AudioSegment."""
        if not self.tracks: return None

        # Check for solo
        solo_tracks = [t for t in self.tracks if t.solo]
        active_tracks = solo_tracks if solo_tracks else [t for t in self.tracks if not t.muted]

        if not active_tracks:
            return AudioSegment.silent(duration=1000) # Fallback

        length = self.get_total_duration_ms()
        if length == 0: return AudioSegment.silent(duration=1000)

        # Create base
        mixed = AudioSegment.silent(duration=length)

        for track in active_tracks:
            if not track.audio_segment: continue
            
            # Create a silent container for this track placed at correct offset
            # (Note: pydub overlay handles position, but better to stabilize volume first)
            
            # Apply Volume
            vol_ratio = track.get_display_volume()
            # Pydub uses gain in dB. track.volume_db is already dB.
            seg = track.audio_segment + track.volume_db
            
            # Overlay
            mixed = mixed.overlay(seg, position=track.start_offset_ms)
            
        return mixed