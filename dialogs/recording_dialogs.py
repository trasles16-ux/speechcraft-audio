"""Recording dialogs extracted from audio_editor.py.

Pattern: PR #4 of the audio_editor.py decomposition plan. These two
``wx.Dialog`` subclasses were the second extraction target because
they have zero coupling to ``SpeechCraftFrame`` -- they only take
initial data via constructor arguments (``script_lines``,
``input_device_id``) and use lazy imports of local helper modules
(``braille_support``, ``network_monitor``, ``studio_recorder``).

Why a separate file from ``effects_dialogs.py``?
-----------------------------------------------
The decomposition puts dialogs that share concerns together.
``effects_dialogs.py`` is for the effects / preset / batch family;
this file is for the recording family. As the plan progresses,
each concern family grows its own dialogs file rather than
ballooning ``effects_dialogs.py``.

The dialogs in this file
------------------------
``RecordingDialog`` -- simple input-level monitor with a gauge and a
start-recording button. No state coupling beyond ``monitor_stream``
which is owned by the dialog itself.

``StudioRecordingDialog`` -- the full director console for in-studio
recording with optional second monitor for the voice actor and
optional network monitor for remote recording. Uses lazy imports
of ``braille_support``, ``network_monitor``, and ``studio_recorder``
so a missing module degrades gracefully.

Both dialogs are pure UI: no callback back to ``SpeechCraftFrame``
beyond what the dialog returns through ``ShowModal()``.
"""

import wx


