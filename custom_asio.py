"""
Custom ASIO Driver for SpeechCraft Studio
Bypasses WASAPI shared mode for lower-latency audio via sounddevice + WASAPI exclusive mode.

Note: True ASIO requires a kernel-mode driver signed by Microsoft, which cannot be
implemented from Python alone. This module uses WASAPI exclusive mode via sounddevice
to achieve similar latency characteristics (2-10ms on modern hardware) without
needing a physical ASIO driver.

Active when audio_editor.py has audio_engine = "custom_asio".
Falls back to sounddevice if exclusive mode cannot be acquired.
"""

import ctypes
from ctypes import wintypes
import threading
import numpy as np
import time
import os

try:
    import win32api
    import win32process
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

import sounddevice as sd


# ── Constants ────────────────────────────────────────────────────────────────

ASIO_MIN_BUFFER_SIZE = 32
ASIO_MAX_BUFFER_SIZE = 8192
ASIO_PREFERRED_BUFFER_SIZE = 256


# ── Driver ────────────────────────────────────────────────────────────────────

class CustomASIODriver:
    """Low-latency audio driver using WASAPI exclusive mode.
    
    Wraps sounddevice's WASAPI exclusive-mode stream with ASIO-compatible
    semantics: fixed buffer size, configurable sample rate, and a
    user-supplied audio callback.
    
    Not a true ASIO driver — this cannot replace a hardware ASIO driver.
    But for most USB microphones and onboard audio, WASAPI exclusive mode
    gives comparable latency to ASIO (< 10ms on modern hardware).
    """
    
    def __init__(self):
        self.initialized = False
        self.running = False
        self.sample_rate = 44100
        self.buffer_size = ASIO_PREFERRED_BUFFER_SIZE
        self.input_channels = 2
        self.output_channels = 2
        
        self.audio_callback = None
        self.input_device = None
        self.output_device = None
        
        self._stream = None
        self.audio_thread = None
        self.stop_event = threading.Event()
    
    def initialize(
        self,
        sample_rate: int = 44100,
        buffer_size: int = 256,
        input_device: int = None,
        output_device: int = None
    ) -> bool:
        """Initialize the driver with the given sample rate and buffer size.
        
        Args:
            sample_rate:  Target sample rate in Hz. Common values: 44100, 48000.
            buffer_size:  Number of samples per audio callback. Smaller =
                          lower latency but more CPU overhead.
            input_device: sounddevice device index for input.
            output_device: sounddevice device index for output.
        
        Returns:
            True if initialization succeeded, False otherwise.
        """
        try:
            self.sample_rate = sample_rate
            self.buffer_size = buffer_size
            self.input_device = input_device
            self.output_device = output_device
            
            # Auto-select devices if not specified
            if self.input_device is None or self.output_device is None:
                devices = sd.query_devices()
                if self.input_device is None:
                    for i, dev in enumerate(devices):
                        if dev.get('max_input_channels', 0) > 0:
                            self.input_device = i
                            break
                if self.output_device is None:
                    for i, dev in enumerate(devices):
                        if dev.get('max_output_channels', 0) > 0:
                            self.output_device = i
                            break
            
            if self.input_device is None or self.output_device is None:
                print("Custom ASIO: no audio devices found")
                return False
            
            self.initialized = True
            print(
                f"Custom ASIO driver: {sample_rate}Hz, "
                f"{buffer_size} samples, in={self.input_device}, out={self.output_device}"
            )
            return True
            
        except Exception as e:
            print(f"Custom ASIO driver initialization failed: {e}")
            return False
    
    def start(self, audio_callback) -> bool:
        """Start the audio processing thread.
        
        Args:
            audio_callback: Callable(indata, outdata, frames, time_info, status)
                           matching the sounddevice stream callback signature.
        
        Returns:
            True if the stream started, False otherwise.
        """
        if not self.initialized:
            return False
        
        self.audio_callback = audio_callback
        self.running = True
        self.stop_event.clear()
        
        self.audio_thread = threading.Thread(target=self._audio_worker, daemon=True)
        self.audio_thread.start()
        
        print("Custom ASIO driver started")
        return True
    
    def stop(self):
        """Stop the audio thread and close the stream."""
        self.running = False
        self.stop_event.set()
        
        if self.audio_thread:
            self.audio_thread.join(timeout=2.0)
            self.audio_thread = None
        
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        
        print("Custom ASIO driver stopped")
    
    def _set_realtime_priority(self):
        """Elevate the audio thread to real-time priority on Windows."""
        if not _WIN32_AVAILABLE:
            return
        
        try:
            handle = win32api.GetCurrentThread()
            win32process.SetThreadPriority(
                handle,
                win32process.THREAD_PRIORITY_TIME_CRITICAL
            )
        except Exception:
            pass  # Non-fatal — just run at normal priority
    
    def _audio_worker(self):
        """Run the sounddevice stream on a background thread."""
        self._set_realtime_priority()
        
        try:
            # Try exclusive-mode WASAPI first
            wasapi_settings = sd.WasapiSettings(exclusive=True)
            self._stream = sd.Stream(
                device=(self.input_device, self.output_device),
                samplerate=self.sample_rate,
                blocksize=self.buffer_size,
                channels=(self.input_channels, self.output_channels),
                dtype=np.float32,
                latency='low',
                extra_settings=wasapi_settings,
                callback=self._process_audio
            )
            self._stream.start()
            
            # Block until stopped
            while self.running and not self.stop_event.wait(0.01):
                pass
            
        except OSError:
            # Exclusive mode not available — fall back to shared mode
            print("Custom ASIO: exclusive mode unavailable, falling back to shared mode")
            self._stream = None
            
            try:
                self._stream = sd.Stream(
                    device=(self.input_device, self.output_device),
                    samplerate=self.sample_rate,
                    blocksize=self.buffer_size,
                    channels=(self.input_channels, self.output_channels),
                    dtype=np.float32,
                    latency='low',
                    callback=self._process_audio
                )
                self._stream.start()
                
                while self.running and not self.stop_event.wait(0.01):
                    pass
                    
            except OSError as e:
                print(f"Custom ASIO: shared mode also failed: {e}")
                self.running = False
        
        finally:
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
    
    def _process_audio(self, indata, outdata, frames, time_info, status):
        """Forward audio to the user callback, handle errors gracefully."""
        if status:
            print(f"Custom ASIO audio status: {status}")
        
        try:
            if self.audio_callback:
                processed = self.audio_callback(indata, frames)
                if processed is not None:
                    outdata[:] = processed
                else:
                    outdata.fill(0)
            else:
                outdata.fill(0)
                
        except Exception as e:
            print(f"Custom ASIO processing error: {e}")
            outdata.fill(0)
    
    def get_latency(self) -> float:
        """Return theoretical latency in milliseconds."""
        return (self.buffer_size / self.sample_rate) * 1000
    
    def get_buffer_size(self) -> int:
        return self.buffer_size
    
    def set_buffer_size(self, size: int):
        self.buffer_size = max(ASIO_MIN_BUFFER_SIZE, min(ASIO_MAX_BUFFER_SIZE, size))
    
    def get_sample_rate(self) -> int:
        return self.sample_rate
    
    def set_sample_rate(self, rate: int):
        self.sample_rate = rate


