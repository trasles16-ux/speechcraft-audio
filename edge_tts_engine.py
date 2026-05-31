"""
Edge TTS Engine for SpeechCraft Studio
Provides free text-to-speech using Microsoft Edge TTS.
Includes South African voices for Afrikaans, English, and Zulu.
"""

import asyncio
import tempfile
import os
import threading
from typing import Optional, Dict

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

from pydub import AudioSegment
import sys


# Configure FFmpeg for pydub
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

ffmpeg_path = os.path.join(base_path, "ffmpeg.exe")
if os.path.exists(ffmpeg_path):
    AudioSegment.converter = ffmpeg_path
    AudioSegment.ffmpeg = ffmpeg_path
    AudioSegment.ffprobe = ffmpeg_path


class EdgeTTSEngine:
    """Wrapper for Microsoft Edge TTS with South African voice support.
    
    Uses the edge_tts Python async API directly (no subprocess spawning).
    Thread-safe — synthesize() can be called from the wx main thread;
    the async work runs in a background thread.
    """
    
    # South African voices (all 11 official languages where available)
    SA_VOICES = {
        "Afrikaans (Female)": "af-ZA-AdriNeural",
        "Afrikaans (Male)": "af-ZA-WillemNeural",
        "English SA (Female)": "en-ZA-LeahNeural",
        "English SA (Male)": "en-ZA-LukeNeural",
        "Zulu (Female)": "zu-ZA-ThandoNeural",
        "Zulu (Male)": "zu-ZA-ThembaNeural",
    }
    
    OTHER_VOICES = {
        "English US (Female)": "en-US-AriaNeural",
        "English US (Male)": "en-US-GuyNeural",
        "English UK (Female)": "en-GB-SoniaNeural",
        "English UK (Male)": "en-GB-RyanNeural",
    }
    
    def __init__(self):
        if not EDGE_TTS_AVAILABLE:
            raise ImportError(
                "edge-tts library not installed. "
                "Install with: pip install edge-tts"
            )
    
    @staticmethod
    def get_all_voices() -> Dict[str, str]:
        """Get all available voices (SA voices first)."""
        all_voices = {}
        all_voices.update(EdgeTTSEngine.SA_VOICES)
        all_voices.update(EdgeTTSEngine.OTHER_VOICES)
        return all_voices
    
    @staticmethod
    def get_sa_voices() -> Dict[str, str]:
        """Get only South African voices."""
        return EdgeTTSEngine.SA_VOICES.copy()
    
    def synthesize(
        self,
        text: str,
        voice_name: str = "English SA (Female)",
        rate: int = 0,
        pitch: int = 0
    ) -> str:
        """Synthesize text to speech using Edge TTS.
        
        Args:
            text:         Text to synthesize. Must not be empty.
            voice_name:   Voice name from get_all_voices() keys.
                          Defaults to "English SA (Female)".
            rate:         Speech rate adjustment. Range: -100 to +100.
                          0 = normal speed. Negative = slower, positive = faster.
            pitch:        Pitch adjustment in Hz. Range: -100 to +100.
                          0 = normal pitch. Negative = lower, positive = higher.
        
        Returns:
            Path to a generated WAV audio file. Caller is responsible for
            deleting the temp file when done.
        
        Raises:
            ValueError:   If text is empty or rate/pitch are out of range.
            RuntimeError: If synthesis fails.
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        if not (-100 <= rate <= 100):
            raise ValueError(f"rate must be between -100 and +100, got {rate}")
        if not (-100 <= pitch <= 100):
            raise ValueError(f"pitch must be between -100 and +100, got {pitch}")
        
        all_voices = self.get_all_voices()
        voice_id = all_voices.get(voice_name) or all_voices["English SA (Female)"]
        
        # Format rate/pitch for edge_tts: "+0%" → "+0%" (already a string)
        rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
        pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
        
        # Run async synthesis in a background thread
        result_container = [None, None]  # [wav_path, exception]
        
        def async_worker():
            try:
                wav_path = asyncio.run(
                    self._synthesize_async(text, voice_id, rate_str, pitch_str)
                )
                result_container[0] = wav_path
            except Exception as e:
                result_container[1] = e
        
        t = threading.Thread(target=async_worker, daemon=True)
        t.start()
        t.join(timeout=30)  # 30-second timeout
        
        if result_container[1]:
            raise RuntimeError(f"Edge TTS synthesis failed: {result_container[1]}")
        if result_container[0] is None:
            raise RuntimeError("Edge TTS synthesis timed out after 30 seconds")
        
        return result_container[0]
    
    async def _synthesize_async(
        self,
        text: str,
        voice: str,
        rate: str,
        pitch: str
    ) -> str:
        """Async synthesis using the edge_tts Python API directly.
        
        Downloads MP3 from Edge, converts to WAV using pydub,
        returns the WAV path. Cleans up the MP3 temp file.
        """
        temp_mp3 = None
        temp_wav = None
        
        try:
            temp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            mp3_path = temp_mp3.name
            temp_mp3.close()  # Close so edge_tts can write to it
            
            # Synthesize directly to MP3 using the async API
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(mp3_path)
            
            if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
                raise RuntimeError("edge_tts produced an empty MP3 file")
            
            # Convert MP3 to WAV using pydub
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            wav_path = temp_wav.name
            temp_wav.close()
            
            audio = AudioSegment.from_mp3(mp3_path)
            audio.export(wav_path, format="wav")
            
            return wav_path
            
        finally:
            # Always clean up MP3 temp file
            if temp_mp3 and os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except OSError:
                    pass
            # temp_wav is intentionally NOT deleted here — caller takes ownership


# ── Test / CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Edge TTS Engine — SpeechCraft Studio")
    
    if not EDGE_TTS_AVAILABLE:
        print("ERROR: edge-tts not installed")
        print("Install with: pip install edge-tts")
    else:
        engine = EdgeTTSEngine()
        
        print("\nSouth African Voices:")
        for name, voice_id in engine.get_sa_voices().items():
            print(f"  {name}: {voice_id}")
        
        print("\nOther Voices:")
        for name, voice_id in engine.get_all_voices().items():
            if name not in engine.SA_VOICES:
                print(f"  {name}: {voice_id}")
        
        print("\nTesting synthesis with English SA (Female)...")
        try:
            output = engine.synthesize(
                "Hello, this is a test of Edge TTS with a South African voice.",
                "English SA (Female)"
            )
            print(f"Success! Audio saved to: {output}")
            print("Play the file to verify the voice.")
        except Exception as e:
            print(f"Error: {e}")