class RecordingDialog(wx.Dialog):
    """Dialog for recording with level monitoring"""
    
    def __init__(self, parent, input_device_id=None):
        super().__init__(parent, title="Recording Setup", size=(400, 300))
        
        self.input_device_id = input_device_id
        self.monitoring = False
        self.monitor_stream = None
        
        self.init_ui()
        
    def init_ui(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        title = wx.StaticText(self, label="Recording Level Monitor")
        title_font = title.GetFont()
        title_font.SetPointSize(12)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Level monitor
        level_box = wx.StaticBox(self, label="Input Level")
        level_sizer = wx.StaticBoxSizer(level_box, wx.VERTICAL)
        
        self.level_gauge = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL, size=(-1, 25))
        level_sizer.Add(self.level_gauge, 0, wx.EXPAND | wx.ALL, 5)
        
        self.level_text = wx.StaticText(self, label="Level: -∞ dB")
        level_sizer.Add(self.level_text, 0, wx.ALL, 5)
        
        self.monitor_btn = wx.Button(self, label="Start Level Monitor")
        self.monitor_btn.Bind(wx.EVT_BUTTON, self.toggle_monitor)
        level_sizer.Add(self.monitor_btn, 0, wx.ALL, 5)
        
        vbox.Add(level_sizer, 1, wx.EXPAND | wx.ALL, 10)
        
        # Instructions
        instructions = wx.StaticText(self, label="Monitor your levels before recording.\nAim for -12dB to -6dB for optimal quality.")
        vbox.Add(instructions, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(self, wx.ID_OK, label="Start Recording")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        vbox.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(vbox)
        
        # Auto-start monitoring if device available
        if self.input_device_id is not None:
            wx.CallAfter(self.toggle_monitor, None)
            
    def toggle_monitor(self, event):
        if not self.monitoring:
            try:
                def audio_callback(indata, frames, time, status):
                    rms = np.sqrt(np.mean(indata**2))
                    db_level = 20 * np.log10(max(rms, 1e-10))
                    level_percent = max(0, min(100, (db_level + 60) / 60 * 100))
                    wx.CallAfter(self.update_level, level_percent, db_level)
                
                self.monitor_stream = sd.InputStream(
                    device=self.input_device_id,
                    channels=1,
                    samplerate=44100,
                    callback=audio_callback,
                    blocksize=1024
                )
                self.monitor_stream.start()
                
                self.monitoring = True
                self.monitor_btn.SetLabel("Stop Monitor")
                
            except Exception as e:
                wx.MessageBox(f"Failed to start monitoring: {e}", "Error", wx.ICON_ERROR)
        else:
            if self.monitor_stream:
                self.monitor_stream.stop()
                self.monitor_stream.close()
                self.monitor_stream = None
                
            self.monitoring = False
            self.monitor_btn.SetLabel("Start Level Monitor")
            self.level_gauge.SetValue(0)
            self.level_text.SetLabel("Level: -∞ dB")
            
    def update_level(self, level_percent, db_level):
        self.level_gauge.SetValue(int(level_percent))
        
        # Color coding
        if level_percent > 85:
            self.level_gauge.SetForegroundColour(wx.Colour(255, 0, 0))
        elif level_percent > 70:
            self.level_gauge.SetForegroundColour(wx.Colour(255, 255, 0))
        else:
            self.level_gauge.SetForegroundColour(wx.Colour(0, 255, 0))
            
        self.level_text.SetLabel(f"Level: {db_level:.1f} dB")
        
    def Destroy(self):
        if self.monitor_stream:
            self.monitor_stream.stop()
            self.monitor_stream.close()
        super().Destroy()

class StudioRecordingDialog(wx.Dialog):
    """Main director dialog for studio recording with full controls"""
    
    def __init__(self, parent, script_lines, input_device_id=None, use_second_monitor=False, use_network_monitor=False):
        super().__init__(parent, title="Studio Recording - Director Control", size=(700, 600))
        
        self.script_lines = script_lines
        self.input_device_id = input_device_id
        self.studio_recorder = None
        self.recording = False
        self.use_second_monitor = use_second_monitor
        self.use_network_monitor = use_network_monitor
        self.voice_actor_monitor = None
        self.network_server = None
        
        self.init_ui()
        
        # Create voice actor monitor if requested
        if self.use_second_monitor:
            self.create_voice_actor_monitor()
            
        # Start network server if requested
        if self.use_network_monitor:
            self.start_network_server()
            
        # Initialize braille display
        try:
            import braille_support
            self.braille = braille_support.get_braille_display()
            if self.braille.is_connected():
                self.braille.send_status("Studio ready")
        except ImportError:
            self.braille = None
        
    def create_voice_actor_monitor(self):
        """Create a simplified monitor window for voice actor in studio"""
        self.voice_actor_monitor = wx.Frame(None, title="Voice Actor Monitor", size=(500, 400))
        
        panel = wx.Panel(self.voice_actor_monitor)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Large, clear title
        title = wx.StaticText(panel, label="Voice Actor Monitor")
        title_font = title.GetFont()
        title_font.SetPointSize(18)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 15)
        
        # Current line display (large text for studio visibility)
        line_box = wx.StaticBox(panel, label="Current Line to Record")
        line_sizer = wx.StaticBoxSizer(line_box, wx.VERTICAL)
        
        self.actor_current_line = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 150))
        line_font = self.actor_current_line.GetFont()
        line_font.SetPointSize(14)
        line_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.actor_current_line.SetFont(line_font)
        line_sizer.Add(self.actor_current_line, 1, wx.EXPAND | wx.ALL, 5)
        
        vbox.Add(line_sizer, 1, wx.EXPAND | wx.ALL, 10)
        
        # Progress display (simple and clear)
        progress_box = wx.StaticBox(panel, label="Session Progress")
        progress_sizer = wx.StaticBoxSizer(progress_box, wx.VERTICAL)
        
        self.actor_progress_gauge = wx.Gauge(panel, range=100, size=(-1, 40))
        progress_sizer.Add(self.actor_progress_gauge, 0, wx.EXPAND | wx.ALL, 5)
        
        self.actor_progress_text = wx.StaticText(panel, label="Ready to start...")
        progress_text_font = self.actor_progress_text.GetFont()
        progress_text_font.SetPointSize(12)
        self.actor_progress_text.SetFont(progress_text_font)
        progress_sizer.Add(self.actor_progress_text, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        vbox.Add(progress_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Status display
        self.actor_status = wx.StaticText(panel, label="Waiting for director...")
        status_font = self.actor_status.GetFont()
        status_font.SetPointSize(14)
        status_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.actor_status.SetFont(status_font)
        vbox.Add(self.actor_status, 0, wx.ALL | wx.ALIGN_CENTER, 15)
        
        panel.SetSizer(vbox)
        
        # Position on second display if available
        displays = wx.Display.GetCount()
        if displays > 1:
            display = wx.Display(1)
            geometry = display.GetGeometry()
            self.voice_actor_monitor.SetPosition((geometry.x + 100, geometry.y + 100))
        else:
            main_pos = self.GetPosition()
            self.voice_actor_monitor.SetPosition((main_pos.x + 50, main_pos.y + 50))
            
        self.voice_actor_monitor.Show()
        
    def start_network_server(self):
        """Start network server for remote voice actor monitor"""
        try:
            import network_monitor
            self.network_server = network_monitor.NetworkMonitorServer()
            server_ip = self.network_server.start_server()
            
            if server_ip:
                # Show connection info to director
                info_msg = (
                    f"Network monitor server started!\n\n"
                    f"Voice actor connection options:\n\n"
                    f"1. Python client: Send voice_actor_client.py\n"
                    f"   Run: python voice_actor_client.py\n\n"
                    f"2. Web browser: Open voice_actor_web.html\n"
                    f"   Or visit: http://{server_ip}:8766\n\n"
                    f"3. Any device: Connect to {server_ip}:8765"
                )
                wx.MessageBox(info_msg, "Network Monitor Ready", wx.ICON_INFORMATION)
            else:
                wx.MessageBox("Failed to start network server.", "Error", wx.ICON_ERROR)
                
        except ImportError:
            wx.MessageBox("Network monitor module not available.", "Error", wx.ICON_ERROR)
        
    def on_volume_change(self, event):
        """Handle volume changes from director"""
        volume = self.volume_slider.GetValue() / 100.0
        if hasattr(self.GetParent(), 'set_monitor_volume'):
            self.GetParent().set_monitor_volume(volume)
            
    def on_director_play(self, event):
        """Director play control"""
        if hasattr(self.GetParent(), 'on_play_pause'):
            self.GetParent().on_play_pause(None)
            
    def on_director_stop(self, event):
        """Director stop control"""
        if hasattr(self.GetParent(), 'on_stop'):
            self.GetParent().on_stop(None)
            
    def update_current_line(self):
        """Update the current line display (not needed for director view)"""
        pass
        
    def init_ui(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        title = wx.StaticText(self, label="Director Control - Studio Recording")
        title_font = title.GetFont()
        title_font.SetPointSize(14)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Audio controls for director
        audio_box = wx.StaticBox(self, label="Audio Controls")
        audio_sizer = wx.StaticBoxSizer(audio_box, wx.HORIZONTAL)
        
        # Volume control
        vol_box = wx.BoxSizer(wx.VERTICAL)
        vol_box.Add(wx.StaticText(self, label="Monitor Volume:"), 0, wx.ALL, 5)
        self.volume_slider = wx.Slider(self, value=80, minValue=0, maxValue=100, style=wx.SL_VERTICAL | wx.SL_LABELS)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.on_volume_change)
        vol_box.Add(self.volume_slider, 1, wx.EXPAND | wx.ALL, 5)
        audio_sizer.Add(vol_box, 0, wx.EXPAND | wx.ALL, 5)
        
        # Playback controls
        playback_box = wx.BoxSizer(wx.VERTICAL)
        self.play_btn = wx.Button(self, label="Play")
        self.stop_btn = wx.Button(self, label="Stop")
        self.play_btn.Bind(wx.EVT_BUTTON, self.on_director_play)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_director_stop)
        playback_box.Add(self.play_btn, 0, wx.EXPAND | wx.ALL, 5)
        playback_box.Add(self.stop_btn, 0, wx.EXPAND | wx.ALL, 5)
        audio_sizer.Add(playback_box, 0, wx.ALL, 5)
        
        vbox.Add(audio_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Redo trigger setting
        redo_box = wx.BoxSizer(wx.HORIZONTAL)
        redo_box.Add(wx.StaticText(self, label="Redo trigger word:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.redo_word = wx.TextCtrl(self, value="oops", size=(100, -1))
        redo_box.Add(self.redo_word, 0, wx.ALL, 5)
        vbox.Add(redo_box, 0, wx.ALL, 5)
        
        # Progress display
        progress_box = wx.StaticBox(self, label="Recording Progress")
        progress_sizer = wx.StaticBoxSizer(progress_box, wx.VERTICAL)
        
        self.progress_gauge = wx.Gauge(self, range=100)
        progress_sizer.Add(self.progress_gauge, 0, wx.EXPAND | wx.ALL, 5)
        
        self.progress_text = wx.StaticText(self, label="Ready to start...")
        progress_sizer.Add(self.progress_text, 0, wx.ALL, 5)
        
        vbox.Add(progress_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Live transcription display
        trans_box = wx.StaticBox(self, label="Live Transcription")
        trans_sizer = wx.StaticBoxSizer(trans_box, wx.VERTICAL)
        
        self.transcription_text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
        trans_sizer.Add(self.transcription_text, 1, wx.EXPAND | wx.ALL, 5)
        
        vbox.Add(trans_sizer, 1, wx.EXPAND | wx.ALL, 10)
        
        # Control buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        
        self.start_btn = wx.Button(self, label="Start Recording")
        self.start_btn.Bind(wx.EVT_BUTTON, self.on_start_recording)
        btn_box.Add(self.start_btn, 0, wx.ALL, 5)
        
        self.redo_btn = wx.Button(self, label="Signal Redo")
        self.redo_btn.Bind(wx.EVT_BUTTON, self.on_redo_line)
        self.redo_btn.Enable(False)
        btn_box.Add(self.redo_btn, 0, wx.ALL, 5)
        
        self.stop_btn = wx.Button(self, label="Stop & Finish")
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop_recording)
        self.stop_btn.Enable(False)
        btn_box.Add(self.stop_btn, 0, wx.ALL, 5)
        
        btn_box.AddStretchSpacer()
        
        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        btn_box.Add(cancel_btn, 0, wx.ALL, 5)
        
        vbox.Add(btn_box, 0, wx.EXPAND | wx.ALL, 10)
        
        self.SetSizer(vbox)
        
    def on_start_recording(self, event):
        """Start the studio recording session"""
        try:
            import studio_recorder
            
            redo_word = self.redo_word.GetValue().strip().lower()
            self.studio_recorder = studio_recorder.StudioRecorder(
                script_lines=self.script_lines,
                redo_trigger=redo_word,
                progress_callback=self.on_progress_update
            )
            
            if self.studio_recorder.start_studio_session(self.input_device_id):
                self.recording = True
                self.start_btn.Enable(False)
                self.redo_btn.Enable(True)
                self.stop_btn.Enable(True)
                self.redo_word.Enable(False)
                
                self.progress_text.SetLabel("Recording in progress...")
                
                # Send recording start to braille
                try:
                    import braille_support
                    braille_support.send_to_braille("Recording started", "high")
                except ImportError:
                    pass
                
                # Update voice actor monitor
                if self.voice_actor_monitor:
                    self.actor_status.SetLabel("Recording in progress...")
                    
                # Update network clients
                if self.network_server:
                    self.network_server.broadcast_update({
                        'status': 'Recording in progress...',
                        'progress': {'current_line': 1, 'total_lines': len(self.script_lines), 'progress_percent': 0}
                    })
            else:
                wx.MessageBox("Failed to start recording session.", "Error", wx.ICON_ERROR)
                
        except ImportError:
            wx.MessageBox("Studio recording module not available.", "Error", wx.ICON_ERROR)
        except Exception as e:
            wx.MessageBox(f"Error starting recording: {e}", "Error", wx.ICON_ERROR)
            
    def on_stop_recording(self, event):
        """Stop the recording session"""
        if self.studio_recorder and self.recording:
            self.final_audio = self.studio_recorder.stop_studio_session()
            self.session_report = self.studio_recorder.get_session_report()
            
            self.recording = False
            self.start_btn.Enable(True)
            self.redo_btn.Enable(False)
            self.stop_btn.Enable(False)
            self.redo_word.Enable(True)
            
            self.progress_text.SetLabel("Recording completed!")
            
            # Send completion to braille
            try:
                import braille_support
                braille_support.send_to_braille("Recording finished", "high")
            except ImportError:
                pass
            
            # Update voice actor monitor
            if self.voice_actor_monitor:
                self.actor_status.SetLabel("Session completed!")
                
            # Update network clients
            if self.network_server:
                self.network_server.broadcast_update({
                    'status': 'Session completed!',
                    'current_line': None
                })
            
            # Close dialog with OK
            self.EndModal(wx.ID_OK)
            
    def on_redo_line(self, event):
        """Manually trigger redo of current line"""
        if self.studio_recorder and self.recording:
            self.studio_recorder.trigger_redo()
            
    def on_progress_update(self, progress, transcription, current_line):
        """Update UI with recording progress"""
        wx.CallAfter(self._update_ui, progress, transcription, current_line)
        
    def _update_ui(self, progress, transcription, current_line):
        """Update UI elements (called on main thread)"""
        # Update main dialog
        self.progress_gauge.SetValue(int(progress['progress_percent']))
        progress_label = (
            f"Line {progress['current_line']} of {progress['total_lines']} "
            f"({progress['completed_lines']} completed)"
        )
        self.progress_text.SetLabel(progress_label)

        # Update transcription
        if transcription == "REDO":
            trans_text = "REDO TRIGGERED - Restarting current line..."
            self.transcription_text.SetValue(trans_text)
        else:
            current_text = self.transcription_text.GetValue()
            self.transcription_text.SetValue(current_text + "\n" + transcription)

        # Update current line
        self.update_current_line()

        # ── Progressive audio update ────────────────────────────────────────────
        # After each line completes, load the progressive audio into the main
        # editor so the director can hit Play and hear the recording building up
        # in real time — lines 1 through N placed at their correct time
        # positions, with silence where lines N+1 onwards will go.
        if self.studio_recorder and progress['completed_lines'] > 0:
            progressive = self.studio_recorder.get_progressive_audio()
            if progressive is not None:
                editor = self.GetParent()
                if hasattr(editor, 'load_audio_from_segment'):
                    editor.load_audio_from_segment(
                        progressive,
                        name=f"Studio Recording ({progress['completed_lines']} lines)"
                    )
        # ── End progressive audio update ───────────────────────────────────────
        
        # Update voice actor monitor if active
        if self.voice_actor_monitor and self.voice_actor_monitor.IsShown():
            self.actor_progress_gauge.SetValue(int(progress['progress_percent']))
            self.actor_progress_text.SetLabel(progress_label)
            
            if transcription == "REDO":
                self.actor_status.SetLabel("Redo in progress...")
                # Send redo status to braille
                try:
                    import braille_support
                    braille_support.send_to_braille("REDO - Restarting line", "high")
                except ImportError:
                    pass
            else:
                self.actor_status.SetLabel("Recording...")
                
            # Update actor current line and send to braille
            if current_line:
                line_text = f"Line {current_line.line_number}:\n\n"
                line_text += current_line.description
                self.actor_current_line.SetValue(line_text)
                
                # Send current line to braille display
                try:
                    import braille_support
                    braille_support.send_line_to_braille(current_line.line_number, current_line.description)
                except ImportError:
                    pass
            else:
                self.actor_current_line.SetValue("All lines completed!")
                try:
                    import braille_support
                    braille_support.send_to_braille("Session complete!", "high")
                except ImportError:
                    pass
                    
        # Update network clients
        if self.network_server:
            network_data = {
                'progress': progress,
                'transcription': transcription if transcription != "REDO" else "REDO - Restarting line",
                'status': 'REDO in progress...' if transcription == "REDO" else 'Recording...'
            }
            
            if current_line:
                network_data['current_line'] = {
                    'line_number': current_line.line_number,
                    'description': current_line.description,
                    'time_in_ms': current_line.time_in_ms,
                    'time_out_ms': current_line.time_out_ms
                }
                
            self.network_server.broadcast_update(network_data)
        
    def update_current_line(self):
        """Update the current line display"""
        if self.studio_recorder:
            current_line = self.studio_recorder.get_current_line()
        else:
            current_line = self.script_lines[0] if self.script_lines else None
            
        if current_line:
            line_text = f"Line {current_line.line_number}:\n"
            line_text += f"Time: {current_line.time_in_ms//1000}s - {current_line.time_out_ms//1000}s\n\n"
            line_text += current_line.description
            self.current_line_text.SetValue(line_text)
        else:
            self.current_line_text.SetValue("All lines completed!")
            
    def get_final_audio(self):
        """Get the final recorded audio"""
        return getattr(self, 'final_audio', None)