# ── Manager ──────────────────────────────────────────────────────────────────

class ASIOManager:
    """Manages a single CustomASIODriver instance for audio_editor.py."""
    
    def __init__(self):
        self.driver = None
        self.active = False
    
    def initialize_asio(
        self,
        sample_rate: int = 44100,
        buffer_size: int = 256,
        input_device: int = None,
        output_device: int = None
    ) -> bool:
        """Initialize the ASIO driver."""
        try:
            self.driver = CustomASIODriver()
            
            if self.driver.initialize(sample_rate, buffer_size, input_device, output_device):
                self.active = True
                print(f"ASIO manager: {self.driver.get_latency():.1f}ms latency")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"ASIO manager initialization error: {e}")
            return False
    
    def start_audio(self, callback) -> bool:
        if self.driver and self.active:
            return self.driver.start(callback)
        return False
    
    def stop_audio(self):
        if self.driver:
            self.driver.stop()
    
    def get_latency_ms(self) -> float:
        if self.driver:
            return self.driver.get_latency()
        return 0.0
    
    def is_active(self) -> bool:
        return self.active
    
    def cleanup(self):
        if self.driver:
            self.driver.stop()
            self.active = False


# ── Module API ────────────────────────────────────────────────────────────────

_asio_manager = None


def get_asio_manager() -> ASIOManager:
    """Get the global ASIOManager singleton."""
    global _asio_manager
    if _asio_manager is None:
        _asio_manager = ASIOManager()
    return _asio_manager


# ── Test ─────────────────────────────────────────────────────────────────────

def test_asio_latency():
    """Test different buffer sizes and report latency."""
    print("Custom ASIO Driver — Latency Test")
    print("=" * 40)
    
    manager = get_asio_manager()
    
    for buffer_size in [32, 64, 128, 256, 512]:
        if manager.initialize_asio(44100, buffer_size):
            latency = manager.get_latency_ms()
            print(f"Buffer {buffer_size:4d}: {latency:.2f}ms latency")
            manager.cleanup()
        else:
            print(f"Buffer {buffer_size:4d}: initialization failed")


if __name__ == "__main__":
    test_asio_latency()