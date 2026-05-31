"""
Real-time Studio Recording System for SpeechCraft
Provides live transcription, automatic line placement, and redo functionality.

Scenario 1: One person — voice actor + director on same machine
Scenario 2: Two people — director's monitor (audio_editor.py) + voice actor's monitor (voice_actor_client.py)
           Voice actor's monitor connects via TCP socket to localhost:8765

Uses Faster Whisper (local, offline) for SA-accent-aware transcription.
"""

import threading
import time
import queue
import numpy as np
import sounddevice as sd
from pydub import AudioSegment
import tempfile
import os
import socket
import json

# Faster Whisper — downloaded once, cached locally
from faster_whisper import WhisperModel


class StudioRecorder:
    """Real-time recording with live transcription and line placement.
    
    Args:
        script_lines: List of ScriptLine objects with .description, .time_in_ms, .time_out_ms, .line_number
        redo_trigger: Word that triggers a redo (default: "oops")
        progress_callback: Function called on transcription progress
        whisper_model: "tiny", "base", "small" (default: "small" — best for SA accents)
        device: "cpu" or "cuda" (auto-detected)
    """
    
    def __init__(
        self,
        script_lines=None,
        redo_trigger="oops",
        progress_callback=None,
        whisper_model="small",
        device=None
    ):
        self.script_lines = script_lines or []
        self.redo_trigger = redo_trigger.lower()
        self.progress_callback = progress_callback
        
        # Recording state
        self.recording = False
        self.current_line_index = 0
        self.audio_queue = queue.Queue()
        self.transcription_queue = queue.Queue()
        
        # Audio settings
        self.sample_rate = 16000  # Whisper expects 16kHz
        self.channels = 1
        self.chunk_duration = 1.0  # 1-second chunks for responsive VAD
        
        # Recorded segments
        self.completed_segments = []
        self.current_segment_audio = []  # float32 samples, mono
        self.current_segment_start_time = None
        
        # Whisper model — loaded lazily on first use
        self._whisper_model = None
        self._whisper_model_size = whisper_model
        self._whisper_device = device  # None = auto
        
        # Threading
        self.audio_thread = None
        self.transcription_thread = None
        
        # Socket server for director/voice actor monitors
        self._socket_server = None
        self._socket_thread = None
        self._client_sockets = []
        
        # Redo flag — set by trigger_redo(), checked by transcription worker
        self._redo_pending = threading.Event()
        
    @property
    def whisper_model(self):
        """Lazy-load Whisper model on first transcription."""
        if self._whisper_model is None:
            device = self._whisper_device or ("cuda" if self._has_cuda() else "cpu")
            print(f"Loading Faster Whisper '{self._whisper_model_size}' on {device}...")
            self._whisper_model = WhisperModel(
                self._whisper_model_size,
                device=device,
                compute_type="int8"  # Fast, good accuracy, low CPU
            )
            print("Whisper model loaded.")
        return self._whisper_model
    
    def _has_cuda(self):
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
        
    def start_studio_session(self, input_device_id=None):
        """Start the studio recording session."""
        if self.recording or not self.script_lines:
            return False
            
        self.recording = True
        self.current_line_index = 0
        self.completed_segments = []
        self._redo_pending.clear()
        
        # Start socket server for director/voice actor monitors
        self._start_socket_server()
        
        # Start audio processing thread
        self.audio_thread = threading.Thread(
            target=self._audio_worker,
            args=(input_device_id,),
            daemon=True
        )
        self.audio_thread.start()
        
        # Start transcription thread
        self.transcription_thread = threading.Thread(
            target=self._transcription_worker,
            daemon=True
        )
        self.transcription_thread.start()
        
        self._broadcast({
            'status': 'Recording',
            'current_line': self._current_line_dict(),
            'progress': self.get_progress()
        })
        
        return True
    
    def stop_studio_session(self):
        """Stop the studio recording session."""
        self.recording = False
        
        # Flush remaining audio from queue before stopping threads
        self._flush_audio_queue()
        
        # Wait for threads to finish
        if self.audio_thread:
            self.audio_thread.join(timeout=2.0)
        if self.transcription_thread:
            self.transcription_thread.join(timeout=2.0)
            
        # Stop socket server
        self._stop_socket_server()
        
        return self.get_final_audio()
    
    def trigger_redo(self):
        """Manually trigger a redo of the current line.
        
        Called by:
          - Director pressing REDO in audio_editor.py
          - Voice actor pressing REDO in voice_actor_client.py (via socket)
        """
        if self.recording:
            print(f"Redo triggered for line {self.current_line_index + 1}")
            self._redo_pending.set()
            self._reset_current_segment()
            
            if self.progress_callback:
                self.progress_callback(
                    self.get_progress(),
                    "REDO",
                    self.get_current_line()
                )
            
            self._broadcast({
                'status': 'REDO',
                'current_line': self._current_line_dict(),
                'progress': self.get_progress()
            })
    
    def get_current_line(self):
        """Get the current script line being recorded."""
        if self.current_line_index < len(self.script_lines):
            return self.script_lines[self.current_line_index]
        return None
    
    def get_progress(self):
        """Get recording progress."""
        total_lines = len(self.script_lines)
        completed = len(self.completed_segments)
        current = self.current_line_index
        
        return {
            'total_lines': total_lines,
            'completed_lines': completed,
            'current_line': current + 1,
            'progress_percent': (completed / total_lines * 100) if total_lines > 0 else 0
        }
    
    # ── Audio worker ──────────────────────────────────────────────────────────
    
    def _audio_worker(self, input_device_id):
        """Worker thread for audio recording and VAD-based chunking."""
        try:
            # Resample to 16kHz for Whisper
            chunk_size = int(self.sample_rate * 0.5)  # 500ms chunks for VAD
            
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                device=input_device_id,
                blocksize=chunk_size,
                callback=self._audio_callback
            ):
                while self.recording:
                    time.sleep(0.05)
                    
                    # Process when we have enough audio
                    if len(self.current_segment_audio) >= self.sample_rate * self.chunk_duration:
                        self._process_audio_chunk()
                        
        except Exception as e:
            print(f"Audio recording error: {e}")
    
    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for audio input. Accumulates samples into current segment."""
        if self.recording:
            if self.current_segment_start_time is None:
                self.current_segment_start_time = time_info.current_time
            self.current_segment_audio.extend(indata.flatten().tolist())
    
    def _process_audio_chunk(self):
        """Grab audio from current segment, queue for transcription, reset buffer.
        
        Fix: we now RESET the segment buffer after queuing, preventing duplicate
        processing that existed in the original implementation.
        """
        if not self.current_segment_audio:
            return
        
        # Take a copy for processing (don't hold the lock on the live buffer)
        audio_samples = self.current_segment_audio[:]
        start_time = self.current_segment_start_time
        line_index = self.current_line_index
        
        # Reset BEFORE queuing (prevents the original duplicate-processing bug)
        self._reset_current_segment()
        
        # Convert to 16-bit PCM for Faster Whisper
        audio_array = np.array(audio_samples, dtype=np.float32)
        audio_int16 = (audio_array * 32767).astype(np.int16)
        
        segment = AudioSegment(
            audio_int16.tobytes(),
            frame_rate=self.sample_rate,
            sample_width=2,
            channels=self.channels
        )
        
        self.audio_queue.put({
            'audio': segment,
            'start_time': start_time,
            'line_index': line_index,
            'sample_count': len(audio_samples)
        })
    
    def _flush_audio_queue(self):
        """On session stop, transcribe any remaining audio in the queue."""
        try:
            while True:
                chunk_data = self.audio_queue.get_nowait()
                self._transcribe_chunk(chunk_data)
        except queue.Empty:
            pass
    
    # ── Transcription worker ──────────────────────────────────────────────────
    
    def _transcription_worker(self):
        """Worker thread for Faster Whisper transcription."""
        while self.recording or not self.audio_queue.empty():
            try:
                chunk_data = self.audio_queue.get(timeout=0.5)
                self._transcribe_chunk(chunk_data)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Transcription worker error: {e}")
    
    def _transcribe_chunk(self, chunk_data):
        """Transcribe a single audio chunk using Faster Whisper."""
        # Check for redo first
        if self._redo_pending.is_set():
            self._redo_pending.clear()
            return
        
        # Save to temp file for Whisper
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            try:
                chunk_data['audio'].export(temp_file.name, format='wav')
                
                # Run Faster Whisper
                # beam_size=5 gives better accuracy at modest speed cost
                segments, info = self.whisper_model.transcribe(
                    temp_file.name,
                    beam_size=5,
                    language="en",
                    vad_filter=True,  # Voice activity detection — skips silence
                    vad_parameters=dict(min_silence_duration_ms=300)
                )
                
                # Collect transcribed text
                transcribed_text = " ".join(seg.text for seg in segments).strip()
                
                if not transcribed_text:
                    # VAD filtered out silence — nothing to process
                    return
                
                # Check redo trigger
                if self.redo_trigger in transcribed_text.lower():
                    self._redo_pending.set()
                    self._handle_redo()
                    return
                
                # Process transcription result
                self._process_transcription(transcribed_text.lower(), chunk_data)
                
            finally:
                os.unlink(temp_file.name)
    
    def _process_transcription(self, text, chunk_data):
        """Process transcribed text and handle line completion."""
        current_line = self.get_current_line()
        if not current_line:
            return
        
        script_text = current_line.description.lower()
        similarity = self._calculate_similarity(text, script_text)
        
        # Broadcast current transcription to monitors
        self._broadcast({
            'status': 'transcribing',
            'transcription': text,
            'similarity': round(similarity, 2),
            'current_line': self._current_line_dict(),
            'progress': self.get_progress()
        })
        
        # If similarity is high enough, consider line complete
        if similarity > 0.65:  # 65% similarity threshold
            self._complete_current_line()
        
        # Update progress callback
        if self.progress_callback:
            self.progress_callback(self.get_progress(), text, current_line)
    
    def _calculate_similarity(self, text1, text2):
        """Calculate similarity between two texts."""
        from difflib import SequenceMatcher
        return SequenceMatcher(None, text1, text2).ratio()
    
    def _complete_current_line(self):
        """Mark current line as complete and move to next."""
        current_line = self.get_current_line()
        if not current_line:
            return
        
        # Save completed segment
        if self.current_segment_audio:
            audio_array = np.array(self.current_segment_audio, dtype=np.float32)
            audio_int16 = (audio_array * 32767).astype(np.int16)
            
            segment = AudioSegment(
                audio_int16.tobytes(),
                frame_rate=self.sample_rate,
                sample_width=2,
                channels=self.channels
            )
            
            self.completed_segments.append({
                'line_index': self.current_line_index,
                'script_line': current_line,
                'audio': segment,
                'start_time': self.current_segment_start_time
            })
        
        # Move to next line
        self.current_line_index += 1
        self._reset_current_segment()
        
        # Check if session is complete
        if self.current_line_index >= len(self.script_lines):
            self.recording = False
        
        self._broadcast({
            'status': 'line_complete' if self.recording else 'session_complete',
            'current_line': self._current_line_dict(),
            'progress': self.get_progress()
        })
    
    def _handle_redo(self):
        """Handle redo request."""
        self._reset_current_segment()
        
        if self.progress_callback:
            self.progress_callback(self.get_progress(), "REDO", self.get_current_line())
    
    def _reset_current_segment(self):
        """Reset current recording segment."""
        self.current_segment_audio = []
        self.current_segment_start_time = None
    
    def get_progressive_audio(self):
        """Get audio assembled from all completed lines placed at their time positions.

        Called after each line completes so the director can hear the recording
        building up in real time — lines 1 through N placed in the correct
        timeline positions, with silence where lines N+1 onwards will go.
        """
        if not self.completed_segments:
            return None

        total_duration_ms = max(
            seg['script_line'].time_out_ms for seg in self.completed_segments
        )
        output_audio = AudioSegment.silent(duration=total_duration_ms)

        for segment in self.completed_segments:
            script_line = segment['script_line']
            audio = segment['audio']

            start_ms = script_line.time_in_ms
            end_ms = script_line.time_out_ms

            available_ms = end_ms - start_ms
            if len(audio) > available_ms:
                audio = audio[:available_ms]

            output_audio = output_audio.overlay(audio, position=start_ms)

        return output_audio

    def get_final_audio(self):
        """Get the final compiled audio with proper timing.

        Alias for get_progressive_audio() — the final audio is simply the
        progressive audio once all lines have been recorded.
        """
        return self.get_progressive_audio()
    
    def get_session_report(self):
        """Get a report of the recording session."""
        total_lines = len(self.script_lines)
        completed = len(self.completed_segments)
        
        report = f"Studio Recording Session Report\n"
        report += f"Model: Faster Whisper ({self._whisper_model_size})\n"
        report += f"Total Lines: {total_lines}\n"
        report += f"Completed Lines: {completed}\n"
        report += f"Success Rate: {(completed/total_lines*100):.1f}%\n\n"
        
        report += "Completed Lines:\n"
        for i, segment in enumerate(self.completed_segments):
            line = segment['script_line']
            report += f"  Line {line.line_number}: {line.description[:50]}...\n"
            
        return report
    
    # ── Socket server (director + voice actor monitors) ──────────────────────
    
    def _start_socket_server(self, port=8765):
        """Start TCP socket server for director/voice actor monitor connections."""
        self._socket_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket_server.bind(('0.0.0.0', port))
        self._socket_server.listen(5)
        self._socket_server.settimeout(0.5)  # Poll every 0.5s for clean shutdown
        
        self._client_sockets = []
        self._running = True
        
        self._socket_thread = threading.Thread(target=self._socket_worker, daemon=True)
        self._socket_thread.start()
    
    def _socket_worker(self):
        """Accept client connections and broadcast updates."""
        while self._running:
            try:
                client, addr = self._socket_server.accept()
                self._client_sockets.append(client)
                print(f"Monitor connected: {addr}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Socket server error: {e}")
                break
        
        # Clean up disconnected clients
        self._client_sockets = [
            c for c in self._client_sockets if c.fileno() != -1
        ]
    
    def _broadcast(self, data):
        """Broadcast JSON update to all connected monitors."""
        if not self._client_sockets:
            return
        
        message = json.dumps(data) + '\n'
        dead = []
        
        for client in self._client_sockets:
            try:
                client.sendall(message.encode('utf-8'))
            except Exception:
                dead.append(client)
        
        # Remove dead clients
        for client in dead:
            try:
                client.close()
            except Exception:
                pass
            self._client_sockets.remove(client)
    
    def _stop_socket_server(self):
        """Stop the socket server."""
        self._running = False
        if self._socket_server:
            try:
                self._socket_server.close()
            except Exception:
                pass
        self._client_sockets = []
    
    def _current_line_dict(self):
        """Return current line as a dict for JSON broadcast."""
        line = self.get_current_line()
        if not line:
            return None
        return {
            'line_number': line.line_number,
            'description': line.description,
            'time_in_ms': line.time_in_ms,
            'time_out_ms': line.time_out_ms
        }
    
    # ── Remote redo (called by director via socket) ──────────────────────────
    
    def remote_redo(self):
        """Handle a redo request from the director's monitor."""
        self.trigger_redo()


# ── Script line helper ──────────────────────────────────────────────────────

class ScriptLine:
    """Represents a single line in a recording script."""
    
    def __init__(self, line_number, description, time_in_ms=0, time_out_ms=5000):
        self.line_number = line_number
        self.description = description
        self.time_in_ms = time_in_ms
        self.time_out_ms = time_out_ms
    
    def __repr__(self):
        return f"ScriptLine({self.line_number}: {self.description[:30]})"