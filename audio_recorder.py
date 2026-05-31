"""
Audio Recording Module for SpeechCraft
Handles real-time audio recording with progress callbacks.
"""

import threading
import time
import sounddevice as sd
import numpy as np
from pydub import AudioSegment

class AudioRecorder:
    """Real-time audio recorder with progress callbacks"""
    
    def __init__(self, sample_rate=44100, channels=1, progress_callback=None, input_device_id=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.progress_callback = progress_callback
        self.input_device_id = input_device_id
        self.recording = False
        self.audio_data = []
        self.start_time = None
        
    def start(self):
        """Start recording audio"""
        if self.recording:
            return
            
        self.recording = True
        self.audio_data = []
        self.start_time = time.time()
        
        # Start recording thread
        self.record_thread = threading.Thread(target=self._record_worker, daemon=True)
        self.record_thread.start()
        
        # Start progress thread
        self.progress_thread = threading.Thread(target=self._progress_worker, daemon=True)
        self.progress_thread.start()
        
    def stop(self):
        """Stop recording and return AudioSegment"""
        if not self.recording:
            return None
            
        self.recording = False
        
        # Wait for threads to finish
        if hasattr(self, 'record_thread'):
            self.record_thread.join(timeout=1.0)
        if hasattr(self, 'progress_thread'):
            self.progress_thread.join(timeout=1.0)
            
        if not self.audio_data:
            return None
            
        # Convert to AudioSegment
        audio_array = np.concatenate(self.audio_data)
        audio_int16 = (audio_array * 32767).astype(np.int16)
        
        return AudioSegment(
            audio_int16.tobytes(),
            frame_rate=self.sample_rate,
            sample_width=2,
            channels=self.channels
        )
        
    def _record_worker(self):
        """Worker thread for audio recording"""
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                device=self.input_device_id,
                callback=self._audio_callback
            ):
                while self.recording:
                    time.sleep(0.1)
        except Exception as e:
            print(f"Recording error: {e}")
            self.recording = False
            
    def _audio_callback(self, indata, frames, time, status):
        """Callback for audio input"""
        if self.recording:
            self.audio_data.append(indata.copy())
            
    def _progress_worker(self):
        """Worker thread for progress updates"""
        while self.recording:
            if self.start_time and self.progress_callback:
                elapsed = time.time() - self.start_time
                self.progress_callback(elapsed)
            time.sleep(0.1)