import wx
import os
import threading
import webbrowser  # Used for Help menu
from pydub import AudioSegment  # pydub is small + cheap, used by setup_ffmpeg
import audio_tracks  # Needed by SpeechCraftFrame (small, fast)
import project_handler  # Used by SpeechCraftFrame (small, fast)
import config  # Built-in presets
import preset_manager  # Custom preset save/load
from dialogs.effects_dialogs import (AudioClipboard, EffectSettingsDialog, BreathSmoothingPresetDialog, CompressorPresetDialog, EQPresetDialog, RoomToneMatchDialog, BatchProcessDialog)
from dialogs.recording_dialogs import (RecordingDialog, StudioRecordingDialog)
from main_frame_tts import TTSMenuMixin

# These are imported lazily inside SpeechCraftFrame.__init__ so the
# splash can show construction progress instead of an invisible freeze.
# sounddevice (~3 MB), pyaudio (~6 MB), and batch_processor (which
# pulls in pedalboard and scipy via audio_effects) are deferred until
# the relevant UI section runs, so the first-paint splash can show
# progress while they're loading.
_LAZY_IMPORTS = {
    "sounddevice": "sound device input/output (AudioClipboard, live monitoring)",
    "pyaudio": "PyAudio (recording engine)",
    "batch_processor": "Batch processor (Effects → Batch Process…)",
}

# Configure FFmpeg path - simplified startup check
def setup_ffmpeg():
    """Setup FFmpeg if available. Returns (ok, message)."""
    import shutil

    # Check local directory first
    local_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        AudioSegment.converter = local_ffmpeg
        AudioSegment.ffmpeg = local_ffmpeg
        AudioSegment.ffprobe = local_ffmpeg
        print(f"Using local FFmpeg: {local_ffmpeg}")
        return True, f"Found FFmpeg in project folder"

    # Check system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        AudioSegment.converter = system_ffmpeg
        AudioSegment.ffmpeg = system_ffmpeg
        AudioSegment.ffprobe = shutil.which("ffprobe") or system_ffmpeg
        print(f"Using system FFmpeg: {system_ffmpeg}")
        return True, f"Found FFmpeg on system PATH"

    # FFmpeg not found - will be handled by dialog later
    print("FFmpeg not found - audio import will be limited")
    return False, "FFmpeg not found - some features will be limited"


# Setup FFmpeg on startup (silent)
setup_ffmpeg()

# --- LOGIC IMPORTS ---
class DummyModule:
    """A placeholder module that provides helpful errors when accessed"""
    def __init__(self, name, error_msg):
        self._name = name
        self._error_msg = error_msg
    def __getattr__(self, attr):
        # Return a function that raises the error when called
        def missing_feature(*args, **kwargs):
            import wx
            wx.MessageBox(
                f"The feature '{attr}' requires the '{self._name}' module, which is missing.\n\n"
                f"Error: {self._error_msg}\n\n"
                "Please check your installation.",
                "Feature Unavailable",
                wx.ICON_ERROR
            )
        return missing_feature

def safe_import(module_name):
    try:
        return __import__(module_name)
    except ImportError as e:
        print(f"Warning: Module {module_name} not available: {e}")
        return DummyModule(module_name, str(e))

transcription = safe_import('transcription')
breath_smoothing = safe_import('breath_smoothing')
auto_ducker = safe_import('auto_ducker')
audio_effects = safe_import('audio_effects')
line_placer = safe_import('line_placer')
script_handler = safe_import('script_handler')
word_alignment = safe_import('word_alignment')
audio_recorder = safe_import('audio_recorder')

class SpeechCraftFrame(TTSMenuMixin, wx.Frame):
    def __init__(self, progress=None):
        """Build the main window.

        Parameters
        ----------
        progress : callable | None
            Optional ``(step_name, status) -> None`` callback that gets
            called after each major setup chunk. Used by the Splash
            window to show construction progress. The callback is
            permitted to be None (e.g. tests, headless boots) — every
            call site guards against that.
        """
        if progress is None:
            def progress(_step, _status=""):  # noqa: F811
                return None

        print("STARTING INIT")
        super().__init__(parent=None, title='SpeechCraft Studio', size=(1000, 800))

        # Check FFmpeg before continuing
        progress("Preparing workspace", "Checking audio engine")
        self.check_ffmpeg_with_dialog()

        # Lazy-load sounddevice here. On the bundle this module is
        # ~3 MB; deferring it until the frame is being constructed
        # lets the splash update before this slow import.
        progress("Preparing workspace", "Loading audio device module")
        global sd
        import sounddevice as sd  # noqa: F811

        # Safety / Late Init for UI components
        self.workspace = None
        self.log_area = None
        self.tracks_list = None

        progress("Preparing workspace", "Building the menu bar")
        self.init_ui()
        self.create_menus()

        # --- AUDIO ENGINE ---
        self.audio_loaded = False
        self.stream = None # For sounddevice
        self.current_samples_float = None
        self.current_samples_int16 = None
        self.sample_rate = 44100

        # Track Manager Integration
        self.track_manager = audio_tracks.TrackManager()
        self.active_track_index = -1

        self.playhead_ms = 0

        # Data State
        self.current_script = None
        self.current_transcript = ""
        self.word_alignment = None

        # Project State
        self.default_project_dir = project_handler.ProjectHandler.get_default_project_dir()
        print(f"DEBUG: Default Project Dir: {self.default_project_dir}")

        # Audio Engine State
        self.audio_engine = "sounddevice" # Options: "sounddevice", "pyaudio", "custom_asio"
        progress("Preparing workspace", "Initialising PyAudio for recording")
        import pyaudio  # noqa: F811  # PyAudio is heavyweight (~6 MB) but needed for recording
        self.pyaudio_instance = pyaudio.PyAudio()
        self._playing = False
        self.monitor_volume = 1.0  # Director volume control

        # Custom ASIO support
        self.asio_manager = None

        # Before/After comparison state
        self._original_samples_float = None   # Saved original audio for A/B compare
        self._original_samples_int16 = None
        self._playback_mode = "processed"      # "processed" or "original"
        self._has_original = False              # True once original has been saved
        try:
            import custom_asio
            self.asio_manager = custom_asio.get_asio_manager()
        except ImportError:
            pass

        # Safety Init
        self.workspace = None
        self.log_area = None
        self.tracks_list = None

        # Audio Engine
        progress("Preparing workspace", "Setting up audio recorder")
        import audio_recorder  # noqa: F811
        self.recorder = audio_recorder.AudioRecorder(progress_callback=self.update_record_time)
        self.is_recording = False

        # Undo History
        self.undo_stack = []
        self.redo_stack = []

        # Initialize UI (THIS WAS MISSING!)
        self.init_ui()
        self.create_menus()
        self.CreateStatusBar()  # Create status bar AFTER menus

        progress("Preparing workspace", "Almost there, finishing UI…")

        # Bind key events after controls are created
        if self.workspace:
            self.workspace.Bind(wx.EVT_KEY_UP, self.on_workspace_key_up)
        if self.log_area:
            self.log_area.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

        wx.CallAfter(self.announce_welcome)

    def announce(self, text):
        """Update status bar for screen reader accessibility"""
        self.SetStatusText(text)

    def announce_welcome(self):
        if self.tracks_list:
            self.tracks_list.SetFocus()
        self.SetStatusText("SpeechCraft Studio loaded. Press F6 to navigate regions.")

    def on_global_key(self, event):
        keycode = event.GetKeyCode()
        
        # Debug: Log all key presses to verify this handler is working
        if keycode == wx.WXK_SPACE:
            print(f"DEBUG: on_global_key called! KeyCode={keycode}, Focus={self.FindFocus()}")
        
        # Space = Play/Pause (global override)
        if keycode == wx.WXK_SPACE:
            focus = self.FindFocus()
            
            # Only allow Space to type normally in the workspace (Region 2)
            # In all other regions (Tracks List, Log Area), Space = Play/Pause
            if focus == self.workspace and not event.ControlDown():
                event.Skip()  # Let space type in workspace
                return
            
            # Trigger playback
            print("DEBUG: Space key intercepted - triggering playback")
            self.on_play_pause(None)
            return
        
        # Let other keys pass through
        event.Skip()

    def init_ui(self):
        self.panel = wx.Panel(self)
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # REGION 1: Tracks (Timeline)
        self.tracks_label = wx.StaticText(self.panel, label="Region 1: Tracks (Timeline)")
        self.tracks_list = wx.ListBox(self.panel, style=wx.LB_SINGLE)
        self.tracks_list.Bind(wx.EVT_KEY_DOWN, self.on_tracks_key_down)

        # REGION 2: Workspace (Transcript)
        self.workspace_label = wx.StaticText(self.panel, label="Region 2: Transcript Workspace")
        self.workspace = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_RICH2)
        self.workspace.Bind(wx.EVT_TEXT, self.on_text_changed)
        self.workspace.Bind(wx.EVT_KEY_DOWN, self.on_workspace_key_down)
        
        # REGION 3: Log Area (For transcription output and status)
        self.log_label = wx.StaticText(self.panel, label="Region 3: Process Logs and Output")
        self.log_area = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY)

        self.main_sizer.Add(self.tracks_label, 0, wx.ALL, 5)
        self.main_sizer.Add(self.tracks_list, 1, wx.EXPAND | wx.ALL, 5)
        self.main_sizer.Add(self.workspace_label, 0, wx.ALL, 5)
        self.main_sizer.Add(self.workspace, 3, wx.EXPAND | wx.ALL, 5)
        self.main_sizer.Add(self.log_label, 0, wx.ALL, 5)
        self.main_sizer.Add(self.log_area, 1, wx.EXPAND | wx.ALL, 5)

        
        self.panel.SetSizer(self.main_sizer)
        
        # Global key handler for Space (must be bound AFTER controls are created)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_global_key)

    def create_menus(self):
        self.menubar = wx.MenuBar()
        # --- 1. FILE ---
        m_file = wx.Menu()
        self.add_item(m_file, "&Open Audio\tCtrl+O", self.on_open_audio)
        self.add_item(m_file, "&Record / Stop\tCtrl+R", self.on_toggle_record)
        self.add_item(m_file, "Open &Script\tCtrl+I", self.on_open_script)
        m_file.AppendSeparator()
        self.add_item(m_file, "&Load Project...\tCtrl+L", self.on_load_project)
        self.add_item(m_file, "&Save Project\tCtrl+S", self.on_save_project)
        m_file.AppendSeparator()
        self.add_item(m_file, "Save &Transcript\tCtrl+Shift+S", self.on_save_transcript)
        self.add_item(m_file, "&Export Audio...\tCtrl+E", self.on_export_audio)
        m_file.AppendSeparator()
        self.add_item(m_file, "&Export Presets...\tCtrl+Shift+E", self.on_export_presets)
        self.add_item(m_file, "&Import Presets...\tCtrl+Shift+I", self.on_import_presets)
        m_file.AppendSeparator()
        self.add_item(m_file, "&Batch Process...\tCtrl+Shift+B", self.on_batch_process)
        m_file.AppendSeparator()
        self.add_item(m_file, "&Exit\tAlt+F4", self.on_exit)
        self.menubar.Append(m_file, "&File")
        
        # --- 2. EDIT ---
        m_edit = wx.Menu()
        self.add_item(m_edit, "Cu&t (Audio+Text)\tCtrl+X", self.on_cut_destructive)
        self.add_item(m_edit, "&Copy\tCtrl+C", self.on_copy)
        self.add_item(m_edit, "&Paste\tCtrl+V", self.on_paste)
        m_edit.AppendSeparator()
        self.undo_menu_item = self.add_item(m_edit, "&Undo\tCtrl+Z", self.on_undo)
        self.redo_menu_item = self.add_item(m_edit, "&Redo\tCtrl+Y", self.on_redo)
        self.undo_menu_item.Enable(False)
        self.redo_menu_item.Enable(False)
        m_edit.AppendSeparator()
        self.add_item(m_edit, "&Jump to Time...\tCtrl+J", self.on_jump_to_time)
        m_edit.AppendSeparator()
        self.add_item(m_edit, "Nudge &Left\t,", self.on_nudge_left)
        self.add_item(m_edit, "Nudge &Right\t.", self.on_nudge_right)
        self.add_item(m_edit, "Nudge Left (&Fine)\tShift+,", self.on_nudge_left_fine)
        self.add_item(m_edit, "Nudge Right (F&ine)\tShift+.", self.on_nudge_right_fine)
        m_edit.AppendSeparator()
        self.edit_mode_item = m_edit.AppendCheckItem(wx.ID_ANY, "Destructive Edit Mode")
        self.Bind(wx.EVT_MENU, self.on_toggle_destructive_mode, self.edit_mode_item)
        self.menubar.Append(m_edit, "&Edit")

        # --- 2. TOOLS ---
        m_tools = wx.Menu()
        self.add_item(m_tools, "&Transcribe\tCtrl+T", self.on_transcribe)
        self.add_item(m_tools, "Auto &Line Placer\tCtrl+P", self.on_line_placer)
        m_tools.AppendSeparator()
        self.add_item(m_tools, "&Studio Recording\tCtrl+Shift+R", self.on_studio_recording)
        self.menubar.Append(m_tools, "&Tools")

        # --- 3. MULTI-TRACK ---
        m_track = wx.Menu()
        self.add_item(m_track, "&Add New Track", self.on_add_track_menu)
        self.add_item(m_track, "&Rename Track", None)
        m_track.AppendSeparator()
        self.add_item(m_track, "Toggle &Mute\tCtrl+M", self.on_toggle_mute)
        self.add_item(m_track, "Toggle &Solo\tCtrl+Shift+M", self.on_toggle_solo)
        self.menubar.Append(m_track, "&Multi-track")

        # --- 4b. AUDIO (channel conversion) ---
        m_audio = wx.Menu()
        mono_item = self.add_item(m_audio, "To &Mono\tCtrl+Alt+M", self.on_convert_mono)
        stereo_item = self.add_item(m_audio, "To &Stereo\tCtrl+Alt+S", self.on_convert_stereo)
        m_audio.AppendSeparator()
        self.add_item(m_audio, "&Room Tone Match...\tCtrl+Shift+R", self.on_room_tone_match)
        m_audio.AppendSeparator()
        self.channel_info_item = m_audio.Append(wx.ID_ANY, "Channel Info: —")
        self.channel_info_item.Enable(False)  # read-only status item
        self.menubar.Append(m_audio, "&Audio")

        # --- 4. EFFECTS ---
        m_effects = wx.Menu()
        self.add_item(m_effects, "&Breath Smoothing\tCtrl+B", self.on_effect_breath)
        self.ba_toggle_item = m_effects.AppendCheckItem(
            wx.ID_ANY,
            "&Before / After (B)",
            "Toggle between original and processed audio.")
        self.ba_toggle_item.Check(False)
        self.ba_toggle_item.Enable(False)  # Enable only after first effect is applied
        self.Bind(wx.EVT_MENU, self.on_before_after_toggle, self.ba_toggle_item)
        m_effects.AppendSeparator()
        self.add_item(m_effects, "Trim Beginning Silence\tCtrl+Shift+T", self.on_trim_silence)
        self.add_item(m_effects, "&Normalize\tF5", self.on_normalize)
        self.add_item(m_effects, "Denoise / Noise Gate\tF6", self.on_denoise)
        m_effects.AppendSeparator()
        self.add_item(m_effects, "Room Remover\tCtrl+Shift+H", self.on_effect_room)
        self.add_item(m_effects, "Compressor\tCtrl+Shift+P", self.on_effect_compressor)
        self.add_item(m_effects, "De-esser\tCtrl+Shift+S", self.on_effect_deesser)
        self.add_item(m_effects, "Equalizer\tCtrl+Shift+Q", self.on_effect_equalizer)
        m_effects.AppendSeparator()
        self.add_item(m_effects, "Auto-&Ducker\tCtrl+D", self.on_auto_ducker)
        self.menubar.Append(m_effects, "&Effects")

        # --- 5. PLAYBACK ---
        m_play = wx.Menu()
        self.add_item(m_play, "&Play / Pause\tSpace", self.on_play_pause)
        self.add_item(m_play, "&Stop\tCtrl+Period", self.on_stop)
        self.add_item(m_play, "Rewind (5s)\tCtrl+Left", self.on_rewind)
        self.add_item(m_play, "Fast Forward (5s)\tCtrl+Right", self.on_forward)
        self.add_item(m_play, "Volume &Up\tCtrl+Up", self.on_vol_up)
        self.add_item(m_play, "Volume &Down\tCtrl+Down", self.on_vol_down)
        m_play.AppendSeparator()
        self.add_item(m_play, "Audio &Setup...", self.on_audio_setup)
        self.add_item(m_play, "&Reset Audio Engine", self.on_reset_audio)
        self.add_item(m_play, "&Check Signal Integrity (Open wav)", self.on_check_integrity)
        self.menubar.Append(m_play, "&Playback")

        # --- 5b. SPEECH (TTS) ---
        m_speech = wx.Menu()
        self.add_item(m_speech, "&Edge TTS (Microsoft) — Free", self.on_edge_tts)
        self.add_item(m_speech, "&Piper TTS — On-device neural", self.on_piper_tts)
        self.menubar.Append(m_speech, "&Speech")

        # --- 6. HELP ---
        m_help = wx.Menu()
        self.add_item(m_help, "&User Manual\tF1", self.on_help_manual)
        self.add_item(m_help, "&Quick Reference\tF2", self.on_help_quick)
        m_help.AppendSeparator()
        self.add_item(m_help, "&Report a Bug...", self.on_report_bug)
        self.menubar.Append(m_help, "&Help")

        self.SetMenuBar(self.menubar)

    def on_help_manual(self, event):
        help_path = self._get_resource_path("help/index.html")
        webbrowser.open(f"file://{help_path}")
        
    def on_help_quick(self, event):
        help_path = self._get_resource_path("help/quick-reference.html")
        webbrowser.open(f"file://{help_path}")
    
    def _get_resource_path(self, relative_path):
        """Get absolute path to resource, works for dev and for PyInstaller"""
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def on_report_bug(self, event):
        """Open the in-app bug-report dialog.

        Imports lazily so the dialog module is not a hard dependency
        of audio_editor.py and so a missing/crashing dialog does not
        take the whole app down.
        """
        try:
            from bug_report_dialog import BugReportDialog
            from crash_submit import read_log_tail
        except ImportError as e:
            wx.MessageBox(
                f"The bug-report dialog could not be loaded:\n\n{e}\n\n"
                f"You can file the report directly at:\n"
                f"https://github.com/trasles16-ux/speechcraft-audio/issues/new",
                "Report a Bug",
                wx.OK | wx.ICON_WARNING,
            )
            return

        log_tail = read_log_tail()
        dlg = BugReportDialog(
            self,
            app_version=__version__ if "__version__" in globals() else "3.0.2",
            log_tail=log_tail,
        )
        dlg.show()

    def add_item(self, menu, label, callback):
        item = menu.Append(wx.ID_ANY, label)
        if callback: self.Bind(wx.EVT_MENU, callback, item)
        return item

    def push_undo_state(self):
        """Save a snapshot of the current state for undo.

        Saves: all track audio segments, word alignment, and transcript text.
        Clears the redo stack (once you make a new change, redo is discarded).
        Respects config['max_undo_levels'] for stack size.
        """
        from copy import deepcopy
        state = {
            "tracks_audio": [deepcopy(t.audio_segment) for t in self.track_manager.tracks],
            "alignment": deepcopy(self.word_alignment),
            "transcript": self.workspace.GetValue()
        }
        self.undo_stack.append(state)

        # Respect configured limit (default 10)
        max_levels = config.MEMORY.get('max_undo_levels', 10)
        while len(self.undo_stack) > max_levels:
            self.undo_stack.pop(0)

        self.redo_stack.clear()
        self._update_undo_menu_state()

    def _update_undo_menu_state(self):
        """Enable/disable Undo and Redo menu items based on stack contents."""
        can_undo = bool(self.undo_stack)
        can_redo = bool(self.redo_stack)
        if hasattr(self, 'undo_menu_item'):
            self.undo_menu_item.Enable(can_undo)
        if hasattr(self, 'redo_menu_item'):
            self.redo_menu_item.Enable(can_redo)

    # --- REGION NAVIGATION ---
    def on_f6(self, event=None): # Added event arg for consistency
        focus = self.FindFocus()
        if focus == self.tracks_list:
            self.workspace.SetFocus()
            self.SetStatusText("Region: Transcript Workspace")
        elif focus == self.workspace:
            self.log_area.SetFocus()
            self.SetStatusText("Region: Process Logs")
        else:
            self.tracks_list.SetFocus()
            self.SetStatusText("Region: Tracks List")

    # --- TRACKS & NAVIGATION ---
    def on_add_track_menu(self, event):
        self.on_add_track(name="New Track")

    def on_add_track(self, event=None, name="New Track", audio=None):
        print(f"DEBUG: on_add_track called. Name: {name}, Has audio: {audio is not None}")
        # Use TrackManager
        t_type = audio_tracks.TrackType.VOICE # Default
        track = self.track_manager.add_track(name, audio_segment=audio, track_type=t_type)
        
        self._refresh_track_list()
        
        # Select new track
        count = len(self.track_manager.tracks)
        self.active_track_index = count - 1
        self.tracks_list.SetSelection(self.active_track_index)
        self.SetStatusText(f"Added track: {name}.")
        
        # Update mix
        self._remix_audio()

    def _refresh_track_list(self):
        self.tracks_list.Clear()
        for i, t in enumerate(self.track_manager.tracks):
            # Format: Track N: [M][S] Name
            prefix = ""
            if t.muted: prefix += "[M]"
            if t.solo: prefix += "[S]"
            label = f"Track {i+1}: {prefix} {t.name}"
            self.tracks_list.Append(label)
        
        if self.active_track_index >= 0 and self.active_track_index < self.tracks_list.GetCount():
            self.tracks_list.SetSelection(self.active_track_index)

    def on_toggle_mute(self, event):
        idx = self.tracks_list.GetSelection()
        if idx == wx.NOT_FOUND: return
        
        track = self.track_manager.tracks[idx]
        track.muted = not track.muted
        self._refresh_track_list()
        self._remix_audio()
        state = "Muted" if track.muted else "Unmuted"
        self.SetStatusText(f"Track {state}.")

    def on_toggle_solo(self, event):
        idx = self.tracks_list.GetSelection()
        if idx == wx.NOT_FOUND: return
        
        track = self.track_manager.tracks[idx]
        track.solo = not track.solo
        self._refresh_track_list()
        self._remix_audio()
        state = "Soloed" if track.solo else "Unsoloed"
        self.SetStatusText(f"Track {state}.")

    def _remix_audio(self):
        print("DEBUG: _remix_audio called")
        # Mix down and get numpy array for output
        mixed = self.track_manager.mix_down()
        print(f"DEBUG: mix_down returned: {mixed is not None}")
        if mixed:
             # Stop current playback
            try: sd.stop()
            except: pass
            
            # 1. Determine Native Hardware Rate
            try:
                device_id = getattr(self, 'output_device_id', sd.default.device[1])
                if device_id == -1: device_id = None
                info = sd.query_devices(device_id, 'output')
                target_rate = int(info['default_samplerate'])
            except:
                target_rate = 44100
                
            # 2. Resample if necessary (Using pydub)
            if mixed.frame_rate != target_rate:
                print(f"DEBUG: Resampling from {mixed.frame_rate} to {target_rate}")
                mixed = mixed.set_frame_rate(target_rate)
            
            # 3. Convert to Float32 for Pedalboard/SoundDevice
            samples = np.array(mixed.get_array_of_samples()).astype(np.float32)
            max_val = float(1 << (8 * mixed.sample_width - 1))
            samples = samples / max_val
            
            # 4. Ensure Stereo
            if mixed.channels == 1:
                samples = np.column_stack((samples, samples))
            elif mixed.channels > 1:
                samples = samples.reshape((-1, mixed.channels))
                if mixed.channels > 2:
                    samples = samples[:, :2] # Truncate to stereo
            
            self.current_samples_float = samples
            self.current_samples_int16 = (samples * 32767).astype(np.int16)
            self.sample_rate = target_rate
            
            # Validation
            peak = np.max(np.abs(samples))
            print(f"DEBUG: Audio Remixed. Rate: {self.sample_rate}, Peak: {peak:.3f}")
            
            if peak < 0.001:
                 print("WARNING: Audio signal is very weak or silent!")
            
            self.current_audio = mixed
            self.audio_loaded = True
            
            # Save temp for reference
            threading.Thread(target=lambda: mixed.export("temp_playback.wav", format="wav"), daemon=True).start()

    def on_tracks_key_down(self, event):
        keycode = event.GetKeyCode()
        ctrl = event.ControlDown()
        
        print(f"DEBUG: on_tracks_key_down called! KeyCode={keycode}")
        
        if keycode == wx.WXK_LEFT:
            if ctrl: self.on_rewind(None)
            else: self.scrub(-1000)
        elif keycode == wx.WXK_RIGHT:
            if ctrl: self.on_forward(None)
            else: self.scrub(1000)
        elif keycode == wx.WXK_SPACE:
            print("DEBUG: Space detected in tracks list - calling on_play_pause")
            self.on_play_pause(None)
        elif keycode == ord(',') or keycode == ord('<'):
            if event.ShiftDown(): self.on_nudge_left_fine(None)
            else: self.on_nudge_left(None)
        elif keycode == ord('.') or keycode == ord('>'):
            if event.ShiftDown(): self.on_nudge_right_fine(None)
            else: self.on_nudge_right(None)
        elif keycode == wx.WXK_F6:
            self.on_f6()
        elif keycode == ord('B') or keycode == ord('b'):
            self.on_before_after_toggle(None)
        elif keycode == wx.WXK_F5:
            self.on_normalize(None)
        elif keycode == wx.WXK_F6:
            self.on_denoise(None)
        elif keycode == wx.WXK_ESCAPE:
            # Close any open effect dialog
            if hasattr(self, 'dlg') and self.dlg:
                self.dlg.EndModal(wx.ID_CANCEL)
            self.announce("Cancelled.")
        else:
            event.Skip() # Allow default listbox navigation (Up/Down)

    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        ctrl = event.ControlDown()
        
        if keycode == wx.WXK_F6:
            self.on_f6()
        elif keycode == wx.WXK_ESCAPE:
            if hasattr(self, 'dlg') and self.dlg:
                self.dlg.EndModal(wx.ID_CANCEL)
                self.announce("Cancelled.")
        elif keycode == wx.WXK_UP and ctrl:
            self.on_vol_up(None)
        elif keycode == wx.WXK_DOWN and ctrl:
            self.on_vol_down(None)
        elif keycode == wx.WXK_LEFT and ctrl: # Scrub
             self.on_rewind(None)
        elif keycode == wx.WXK_RIGHT and ctrl: # Scrub
             self.on_forward(None)
        elif keycode == wx.WXK_SPACE and ctrl: # Play
             self.on_play_pause(None)
        else:
            event.Skip()

    def on_workspace_key_down(self, event):
        """Handle key presses in workspace for navigation and destructive editing"""
        keycode = event.GetKeyCode()
        ctrl = event.ControlDown()
        shift = event.ShiftDown()
        
        # Word-by-word navigation
        if ctrl and keycode == wx.WXK_LEFT:
            # Move to previous word
            pos = self.workspace.GetInsertionPoint()
            text = self.workspace.GetValue()
            new_pos = self._find_word_boundary(text, pos, -1)
            if shift:
                # Extend selection
                start, end = self.workspace.GetSelection()
                if start == end:  # No current selection
                    self.workspace.SetSelection(pos, new_pos)
                else:
                    self.workspace.SetSelection(start, new_pos)
            else:
                self.workspace.SetInsertionPoint(new_pos)
            return
            
        elif ctrl and keycode == wx.WXK_RIGHT:
            # Move to next word
            pos = self.workspace.GetInsertionPoint()
            text = self.workspace.GetValue()
            new_pos = self._find_word_boundary(text, pos, 1)
            if shift:
                # Extend selection
                start, end = self.workspace.GetSelection()
                if start == end:  # No current selection
                    self.workspace.SetSelection(pos, new_pos)
                else:
                    self.workspace.SetSelection(start, new_pos)
            else:
                self.workspace.SetInsertionPoint(new_pos)
            return
            
        # Handle destructive editing triggers
        if self.edit_mode_item.IsChecked():
            if keycode in [wx.WXK_DELETE, wx.WXK_BACK]:
                wx.CallAfter(self.sync_text_to_audio)
                
        # Other workspace shortcuts
        if keycode == wx.WXK_F6:
            self.on_f6()
            return
        elif keycode == wx.WXK_ESCAPE:
            if hasattr(self, 'dlg') and self.dlg:
                self.dlg.EndModal(wx.ID_CANCEL)
                self.announce("Cancelled.")
            
        event.Skip()
        
    def _find_word_boundary(self, text, pos, direction):
        """Find word boundary for Ctrl+Arrow navigation"""
        if direction == -1:  # Moving left
            # Skip current whitespace
            while pos > 0 and text[pos-1].isspace():
                pos -= 1
            # Skip current word
            while pos > 0 and not text[pos-1].isspace():
                pos -= 1
        else:  # Moving right
            # Skip current word
            while pos < len(text) and not text[pos].isspace():
                pos += 1
            # Skip whitespace
            while pos < len(text) and text[pos].isspace():
                pos += 1
        return max(0, min(pos, len(text)))

    def on_workspace_key_up(self, event):
        """Handle key releases in workspace for destructive editing"""
        if self.edit_mode_item.IsChecked():
            keycode = event.GetKeyCode()
            if keycode in [wx.WXK_DELETE, wx.WXK_BACK]:
                wx.CallAfter(self.sync_text_to_audio)
        event.Skip()

    def check_ffmpeg_with_dialog(self):
        """Check FFmpeg with user dialog if download needed"""
        import shutil
        
        # Quick check if already available
        local_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
        if os.path.exists(local_ffmpeg) or shutil.which("ffmpeg"):
            return  # Already available
            
        # Ask user if they want to download FFmpeg
        dlg = wx.MessageDialog(
            self,
            "FFmpeg is required for MP3 support but was not found.\n\n"
            "Would you like to download it automatically?\n"
            "(This is a one-time download of about 100MB)",
            "FFmpeg Required",
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if dlg.ShowModal() == wx.ID_YES:
            # Show progress dialog
            progress_dlg = wx.ProgressDialog(
                "Downloading FFmpeg",
                "Downloading FFmpeg for MP3 support...",
                maximum=100,
                parent=self,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
            )
            progress_dlg.Pulse()
            
            # Download in thread
            import threading
            def download_worker():
                success = self.download_ffmpeg()
                wx.CallAfter(self.on_ffmpeg_download_complete, progress_dlg, success)
                
            threading.Thread(target=download_worker, daemon=True).start()
        else:
            wx.MessageBox(
                "FFmpeg was not installed. MP3 files will not be supported.\n"
                "You can still use WAV files for all features.",
                "FFmpeg Skipped",
                wx.ICON_INFORMATION
            )
        
        dlg.Destroy()
        
    def download_ffmpeg(self):
        """Download FFmpeg (called from thread)"""
        try:
            import urllib.request
            import zipfile
            import tempfile
            import shutil
            
            ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = os.path.join(temp_dir, "ffmpeg.zip")
                urllib.request.urlretrieve(ffmpeg_url, zip_path)
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Find ffmpeg.exe in extracted files
                for root, dirs, files in os.walk(temp_dir):
                    if "ffmpeg.exe" in files:
                        src_ffmpeg = os.path.join(root, "ffmpeg.exe")
                        dst_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
                        shutil.copy2(src_ffmpeg, dst_ffmpeg)
                        
                        # Configure pydub
                        AudioSegment.converter = dst_ffmpeg
                        AudioSegment.ffmpeg = dst_ffmpeg
                        AudioSegment.ffprobe = dst_ffmpeg
                        return True
            return False
        except Exception as e:
            print(f"FFmpeg download failed: {e}")
            return False
            
    def on_ffmpeg_download_complete(self, progress_dlg, success):
        """Handle FFmpeg download completion"""
        progress_dlg.Destroy()
        
        if success:
            wx.MessageBox(
                "FFmpeg downloaded successfully!\n"
                "MP3 files are now supported.",
                "Download Complete",
                wx.ICON_INFORMATION
            )
        else:
            wx.MessageBox(
                "FFmpeg download failed.\n"
                "MP3 files will not be supported, but WAV files will work.",
                "Download Failed",
                wx.ICON_WARNING
            )

    def on_studio_recording(self, event):
        """Start studio recording session with live transcription"""
        if not self.current_script:
            wx.MessageBox(
                "Studio Recording requires a script file.\n\n"
                "Please load a script first using File > Open Script.",
                "Script Required", wx.ICON_WARNING
            )
            return
            
        # Ask about second monitor
        monitor_choice = wx.MessageBox(
            "Choose monitor setup:\n\n"
            "YES = Physical second monitor\n"
            "NO = Network monitor (voice actor's computer)\n"
            "CANCEL = Director monitor only",
            "Monitor Setup", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
        )
        
        use_second_monitor = monitor_choice == wx.YES
        use_network_monitor = monitor_choice == wx.NO
            
        # Show studio recording dialog
        dlg = StudioRecordingDialog(self, self.current_script, 
                                   input_device_id=getattr(self, 'input_device_id', None),
                                   use_second_monitor=use_second_monitor,
                                   use_network_monitor=use_network_monitor)
        
        if dlg.ShowModal() == wx.ID_OK:
            # Get the recorded audio
            final_audio = dlg.get_final_audio()
            if final_audio:
                # Replace the progressive audio with the final assembled audio
                self.load_audio_from_segment(final_audio, name="Studio Recording")

                # Show session report
                report = dlg.get_session_report()
                self.log_area.AppendText("\n--- Studio Recording Report ---\n" + report + "\n")

                self.SetStatusText("Studio recording completed successfully.")
            else:
                self.SetStatusText("Studio recording was cancelled or failed.")
                
        dlg.Destroy()

    def on_text_changed(self, event):
        """Handle text changes for destructive editing"""
        if self.edit_mode_item.IsChecked() and self.word_alignment:
            # Debounce text changes to avoid excessive processing
            if hasattr(self, '_text_change_timer'):
                self._text_change_timer.Stop()
            self._text_change_timer = wx.CallLater(500, self.sync_text_to_audio)
        event.Skip()

    def sync_text_to_audio(self):
        """Sync current text content with audio using word alignment"""
        if not self.word_alignment or not self.edit_mode_item.IsChecked():
            return
            
        current_text = self.workspace.GetValue()
        original_text = self.word_alignment.get_transcript_text()
        
        if current_text == original_text:
            return  # No changes
            
        # Find differences and apply destructive edits
        self._apply_text_diff_to_audio(original_text, current_text)

    def cycle_tracks(self, direction):
        pass # Removed

    # --- SCRUBBING WITH SOUND ---
    def scrub(self, ms):
        self.playhead_ms = max(0, self.playhead_ms + ms)
        
        if self.audio_loaded and hasattr(self, 'current_samples_float') and self.current_samples_float is not None:
            # Calculate scrub position
            start_idx = int((self.playhead_ms / 1000) * self.sample_rate)
            
            # Ensure we don't go past the end
            if start_idx >= len(self.current_samples_float):
                self.playhead_ms = (len(self.current_samples_float) / self.sample_rate) * 1000
                start_idx = len(self.current_samples_float) - int(0.1 * self.sample_rate)
                
            # Create 100ms audio blip for scrubbing
            blip_duration = int(0.1 * self.sample_rate)  # 100ms
            end_idx = min(start_idx + blip_duration, len(self.current_samples_float))
            
            if end_idx > start_idx:
                blip_f32 = self.current_samples_float[start_idx:end_idx]
                
                # Stop any current playback first
                try:
                    sd.stop()
                except:
                    pass
                    
                # Play scrub audio
                try:
                    sd.play(blip_f32, self.sample_rate, device=getattr(self, 'output_device_id', None))
                except Exception as e:
                    print(f"Scrub audio failed: {e}")
        
        # Update status for screen reader
        self.SetStatusText(f"Position: {self.playhead_ms/1000:.1f} seconds")

    def on_forward(self, event):
        self.scrub(5000)
        self.SetStatusText(f"Forward 5s. Pos: {self.playhead_ms/1000:.1f}s")

    def on_rewind(self, event):
        self.scrub(-5000)
        self.SetStatusText(f"Rewind 5s. Pos: {self.playhead_ms/1000:.1f}s")

    def on_jump_to_time(self, event):
        dlg = wx.TextEntryDialog(self, "Enter time (MM:SS or SS):", "Jump to Time")
        if dlg.ShowModal() == wx.ID_OK:
            val = dlg.GetValue().strip()
            try:
                if ":" in val:
                    parts = val.split(":")
                    if len(parts) == 2:
                        m, s = map(int, parts)
                        ms = (m * 60 + s) * 1000
                    elif len(parts) == 3:
                        h, m, s = map(int, parts)
                        ms = (h * 3600 + m * 60 + s) * 1000
                    else:
                        raise ValueError
                else:
                    ms = int(val) * 1000
                
                self.playhead_ms = ms
                self.scrub(0)
                self.SetStatusText(f"Jumped to {val}. Pos: {self.playhead_ms/1000:.1f}s")
            except ValueError:
                wx.MessageBox("Invalid time format. Use MM:SS or SS.", "Error", wx.ICON_ERROR)
        dlg.Destroy()

    def on_nudge_left(self, event):
        self.scrub(-500)
        self.SetStatusText(f"Nudge Left. Pos: {self.playhead_ms/1000:.1f}s")

    def on_nudge_right(self, event):
        self.scrub(500)
        self.SetStatusText(f"Nudge Right. Pos: {self.playhead_ms/1000:.1f}s")

    def on_nudge_left_fine(self, event):
        self.scrub(-50)
        self.SetStatusText(f"Nudge Left (Fine). Pos: {self.playhead_ms/1000:.1f}s")

    def on_nudge_right_fine(self, event):
        self.scrub(50)
        self.SetStatusText(f"Nudge Right (Fine). Pos: {self.playhead_ms/1000:.1f}s")

    # --- FILE & EFFECTS ---
    def on_open_audio(self, event):
        with wx.FileDialog(self, "Open Audio", wildcard="Audio (*.wav;*.mp3)|*.wav;*.mp3") as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                # Reset before/after state for new file — original audio is now this file
                self._has_original = False
                self._playback_mode = "processed"
                self.ba_toggle_item.Check(False)
                self.load_audio(path)

    def load_audio(self, path):
        print(f"DEBUG: load_audio called with path: {path}")
        # New logic: Add as track
        try:
            seg = AudioSegment.from_file(path)
            print(f"DEBUG: AudioSegment loaded. Duration: {len(seg)}ms, Channels: {seg.channels}")
        except FileNotFoundError as e:
            # FFmpeg not found - try direct WAV loading
            if path.lower().endswith('.wav'):
                import wave
                with wave.open(path, 'rb') as wav:
                    frames = wav.readframes(wav.getnframes())
                    seg = AudioSegment(
                        data=frames,
                        sample_width=wav.getsampwidth(),
                        frame_rate=wav.getframerate(),
                        channels=wav.getnchannels()
                    )
                self.log_area.AppendText("Loaded WAV directly (ffmpeg not found)\n")
            else:
                wx.MessageBox(
                    f"Cannot load {os.path.basename(path)}.\n\n"
                    "FFmpeg is required for MP3/other formats.\n"
                    "Please install ffmpeg or use WAV files.",
                    "FFmpeg Missing", wx.ICON_ERROR
                )
                return

        self.load_audio_from_segment(seg, name=os.path.basename(path))

    def load_audio_from_segment(self, audio_segment, name="Studio Recording"):
        """Load an AudioSegment directly, replacing all existing tracks.

        Used by the studio recorder for progressive audio — after each line
        completes, the director can hear the recording building up in real
        time with all completed lines placed at their correct time positions.
        """
        # Stop any current playback
        try:
            sd.stop()
        except Exception:
            pass

        # Clear all existing tracks (progressive audio replaces everything)
        self.track_manager.tracks = []
        self.active_track_index = -1

        # Add the segment as the single track
        self.on_add_track(name=name, audio=audio_segment)

    def on_save_transcript(self, event):
        with wx.FileDialog(self, "Save Transcript", wildcard="Text (*.txt)|*.txt", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(self.workspace.GetValue())
                    self.SetStatusText(f"Saved transcript to {os.path.basename(path)}")
                except Exception as e:
                    wx.MessageBox(f"Error saving: {e}", "Error", wx.ICON_ERROR)

    def on_exit(self, event):
        self.Close()
    
    # --- EDITING ---
    def on_cut_destructive(self, event):
        # Check Edit Mode
        is_destructive = self.edit_mode_item.IsChecked()
        
        # 1. Get Selection (Text)
        start_idx, end_idx = self.workspace.GetSelection()
        if start_idx == end_idx: return
        
        self.push_undo_state() # Save state before destructive operation
        
        if not is_destructive:
            # Standard Cut
            self.workspace.Cut()
            self.SetStatusText("Text Cut (Clipboard). Audio unaffected.")
            return

        # 2. Destructive Mode
        if not self.word_alignment:
             wx.MessageBox("No sync data (Word Alignment) available.\nPlease 'Transcribe' or 'Sync' to enable destructive editing.", "Cannot Cut Audio", wx.ICON_ERROR)
             return
             
        # 3. Find Audio Range
        indices = self.word_alignment.get_indices_in_char_range(start_idx, end_idx)
        if not indices:
             self.SetStatusText("Selection does not cover complete words. Cutting text only.")
             self.workspace.Cut()
             return
             
        start_word = self.word_alignment.word_segments[min(indices)]
        end_word = self.word_alignment.word_segments[max(indices)]
        
        start_time = int(start_word.start_ms)
        end_time = int(end_word.end_ms)
        duration_ms = end_time - start_time

        # 4. Perform Cut
        # A. Cut Audio
        if self.active_track_index == -1:
             wx.MessageBox("No active track selected.", "Error", wx.ICON_ERROR)
             return
             
        track = self.track_manager.tracks[self.active_track_index]
        if track.audio_segment:
             # Extract
             cut_audio = track.audio_segment[start_time:end_time]
             
             # Capture word segments being cut
             cut_word_segments = [self.word_alignment.word_segments[idx] for idx in range(min(indices), max(indices) + 1)]
             # Deep copy segments (create new instances) to avoid side effects
             from copy import deepcopy
             AudioClipboard.set(cut_audio, deepcopy(cut_word_segments))
             
             # Remove audio
             before = track.audio_segment[:start_time]
             after = track.audio_segment[end_time:]
             track.audio_segment = before + after
             
             # Update Mix
             self._remix_audio()
             
             # B. Cut Text (Standard)
             self.workspace.Cut()
             
             # C. Update Alignment
             # We remove the words from alignment
             for idx in sorted(indices, reverse=True):
                 self.word_alignment.word_segments.pop(idx)
             
             # D. Shift subsequent audio timing in alignment
             for i in range(min(indices), len(self.word_alignment.word_segments)):
                 seg = self.word_alignment.word_segments[i]
                 seg.start_ms -= duration_ms
                 seg.end_ms -= duration_ms
             
             # E. Re-calculate char offsets for text matches
             self.word_alignment.update_char_offsets()
             
             self.SetStatusText(f"Destructive Cut: Removed {duration_ms}ms of audio.")
             wx.Bell()

    def _apply_text_diff_to_audio(self, original_text, current_text):
        """Apply text differences to audio using word alignment"""
        if self.active_track_index == -1:
            return
            
        self.push_undo_state()
        
        # Get current track
        track = self.track_manager.tracks[self.active_track_index]
        if not track.audio_segment:
            return
            
        # Find removed words by comparing original and current text
        original_words = original_text.split()
        current_words = current_text.split()
        
        # Create a mapping of which original words are still present
        removed_segments = []
        current_idx = 0
        
        for orig_idx, orig_word in enumerate(original_words):
            if current_idx < len(current_words) and current_words[current_idx] == orig_word:
                current_idx += 1
            else:
                # This word was removed
                if orig_idx < len(self.word_alignment.word_segments):
                    removed_segments.append(self.word_alignment.word_segments[orig_idx])
        
        if not removed_segments:
            return  # No words removed
            
        # Sort by start time and remove audio segments
        removed_segments.sort(key=lambda x: x.start_ms)
        total_removed_ms = 0
        
        for segment in removed_segments:
            # Adjust for previously removed audio
            start_ms = int(segment.start_ms - total_removed_ms)
            end_ms = int(segment.end_ms - total_removed_ms)
            duration_ms = end_ms - start_ms
            
            # Remove audio segment
            before = track.audio_segment[:start_ms]
            after = track.audio_segment[end_ms:]
            track.audio_segment = before + after
            
            total_removed_ms += duration_ms
        
        # Update word alignment to match current text
        self.word_alignment.sync_with_text(current_text)
        
        # Shift remaining word timings
        removed_duration = 0
        for segment in removed_segments:
            removed_duration += segment.end_ms - segment.start_ms
            
        # Adjust timings of remaining segments
        for segment in self.word_alignment.word_segments:
            # Find how much audio was removed before this segment
            removed_before = sum(
                (rs.end_ms - rs.start_ms) for rs in removed_segments 
                if rs.start_ms < segment.start_ms
            )
            segment.start_ms -= removed_before
            segment.end_ms -= removed_before
        
        # Remix audio and update status
        self._remix_audio()
        
        if total_removed_ms > 0:
            self.SetStatusText(f"Destructive Edit: Removed {total_removed_ms}ms of audio.")

    def on_paste_destructive(self, event):
        is_destructive = self.edit_mode_item.IsChecked()
        
        if not is_destructive:
            self.workspace.Paste()
            return

        self.push_undo_state()  # Save state before destructive paste

        if not AudioClipboard.has_content():
            self.SetStatusText("Audio Clipboard empty. Pasting text only.")
            self.workspace.Paste()
            return

        # 1. Get Insertion Point (Char Index)
        ins_char_idx = self.workspace.GetInsertionPoint()
        
        # 2. Find Insertion Time and Word Index
        insert_time = 0
        insert_word_idx = 0
        
        if self.word_alignment and self.word_alignment.word_segments:
            for i, seg in enumerate(self.word_alignment.word_segments):
                if ins_char_idx <= seg.char_start:
                    insert_time = int(seg.start_ms)
                    insert_word_idx = i
                    break
            else:
                # Past end of last word
                last_seg = self.word_alignment.word_segments[-1]
                insert_time = int(last_seg.end_ms)
                insert_word_idx = len(self.word_alignment.word_segments)
        else:
            # No alignment yet, use total audio duration
            insert_time = self.track_manager.get_total_duration_ms()
            insert_word_idx = 0

        # 3. Paste Audio
        clip, clip_segments = AudioClipboard.get()
        if self.active_track_index == -1: 
             wx.MessageBox("No active track selected for pasting audio.", "Error", wx.ICON_ERROR)
             return
        
        track = self.track_manager.tracks[self.active_track_index]
        if track.audio_segment:
            before = track.audio_segment[:insert_time]
            after = track.audio_segment[insert_time:]
            track.audio_segment = before + clip + after
            
            self._remix_audio()
            
            # 4. Paste Text
            self.workspace.Paste()
            
            # 5. Update Alignment
            duration_ms = len(clip)
            
            # A. Shift existing words that come after the insertion point
            if self.word_alignment:
                for i in range(insert_word_idx, len(self.word_alignment.word_segments)):
                    seg = self.word_alignment.word_segments[i]
                    seg.start_ms += duration_ms
                    seg.end_ms += duration_ms
                
                # B. Insert new segments from clipboard
                # Shift clipboard segments to start at insert_time
                offset_time = insert_time - clip_segments[0].start_ms if clip_segments else 0
                for seg in clip_segments:
                    seg.start_ms += offset_time
                    seg.end_ms += offset_time
                
                # Insert into list
                for i, seg in enumerate(clip_segments):
                    self.word_alignment.word_segments.insert(insert_word_idx + i, seg)
                
                # C. Re-calculate char offsets for everything
                self.word_alignment.update_char_offsets()
            
            self.SetStatusText(f"Destructive Paste: Added {duration_ms}ms of audio and restored alignment.")
            wx.Bell()

    def on_copy(self, event): self.workspace.Copy()
    def on_paste(self, event): 
        if self.edit_mode_item.IsChecked():
             self.on_paste_destructive(event)
        else:
             self.workspace.Paste()

    def enable_destructive_mode(self):
        """Enable destructive editing mode with proper setup"""
        if not self.word_alignment:
            wx.MessageBox(
                "Destructive editing requires word alignment.\n\n"
                "Please transcribe your audio first using Tools > Transcribe.",
                "Word Alignment Required", wx.ICON_WARNING
            )
            self.edit_mode_item.Check(False)
            return False
            
        if self.active_track_index == -1:
            wx.MessageBox(
                "Please select an active track for destructive editing.",
                "No Active Track", wx.ICON_WARNING
            )
            self.edit_mode_item.Check(False)
            return False
            
        # Sync current text with word alignment
        current_text = self.workspace.GetValue()
        self.word_alignment.sync_with_text(current_text)
        
        self.SetStatusText("Destructive Edit Mode enabled. Text changes will modify audio.")
        return True

    def on_toggle_destructive_mode(self, event):
        """Handle destructive edit mode toggle"""
        if self.edit_mode_item.IsChecked():
            if not self.enable_destructive_mode():
                return  # Mode was disabled due to missing requirements
        else:
            self.SetStatusText("Destructive Edit Mode disabled. Text changes won't affect audio.")

    def on_open_script(self, event):
        with wx.FileDialog(self, "Open Script", wildcard="Script (*.srt;*.xlsx)|*.srt;*.xlsx") as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                try:
                    self.current_script = script_handler.ScriptUtils.load_script(path)
                    self.SetStatusText(f"Loaded script: {os.path.basename(path)} ({len(self.current_script)} lines)")
                    self.log_area.AppendText(f"Loaded script with {len(self.current_script)} lines.\n")
                    wx.Bell()
                except Exception as e:
                    wx.MessageBox(f"Error loading script: {e}", "Error", wx.ICON_ERROR)

    def _get_current_segment(self):
        """Return the currently active AudioSegment (from focused track or first track).
        Returns (segment, track_index) or (None, -1) if no audio loaded.
        """
        # Try focused track first
        focused = self.notebook.GetSelection()
        if focused >= 0 and focused < len(self.track_manager.tracks):
            seg = self.track_manager.tracks[focused].audio_segment
            if seg is not None:
                return seg, focused
        # Fall back to first track with audio
        for i, track in enumerate(self.track_manager.tracks):
            if track.audio_segment is not None:
                return track.audio_segment, i
        return None, -1

    def _update_channel_info(self):
        """Refresh the channel info status item in the Audio menu."""
        seg, idx = self._get_current_segment()
        if seg is None:
            label = "Channel Info: No audio loaded"
        elif seg.channels == 1:
            label = f"Channel Info: Mono ({seg.channels} ch, {seg.sample_width*8}-bit, {seg.frame_rate}Hz)"
        else:
            label = f"Channel Info: Stereo ({seg.channels} ch, {seg.sample_width*8}-bit, {seg.frame_rate}Hz)"
        if hasattr(self, 'channel_info_item'):
            self.channel_info_item.SetItemLabel(label)

    def on_convert_mono(self, event):
        """Convert the current track to mono (mix stereo L+R to single channel)."""
        seg, track_idx = self._get_current_segment()
        if seg is None:
            self.announce("No audio loaded.")
            wx.MessageBox("No audio loaded.", "Cannot Convert", wx.ICON_WARNING)
            return

        if seg.channels == 1:
            self.announce("Already mono.")
            wx.MessageBox("This track is already mono.", "No Change Needed", wx.ICON_INFORMATION)
            return

        self.push_undo_state()
        import numpy as np
        # Convert to numpy: (channels, samples)
        arr = np.array(seg.get_array_of_samples(), dtype=np.float32).reshape(seg.channels, -1) / (2**15)
        # Average all channels to mono
        mono_arr = arr.mean(axis=0)
        mono_seg = AudioSegment(
            data=(mono_arr * (2**15)).astype(np.int16).tobytes(),
            sample_width=seg.sample_width,
            frame_rate=seg.frame_rate,
            channels=1,
        )
        self.track_manager.tracks[track_idx].audio_segment = mono_seg
        self._refresh_track_list()
        self._update_channel_info()
        ch_str = "mono (1 channel)"
        self.announce(f"Converted to {ch_str}.")

    def on_convert_stereo(self, event):
        """Convert the current track to stereo (duplicate mono to both channels)."""
        seg, track_idx = self._get_current_segment()
        if seg is None:
            self.announce("No audio loaded.")
            wx.MessageBox("No audio loaded.", "Cannot Convert", wx.ICON_WARNING)
            return

        if seg.channels == 2:
            self.announce("Already stereo.")
            wx.MessageBox("This track is already stereo.", "No Change Needed", wx.ICON_INFORMATION)
            return

        self.push_undo_state()
        import numpy as np
        # Convert mono to numpy: (1, samples)
        arr = np.array(seg.get_array_of_samples(), dtype=np.float32).reshape(1, -1) / (2**15)
        # Duplicate to stereo: (2, samples)
        stereo_arr = np.vstack([arr, arr])
        stereo_seg = AudioSegment(
            data=(stereo_arr * (2**15)).astype(np.int16).tobytes(),
            sample_width=seg.sample_width,
            frame_rate=seg.frame_rate,
            channels=2,
        )
        self.track_manager.tracks[track_idx].audio_segment = stereo_seg
        self._refresh_track_list()
        self._update_channel_info()
        self.announce("Converted to stereo (2 channels).")

    # ------------------------------------------------------------------
    # ROOM TONE MATCH
    # ------------------------------------------------------------------
    def on_room_tone_match(self, event):
        """Open the Room Tone Match dialog to generate a looped room-tone track."""
        if not self.track_manager.tracks:
            self.announce("No tracks available.")
            wx.MessageBox("No tracks available. Load audio first.", "No Tracks", wx.ICON_WARNING)
            return

        # Build list of track names + durations for the dialog
        track_names = []
        track_durations = []
        for t in self.track_manager.tracks:
            dur_s = len(t.audio_segment) / 1000.0 if t.audio_segment else 0
            label = f"{t.name} ({dur_s:.1f}s)"
            track_names.append(label)
            track_durations.append(dur_s)

        dlg = RoomToneMatchDialog(self, track_names, track_durations)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        # Collect values from dialog
        track_idx = dlg.selected_track
        ref_start_s = dlg.ref_start_s
        ref_end_s = dlg.ref_end_s
        num_loops = dlg.num_loops
        crossfade_ms = dlg.crossfade_ms
        new_track_name = dlg.track_name
        level_db = dlg.level_db
        dlg.Destroy()

        ref_track = self.track_manager.tracks[track_idx]
        ref_seg = ref_track.audio_segment

        if ref_seg is None:
            self.announce("Selected track has no audio.")
            wx.MessageBox("Selected track has no audio.", "Error", wx.ICON_WARNING)
            return

        total_ref_ms = int((ref_end_s - ref_start_s) * 1000)
        if total_ref_ms <= 0:
            self.announce("Invalid reference region.")
            wx.MessageBox("Start time must be before end time.", "Invalid Region", wx.ICON_WARNING)
            return

        # Extract reference region as numpy: (channels, samples)
        import numpy as np
        ref_samples = ref_seg.get_array_of_samples()
        arr = np.array(ref_samples, dtype=np.float32).reshape(ref_seg.channels, -1) / (2**15)

        ref_len = arr.shape[1]
        frame_rate = ref_seg.frame_rate

        # Extract the reference region
        start_sample = int(ref_start_s * frame_rate)
        region_len = int((ref_end_s - ref_start_s) * frame_rate)
        end_sample = start_sample + region_len
        ref_region = arr[:, start_sample:end_sample]

        if ref_region.size == 0:
            self.announce("Reference region is empty.")
            wx.MessageBox(
                "The selected reference region is empty — it may extend past the end of the track.\n\n"
                "Please choose a smaller region or check that the start/end times are within the track's duration.",
                "Empty Reference Region",
                wx.ICON_WARNING,
            )
            return

        # Build the output by looping segments with crossfades
        fade_len = int(crossfade_ms * frame_rate / 1000) if crossfade_ms > 0 else 0

        # Assemble segments list: each is (channel_count, samples)
        # For N loops, we need N copies of ref_region
        # Crossfades are applied between consecutive segments
        parts = []
        for i in range(num_loops):
            parts.append(ref_region.copy())

        # Build output array
        if fade_len == 0 or num_loops == 1:
            # No crossfade — just concatenate
            output = np.hstack(parts)
        else:
            # Crossfade at each segment boundary
            seg_len = parts[0].shape[1]
            # Overlap per boundary = fade_len, each segment contributes fade_len at its end
            # Total output length = num_loops * seg_len - (num_loops-1) * fade_len
            out_len = num_loops * seg_len - (num_loops - 1) * fade_len
            output = np.zeros((ref_region.shape[0], out_len), dtype=np.float32)

            pos = 0
            for i, seg in enumerate(parts):
                if i == 0:
                    # First segment goes in at full volume, no overlap
                    output[:, :seg_len] = seg
                    pos = seg_len
                else:
                    # Crossfade region: fade out previous tail, fade in current head
                    overlap_start = pos - fade_len
                    # Previous segment's tail
                    prev_tail = output[:, overlap_start:pos]
                    # Current segment's head (fade in)
                    curr_head = seg[:, :fade_len] * np.linspace(0, 1, fade_len)
                    # Previous segment's tail (fade out)
                    prev_tail_faded = prev_tail * np.linspace(1, 0, fade_len)
                    output[:, overlap_start:pos] = prev_tail_faded + curr_head
                    # Rest of current segment (after the head that was just blended)
                    output[:, pos:pos + seg_len - fade_len] = seg[:, fade_len:]
                    pos += seg_len - fade_len

        # Apply level (gain)
        if level_db != 0:
            scale = 10 ** (level_db / 20.0)
            output *= scale

        # Convert to mono AudioSegment
        mono_output = output.mean(axis=0)
        mono_int = (np.clip(mono_output, -1.0, 1.0) * (2**15)).astype(np.int16)
        new_seg = AudioSegment(
            data=mono_int.tobytes(),
            sample_width=ref_seg.sample_width,
            frame_rate=frame_rate,
            channels=1,
        )

        # Add as a new AMBIENCE track at the bottom of the list
        self.track_manager.add_track(
            new_track_name,
            audio_segment=new_seg,
            track_type=audio_tracks.TrackType.AMBIENCE,
        )

        self._refresh_track_list()
        self._remix_audio()
        dur_s = len(new_seg) / 1000.0
        self.announce(f"Room tone track '{new_track_name}' created. Duration: {dur_s:.1f} seconds.")
        self.SetStatusText(f"Room Tone track created: {new_track_name} ({dur_s:.1f}s).")

    def on_transcribe(self, event):
        if not self.audio_loaded:
            wx.MessageBox("No audio loaded.", "Error", wx.ICON_ERROR)
            return

        self.log_area.AppendText("Transcription started...\n")
        self.SetStatusText("Transcription in progress...")
        
        self.dlg = wx.ProgressDialog("Transcription", 
                                   "Transcribing audio (this may take a moment)...", 
                                   maximum=100, 
                                   parent=self, 
                                   style=wx.PD_APP_MODAL | wx.PD_ELAPSED_TIME | wx.PD_AUTO_HIDE)
        self.dlg.Pulse()
        
        thread = threading.Thread(target=self._transcribe_worker)
        thread.start()

    def _transcribe_worker(self):
        try:
            # Use factory to get engine, then transcribe with alignment
            # transcribe_with_alignment() works for both FasterWhisper
            # (real word timestamps) and Google SR (estimated timestamps)
            transcriber = transcription.create_transcriber()
            text, alignment = transcriber.transcribe_with_alignment("temp_playback.wav")
            self.word_alignment = alignment
            
            wx.CallAfter(self._on_transcribe_success, text)
        except Exception as e:
            wx.CallAfter(self._on_transcribe_error, str(e))

    def _on_transcribe_success(self, text):
        if self.dlg: self.dlg.Destroy()
        self.current_transcript = text
        self.log_area.AppendText("Transcription Result:\n" + text + "\n")
        self.workspace.SetValue(text)
        self.SetStatusText("Transcription complete.")
        wx.Bell()
        self.workspace.SetFocus()

    def _on_transcribe_error(self, error):
        if self.dlg: self.dlg.Destroy()
        self.log_area.AppendText(f"Transcription Error: {error}\n")
        wx.MessageBox(f"Error: {error}", "Transcription Failed", wx.ICON_ERROR)

    def on_line_placer(self, event):
        if not self.audio_loaded:
            wx.MessageBox("No audio loaded.", "Error", wx.ICON_ERROR)
            return
        if not self.current_script:
            wx.MessageBox("No script loaded. Please Open Script first.", "Error", wx.ICON_ERROR)
            return
        if not self.current_transcript:
            wx.MessageBox("No transcript available. Please Transcribe first.", "Error", wx.ICON_ERROR)
            return

        self.SetStatusText("Running Line Placer...")
        self.dlg = wx.ProgressDialog("Line Placer", 
                                   "Matching script lines to audio...", 
                                   maximum=100, 
                                   parent=self, 
                                   style=wx.PD_APP_MODAL | wx.PD_ELAPSED_TIME | wx.PD_AUTO_HIDE)
        self.dlg.Pulse()
        
        thread = threading.Thread(target=self._line_placer_worker)
        thread.start()

    def _line_placer_worker(self):
        try:
            placer = line_placer.LinePlacerAlgorithm()
            matches = placer.match_lines(self.current_script, self.current_transcript, self.word_alignment)
            
            # Generate output audio
            output_audio, stats = line_placer.AudioSegmentPlacer.create_output_audio(
                self.current_audio, 
                matches, 
                total_duration_ms=max(m.script_time_out_ms for m in matches) + 1000 
            )
            
            # Save to temp
            output_audio.export("temp_placed.wav", format="wav")
            
            report = line_placer.AudioSegmentPlacer.get_placement_report(matches)
            wx.CallAfter(self._on_line_placer_success, report)
        except Exception as e:
            import traceback
            wx.CallAfter(self._on_line_placer_error, str(e) + "\n" + traceback.format_exc())

    def _on_line_placer_success(self, report):
        if self.dlg: self.dlg.Destroy()
        self.load_audio("temp_placed.wav")
        self.log_area.AppendText("\n--- Line Placer Report ---\n" + report + "\n")
        self.SetStatusText("Line Placer complete. Audio updated.")
        wx.Bell()

    def _on_line_placer_error(self, error):
        if self.dlg: self.dlg.Destroy()
        self.SetStatusText("Line Placer failed.")
        self.log_area.AppendText(f"Line Placer Error: {error}\n")
        wx.MessageBox(f"Error: {error}", "Line Placer Failed", wx.ICON_ERROR)

    def _save_original_if_needed(self):
        """Save the current audio as the original 'before' version, if not already saved.

        Called before applying any effect, so we always compare against
        the true original — not the result of a previous effect pass.
        """
        if self._has_original:
            return  # Already saved

        if self.current_samples_float is None:
            return  # Nothing to save

        self._original_samples_float = self.current_samples_float.copy()
        self._original_samples_int16 = self.current_samples_int16.copy()
        self._has_original = True

        # Export to a WAV file for tools that need to read it directly
        orig_audio = self.current_audio
        threading.Thread(
            target=lambda: orig_audio.export("temp_original.wav", format="wav"),
            daemon=True
        ).start()

    def on_before_after_toggle(self, event):
        """Toggle between original ('before') and processed ('after') audio."""
        if not self._has_original:
            self.announce("No original audio saved. Apply an effect first.")
            return

        if self._playing:
            self.stop_audio()

        if self._playback_mode == "processed":
            # Switch to original
            self.current_samples_float = self._original_samples_float
            self.current_samples_int16 = self._original_samples_int16
            self._playback_mode = "original"
            self.ba_toggle_item.Check(True)
            mode_label = "Original (before processing)"
            self.log_area.AppendText(f"Before/After: now playing ORIGINAL.{self._get_playhead_label()}\n")
        else:
            # Switch back to processed — reload from temp_playback.wav
            try:
                seg = AudioSegment.from_file("temp_playback.wav")
                self.current_samples_float = self._get_samples_float(seg)
                self.current_samples_int16 = (self.current_samples_float * 32767).astype(np.int16)
                self._playback_mode = "processed"
                self.ba_toggle_item.Check(False)
                mode_label = "Processed (after processing)"
                self.log_area.AppendText(f"Before/After: now playing PROCESSED.{self._get_playhead_label()}\n")
            except FileNotFoundError:
                # temp_playback.wav gone — fall back to keeping original
                self.current_samples_float = self._original_samples_float
                self.current_samples_int16 = self._original_samples_int16
                self._playback_mode = "original"
                mode_label = "Original (playback file missing)"

        self.announce(f"Playing {mode_label}. Press B to switch back.")
        self.SetStatusText(f"Before/After: {mode_label}  |  Press B to toggle.")

    def _get_samples_float(self, seg):
        """Convert an AudioSegment to a normalised float32 numpy stereo array."""
        samples = np.array(seg.get_array_of_samples()).astype(np.float32)
        max_val = float(1 << (8 * seg.sample_width - 1))
        samples = samples / max_val
        if seg.channels == 1:
            samples = np.column_stack((samples, samples))
        else:
            samples = samples.reshape((-1, seg.channels))
            if seg.channels > 2:
                samples = samples[:, :2]
        return samples

    def _get_playhead_label(self):
        secs = self.playhead_ms / 1000
        mins = int(secs // 60)
        secs_rem = secs % 60
        return f"  [{mins:02d}:{secs_rem:05.2f}]"

    def on_effect_breath(self, e):
        if not self.audio_loaded: return
        self._save_original_if_needed()

        with BreathSmoothingPresetDialog(self) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                vals = dlg.get_values()
                self._breath_params = vals

                self.announce("Running Breath Smoothing...")
                self.dlg = wx.ProgressDialog(
                    "Breath Smoothing",
                    f"Detecting and smoothing breaths...",
                    maximum=100,
                    parent=self,
                    style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
                )
                self.dlg.Pulse()

                thread = threading.Thread(target=self._breath_worker)
                thread.start()

    def _breath_worker(self):
        try:
            vals = getattr(self, '_breath_params', {
                'reduction_db': 6, 'dry_wet': 1.0, 'rms_thresh': 0.02
            })
            breath_smoothing.process_file(
                "temp_playback.wav",
                "temp_processed.wav",
                reduction_db=vals.get('reduction_db', 6),
                rms_thresh=vals.get('rms_thresh', 0.02),
                dry_wet=vals.get('dry_wet', 1.0),
            )
            wx.CallAfter(self._on_breath_success)
        except Exception as e:
            wx.CallAfter(self._on_breath_error, str(e))

    def _on_breath_success(self):
        if self.dlg: self.dlg.Destroy()
        self.push_undo_state()  # Save full state so undo restores pre-effect audio
        self.load_audio("temp_processed.wav")
        # Reset to processed mode after applying an effect
        self._playback_mode = "processed"
        self.ba_toggle_item.Check(False)
        self.ba_toggle_item.Enable(True)  # Enable Before/After toggle now that we have original saved
        preset = getattr(self, '_breath_params', {}).get('preset_name', 'applied')
        self.announce(f"Breath Smoothing ({preset}) complete.  Audio updated. Press B to compare with original.")
        self.log_area.AppendText(f"Breath Smoothing ({preset}) applied successfully.\n")
        wx.Bell()
        self._update_channel_info()

    def _on_breath_error(self, error):
        if self.dlg: self.dlg.Destroy()
        self.announce("Breath Smoothing failed.")
        self.log_area.AppendText(f"Breath Smoothing Error: {error}\n")

    def on_trim_silence(self, event):
        if not self.audio_loaded: return
        self._save_original_if_needed()
        if self.active_track_index == -1:
            wx.MessageBox("No active track selected.", "Error", wx.ICON_ERROR)
            return

        params = {"Threshold (dB)": (-50, -80, -20)}
        with EffectSettingsDialog(self, "Trim Silence Options", params) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                vals = dlg.get_values()
                threshold = vals["Threshold (dB)"]
                
                self.announce("Trimming leading silence...")
                self.push_undo_state()
                
                track = self.track_manager.tracks[self.active_track_index]
                effect = audio_effects.TrimSilence(threshold_db=threshold)
                
                try:
                    new_seg, trim_ms = effect.apply_to_segment(track.audio_segment)
                    if trim_ms > 0:
                        track.audio_segment = new_seg
                        
                        if self.word_alignment:
                            for seg in self.word_alignment.word_segments:
                                seg.start_ms -= trim_ms
                                seg.end_ms -= trim_ms
                            self.word_alignment.update_char_offsets()
                        
                        self._remix_audio()
                        msg = f"Trimmed {trim_ms}ms of silence."
                        self.announce(msg)
                        wx.MessageBox(msg, "Success", wx.ICON_INFORMATION)
                        wx.Bell()
                    else:
                        self.announce("No leading silence detected at this threshold.")
                        wx.MessageBox("No leading silence detected at this threshold.", "Trim Silence", wx.ICON_INFORMATION)
                except Exception as e:
                    wx.MessageBox(f"Error trimming silence: {e}", "Error", wx.ICON_ERROR)

    def on_normalize(self, event):
        """Normalize audio to a target peak level (default -1 dB)."""
        if not self.audio_loaded: return
        self._save_original_if_needed()
        if self.active_track_index == -1:
            wx.MessageBox("No active track selected.", "Error", wx.ICON_ERROR)
            return
        params = {"Target Peak (dB)": (-1, -12, 0)}
        with EffectSettingsDialog(self, "Normalize Options", params) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                target_db = dlg.get_values()["Target Peak (dB)"]
                self.apply_effect(audio_effects.PB_Normalizer(target_db=target_db), f"Normalize ({target_db} dB)")

    def on_denoise(self, event):
        """Apply noise gate to reduce background noise."""
        if not self.audio_loaded: return
        self._save_original_if_needed()
        if self.active_track_index == -1:
            wx.MessageBox("No active track selected.", "Error", wx.ICON_ERROR)
            return
        params = {"Threshold (dB)": (-40, -80, 0)}
        with EffectSettingsDialog(self, "Denoise Options", params) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                threshold_db = dlg.get_values()["Threshold (dB)"]
                self.apply_effect(audio_effects.PB_NoiseGate(threshold_db=threshold_db), f"Denoise ({threshold_db} dB)")

    def on_effect_room(self, e):
        if not self.audio_loaded: return
        self._save_original_if_needed()
        params = {"Sensitivity (0-100)": (50, 0, 100)}
        with EffectSettingsDialog(self, "Room Tone Remover Options", params) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                sens = dlg.get_values()["Sensitivity (0-100)"] / 100.0
                self.apply_effect(audio_effects.RoomToneRemover(sensitivity=sens), "Room Tone Removal")

    def on_effect_compressor(self, e):
        if not self.audio_loaded: return
        self._save_original_if_needed()
        with CompressorPresetDialog(self) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                vals = dlg.get_values()
                eff = audio_effects.Compressor(
                    threshold_db=vals["threshold_db"],
                    ratio=vals["ratio"],
                    attack_ms=vals["attack_ms"],
                    release_ms=vals["release_ms"],
                    makeup_db=vals["makeup_db"],
                )
                self.apply_effect(eff, f"Compression ({dlg.selected_preset if hasattr(dlg, 'selected_preset') else 'Custom'})")

    def on_effect_deesser(self, e):
        if not self.audio_loaded: return
        self._save_original_if_needed()
        params = {"Threshold (dB)": (-20, -60, 0)}
        with EffectSettingsDialog(self, "De-esser Options", params) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                val = dlg.get_values()["Threshold (dB)"]
                self.apply_effect(audio_effects.DeEsser(threshold_db=val), "De-essing")

    def on_effect_equalizer(self, e):
        if not self.audio_loaded: return
        self._save_original_if_needed()
        with EQPresetDialog(self) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                bands = dlg.get_values()
                eff = audio_effects.Equalizer(bands=bands)
                self.apply_effect(eff, f"Equalizer ({dlg.get_preset_name()})")

    def apply_effect(self, effect_obj, name):
        self.announce(f"Applying {name}...")
        self.dlg = wx.ProgressDialog(name, f"Processing audio with {name}...", 
                                   maximum=100, parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
        self.dlg.Pulse()
        
        def worker():
            try:
                track = self.track_manager.tracks[self.active_track_index]
                track.audio_segment = effect_obj.apply(track.audio_segment)
                wx.CallAfter(self._on_effect_success, name)
            except Exception as e:
                wx.CallAfter(self._on_effect_error, name, str(e))

        threading.Thread(target=worker).start()

    def _on_effect_success(self, name):
        if self.dlg: self.dlg.Destroy()
        self.push_undo_state()  # Must be on main thread — push_undo_state calls _update_undo_menu_state
        self._remix_audio()
        msg = f"{name} applied successfully."
        self.announce(msg)
        wx.MessageBox(msg, "Success", wx.ICON_INFORMATION)
        wx.Bell()

    def _on_effect_error(self, name, error):
        if self.dlg: self.dlg.Destroy()
        self.announce(f"{name} failed.")
        self.log_area.AppendText(f"{name} Error: {error}\n")
        wx.MessageBox(f"Error applying {name}: {error}", "Effect Error", wx.ICON_ERROR)

    def set_monitor_volume(self, volume):
        """Set monitor volume from director controls"""
        self.monitor_volume = volume
        self.SetStatusText(f"Director set volume: {int(volume*100)}%")

    # --- RECORDING ---
    def on_toggle_record(self, event):
        if not self.is_recording:
            # Show recording dialog with level monitor
            dlg = RecordingDialog(self, getattr(self, 'input_device_id', None))
            if dlg.ShowModal() == wx.ID_OK:
                try:
                    self.recorder.start()
                    self.is_recording = True
                    self.SetStatusText("Recording... Press Ctrl+R to stop.")
                except Exception as e:
                    wx.MessageBox(str(e), "Recording Error", wx.ICON_ERROR)
            dlg.Destroy()
        else:
            seg = self.recorder.stop()
            self.is_recording = False
            if seg:
                self.on_add_track(name="Recording", audio=seg)
                self.SetStatusText("Recording finished.")
            else:
                self.SetStatusText("Recording failed or was empty.")

    def update_record_time(self, seconds):
        wx.CallAfter(self.SetStatusText, f"Recording: {seconds:.1f}s")

    def on_stop(self, e):
        sd.stop()
        if self.is_recording:
            self.on_toggle_record(None)
        self.SetStatusText("Playback stopped.")

    def on_play_pause(self, e):
        print(f"DEBUG: on_play_pause called. audio_loaded={self.audio_loaded}")
        if not self.audio_loaded:
            self.announce("No audio loaded.")
            return

        if self._playing:
            self.stop_audio()
            self.announce("Paused.")
        else:
            mode_suffix = " (Original)" if self._playback_mode == "original" else ""
            self.start_audio()
            self.announce(f"Playing{mode_suffix} from {self.playhead_ms/1000:.1f} seconds. Press B to toggle.")
            pos = f"{self.playhead_ms/1000:.1f}s"
            self.SetStatusText(f"Playing{mode_suffix}  |  Pos: {pos}  |  Press B to toggle.")

    def start_audio(self):
        if self._playing: return
        
        start_ms = self.playhead_ms
        start_idx = int((start_ms / 1000) * self.sample_rate)
        
        if self.current_samples_int16 is None or len(self.current_samples_int16) == 0:
            self.announce("Playback buffer is empty.")
            return

        if start_idx >= len(self.current_samples_int16):
            self.playhead_ms = 0
            start_idx = 0

        chunk_f32 = self.current_samples_float[start_idx:]
        chunk_i16 = self.current_samples_int16[start_idx:]
        
        peak = np.max(np.abs(chunk_f32))
        print(f"DEBUG: Starting Playback. Engine: {self.audio_engine}, Rate: {self.sample_rate}, Offset: {start_ms}ms, Peak: {peak:.3f}")
        
        if peak < 0.001:
            self.announce("Warning: Starting playback of silence.")

        if self.audio_engine == "sounddevice":
            try:
                # Apply director volume control
                volume_adjusted = chunk_f32 * self.monitor_volume
                sd.play(volume_adjusted, self.sample_rate, 
                        device=getattr(self, 'output_device_id', None))
                self._playing = True
            except Exception as ex:
                print(f"DEBUG: SoundDevice failed: {ex}")
                self.announce(f"SoundDevice failed. Falling back to PyAudio.")
                self.audio_engine = "pyaudio"
                self.start_audio()
        elif self.audio_engine == "custom_asio":
            try:
                if self.asio_manager and self.asio_manager.is_active():
                    # Custom ASIO playback with ultra-low latency
                    volume_adjusted = chunk_f32 * self.monitor_volume
                    
                    def asio_callback(indata, frames):
                        # Return the audio data for playback
                        if len(volume_adjusted) >= frames:
                            return volume_adjusted[:frames]
                        else:
                            # Pad with zeros if not enough data
                            padded = np.zeros((frames, 2), dtype=np.float32)
                            padded[:len(volume_adjusted)] = volume_adjusted
                            return padded
                    
                    self.asio_manager.start_audio(asio_callback)
                    self._playing = True
                else:
                    raise Exception("Custom ASIO not initialized")
            except Exception as ex:
                print(f"DEBUG: Custom ASIO failed: {ex}")
                self.announce(f"Custom ASIO failed. Falling back to SoundDevice.")
                self.audio_engine = "sounddevice"
                self.start_audio() 
        else:
            try:
                self.pa_stream = self.pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=2,
                    rate=self.sample_rate,
                    output=True,
                    output_device_index=getattr(self, 'output_device_id', None)
                )
                self._playing = True
                threading.Thread(target=self._pyaudio_worker, args=(chunk_i16,), daemon=True).start()
            except Exception as ex:
                print(f"DEBUG: PyAudio failed: {ex}")
                self.announce(f"PyAudio failed: {ex}")
                wx.MessageBox(f"Audio Engines failing: {ex}", "Audio Error", wx.ICON_ERROR)

    def _pyaudio_worker(self, data):
        print(f"DEBUG: PyAudio Worker started. Data size: {len(data)} samples.")
        try:
            chunk_size = 1024
            written = 0
            for i in range(0, len(data), chunk_size):
                if not self._playing: break
                chunk = data[i:i+chunk_size].tobytes()
                self.pa_stream.write(chunk)
                written += chunk_size
            
            print(f"DEBUG: PyAudio Worker finished. Samples written: {written}")
            if self._playing:
                self._playing = False
                wx.CallAfter(self.announce, "Playback finished.")
        except Exception as e:
            print(f"DEBUG: PyAudio Worker crashed: {e}")
        finally:
            if hasattr(self, 'pa_stream'):
                try: self.pa_stream.stop_stream()
                except: pass
                try: self.pa_stream.close()
                except: pass

    def stop_audio(self):
        self._playing = False
        if self.audio_engine == "sounddevice":
            sd.stop()
        elif self.audio_engine == "custom_asio":
            if self.asio_manager:
                self.asio_manager.stop_audio()
        # PyAudio worker will close itself when self._playing is False

    def on_stop(self, e):
        self.stop_audio()
        if self.is_recording:
            self.on_toggle_record(None)
        self.announce("Playback stopped.")

    def on_audio_setup(self, event):
        # Advanced Audio Setup Dialog with Level Monitoring
        dlg = wx.Dialog(self, title="Advanced Audio Setup", size=(500, 650))
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Engine Choice
        vbox.Add(wx.StaticText(dlg, label="Audio Engine:"), 0, wx.ALL, 5)
        engine_cb = wx.ComboBox(dlg, choices=["SoundDevice (WASAPI/MME)", "PyAudio (Compatibility)", "Custom ASIO (Ultra-Low Latency)"], style=wx.CB_READONLY)
        engine_cb.SetSelection(0 if self.audio_engine == "sounddevice" else 1)
        vbox.Add(engine_cb, 0, wx.EXPAND | wx.ALL, 5)
        
        # Output Device
        vbox.Add(wx.StaticText(dlg, label="Output Device (Playback):"), 0, wx.ALL, 5)
        output_cb = wx.ComboBox(dlg, style=wx.CB_READONLY)
        
        # Input Device
        vbox.Add(wx.StaticText(dlg, label="Input Device (Microphone):"), 0, wx.ALL, 5)
        input_cb = wx.ComboBox(dlg, style=wx.CB_READONLY)
        
        # Recording Level Monitor
        level_box = wx.StaticBox(dlg, label="Recording Level Monitor")
        level_sizer = wx.StaticBoxSizer(level_box, wx.VERTICAL)
        
        level_gauge = wx.Gauge(dlg, range=100, style=wx.GA_HORIZONTAL)
        level_sizer.Add(level_gauge, 0, wx.EXPAND | wx.ALL, 5)
        
        level_text = wx.StaticText(dlg, label="Level: -∞ dB")
        level_sizer.Add(level_text, 0, wx.ALL, 5)
        
        monitor_btn = wx.Button(dlg, label="Start Level Monitor")
        level_sizer.Add(monitor_btn, 0, wx.ALL, 5)
        
        vbox.Add(level_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Level monitoring state
        monitoring = [False]  # Use list for closure
        monitor_stream = [None]
        
        def populate_devices():
            try:
                engine_sel = engine_cb.GetSelection()
                
                if engine_sel == 0:  # SoundDevice
                    devices = sd.query_devices()
                    
                    # Output devices
                    output_choices = []
                    input_choices = []
                    
                    for i, d in enumerate(devices):
                        if d['max_output_channels'] > 0:
                            output_choices.append(f"{i}: {d['name']}")
                        if d['max_input_channels'] > 0:
                            input_choices.append(f"{i}: {d['name']}")
                    
                    output_cb.SetItems(output_choices)
                    input_cb.SetItems(input_choices)
                    
                elif engine_sel == 1:  # PyAudio
                    output_choices = []
                    input_choices = []
                    try:
                        for i in range(self.pyaudio_instance.get_device_count()):
                            info = self.pyaudio_instance.get_device_info_by_index(i)
                            if info['maxOutputChannels'] > 0:
                                output_choices.append(f"{i}: {info['name']}")
                            if info['maxInputChannels'] > 0:
                                input_choices.append(f"{i}: {info['name']}")
                    except:
                        output_choices = ["PyAudio error - check installation"]
                        input_choices = ["PyAudio error - check installation"]
                        
                    output_cb.SetItems(output_choices)
                    input_cb.SetItems(input_choices)
                    
                else:  # Custom ASIO
                    if self.asio_manager:
                        try:
                            import sounddevice as sd
                            devices = sd.query_devices()
                            
                            # Show all devices for ASIO selection
                            output_choices = []
                            input_choices = []
                            
                            for i, d in enumerate(devices):
                                if d['max_output_channels'] > 0:
                                    output_choices.append(f"{i}: {d['name']} (ASIO)")
                                if d['max_input_channels'] > 0:
                                    input_choices.append(f"{i}: {d['name']} (ASIO)")
                            
                            if not output_choices:
                                output_choices = ["No output devices found"]
                            if not input_choices:
                                input_choices = ["No input devices found"]
                                
                            output_cb.SetItems(output_choices)
                            input_cb.SetItems(input_choices)
                        except:
                            output_cb.SetItems(["Custom ASIO device enumeration failed"])
                            input_cb.SetItems(["Custom ASIO device enumeration failed"])
                    else:
                        output_cb.SetItems(["Custom ASIO not available - check installation"])
                        input_cb.SetItems(["Custom ASIO not available - check installation"])
                    
                if output_cb.GetCount() > 0:
                    output_cb.SetSelection(0)
                if input_cb.GetCount() > 0:
                    input_cb.SetSelection(0)
                    
            except Exception as e:
                wx.MessageBox(f"Error enumerating devices: {e}", "Error", wx.ICON_ERROR)
            
        def toggle_level_monitor(e):
            if not monitoring[0]:
                # Start monitoring
                sel = input_cb.GetStringSelection()
                if not sel or "error" in sel.lower() or "requires" in sel.lower():
                    wx.MessageBox("Please select a valid input device first.", "Error", wx.ICON_ERROR)
                    return
                    
                try:
                    input_id = int(sel.split(":")[0])
                    
                    def audio_callback(indata, frames, time, status):
                        try:
                            if status:
                                print(f"Audio callback status: {status}")
                            
                            # Calculate RMS level
                            rms = np.sqrt(np.mean(indata**2))
                            db_level = 20 * np.log10(max(rms, 1e-10))  # Avoid log(0)
                            
                            # Convert to 0-100 scale (-60dB to 0dB)
                            level_percent = max(0, min(100, (db_level + 60) / 60 * 100))
                            
                            wx.CallAfter(update_level_display, level_percent, db_level)
                        except Exception as ex:
                            print(f"Callback error: {ex}")
                    
                    monitor_stream[0] = sd.InputStream(
                        device=input_id,
                        channels=1,
                        samplerate=44100,
                        callback=audio_callback,
                        blocksize=1024
                    )
                    monitor_stream[0].start()
                    
                    monitoring[0] = True
                    monitor_btn.SetLabel("Stop Level Monitor")
                    
                except Exception as ex:
                    wx.MessageBox(f"Failed to start level monitor: {ex}", "Error", wx.ICON_ERROR)
            else:
                # Stop monitoring
                if monitor_stream[0]:
                    try:
                        monitor_stream[0].stop()
                        monitor_stream[0].close()
                    except:
                        pass
                    monitor_stream[0] = None
                    
                monitoring[0] = False
                monitor_btn.SetLabel("Start Level Monitor")
                level_gauge.SetValue(0)
                level_text.SetLabel("Level: -∞ dB")
        
        def update_level_display(level_percent, db_level):
            try:
                level_gauge.SetValue(int(level_percent))
                level_text.SetLabel(f"Level: {db_level:.1f} dB")
            except:
                pass
        
        populate_devices()
        engine_cb.Bind(wx.EVT_COMBOBOX, lambda e: populate_devices())
        monitor_btn.Bind(wx.EVT_BUTTON, toggle_level_monitor)
        
        vbox.Add(output_cb, 0, wx.EXPAND | wx.ALL, 5)
        vbox.Add(input_cb, 0, wx.EXPAND | wx.ALL, 5)
        
        # Tools
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        test_out_btn = wx.Button(dlg, label="Test Output")
        test_in_btn = wx.Button(dlg, label="Test Input")
        btn_box.Add(test_out_btn, 1, wx.ALL, 5)
        btn_box.Add(test_in_btn, 1, wx.ALL, 5)
        vbox.Add(btn_box, 0, wx.EXPAND)
        
        def test_output(e):
            try:
                self._play_test_tone()
            except Exception as ex:
                wx.MessageBox(f"Output test failed: {ex}", "Error", wx.ICON_ERROR)
            
        def test_input(e):
            sel = input_cb.GetStringSelection()
            if not sel or "error" in sel.lower(): 
                wx.MessageBox("Please select a valid input device.", "Error", wx.ICON_ERROR)
                return
                
            try:
                input_id = int(sel.split(":")[0])
                
                self.SetStatusText("Recording 2-second test...")
                test_data = sd.rec(int(2 * 44100), samplerate=44100, channels=1, device=input_id)
                sd.wait()
                
                # Play back the recording
                sd.play(test_data, 44100)
                self.SetStatusText("Playing back microphone test...")
            except Exception as ex:
                wx.MessageBox(f"Microphone test failed: {ex}", "Error", wx.ICON_ERROR)
                
        test_out_btn.Bind(wx.EVT_BUTTON, test_output)
        test_in_btn.Bind(wx.EVT_BUTTON, test_input)
        
        vbox.AddStretchSpacer()
        ok_btn = wx.Button(dlg, wx.ID_OK, label="Apply Settings")
        vbox.Add(ok_btn, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        dlg.SetSizer(vbox)
        
        # Cleanup on dialog close
        def on_close(event):
            if monitor_stream[0]:
                try:
                    monitor_stream[0].stop()
                    monitor_stream[0].close()
                except:
                    pass
            event.Skip()
            
        dlg.Bind(wx.EVT_CLOSE, on_close)
        
        try:
            if dlg.ShowModal() == wx.ID_OK:
                # Stop monitoring before applying settings
                if monitor_stream[0]:
                    try:
                        monitor_stream[0].stop()
                        monitor_stream[0].close()
                    except:
                        pass
                    
                engine_sel = engine_cb.GetSelection()
                if engine_sel == 0:
                    self.audio_engine = "sounddevice"
                elif engine_sel == 1:
                    self.audio_engine = "pyaudio"
                else:
                    self.audio_engine = "custom_asio"
                    # Initialize custom ASIO if selected
                    if self.asio_manager:
                        # Get selected devices
                        output_sel = output_cb.GetStringSelection()
                        input_sel = input_cb.GetStringSelection()
                        
                        output_device_id = None
                        input_device_id = None
                        
                        if output_sel and "not found" not in output_sel.lower() and "failed" not in output_sel.lower():
                            try:
                                output_device_id = int(output_sel.split(":")[0])
                            except:
                                pass
                                
                        if input_sel and "not found" not in input_sel.lower() and "failed" not in input_sel.lower():
                            try:
                                input_device_id = int(input_sel.split(":")[0])
                            except:
                                pass
                        
                        buffer_size = 128  # Ultra-low latency
                        if self.asio_manager.initialize_asio(44100, buffer_size, input_device_id, output_device_id):
                            latency = self.asio_manager.get_latency_ms()
                            wx.MessageBox(
                                f"Custom ASIO initialized successfully!\n\n"
                                f"Input: {input_sel.split(':')[1] if input_sel else 'Default'}\n"
                                f"Output: {output_sel.split(':')[1] if output_sel else 'Default'}\n"
                                f"Latency: {latency:.1f}ms\n"
                                f"Buffer size: {buffer_size} samples\n\n"
                                f"This bypasses WASAPI for minimal latency.",
                                "ASIO Ready", wx.ICON_INFORMATION
                            )
                        else:
                            wx.MessageBox("Failed to initialize Custom ASIO.", "Error", wx.ICON_ERROR)
                            self.audio_engine = "sounddevice"  # Fallback
                
                # Save output device
                output_sel = output_cb.GetStringSelection()
                if output_sel and "error" not in output_sel.lower() and "requires" not in output_sel.lower():
                    try:
                        self.output_device_id = int(output_sel.split(":")[0])
                    except:
                        pass
                        
                # Save input device
                input_sel = input_cb.GetStringSelection()
                if input_sel and "error" not in input_sel.lower() and "requires" not in input_sel.lower():
                    try:
                        self.input_device_id = int(input_sel.split(":")[0])
                        # Update recorder with new input device
                        if hasattr(self, 'recorder'):
                            self.recorder.input_device_id = self.input_device_id
                    except:
                        pass
                        
                self.SetStatusText(f"Audio configured: {self.audio_engine.upper()}")
                
        except Exception as e:
            wx.MessageBox(f"Audio setup error: {e}", "Error", wx.ICON_ERROR)
        finally:
            dlg.Destroy()

    def on_reset_audio(self, event):
        try:
            sd.stop()
            sd.query_devices()
            self.announce("Audio engine reset. Please try playing again.")
        except Exception as e:
            self.announce(f"Reset failed: {e}")

    def on_check_integrity(self, event):
        path = os.path.abspath("temp_playback.wav")
        if os.path.exists(path):
            self.announce("Opening mixed audio in system player...")
            webbrowser.open(f"file:///{path}")
        else:
            wx.MessageBox("No temporary mixed audio found. Try loading a track first.", "Error", wx.ICON_ERROR)

    def _play_test_tone(self):
        fs = 44100
        duration = 1.0 # seconds
        f = 440.0 # Hz
        t = np.arange(fs * duration)
        # Create Stereo Tone
        left = np.sin(2 * np.pi * t * f / fs).astype(np.float32)
        right = np.sin(2 * np.pi * t * (f * 1.5) / fs).astype(np.float32)
        samples_f32 = np.column_stack((left, right))
        
        try:
            self.announce(f"Playing stereo test tone ({self.audio_engine})...")
            if self.audio_engine == "sounddevice":
                sd.play(samples_f32, fs, device=getattr(self, 'output_device_id', None))
            else:
                # PyAudio Test
                samples_i16 = (samples_f32 * 32767).astype(np.int16)
                stream = self.pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=2,
                    rate=fs,
                    output=True,
                    output_device_index=getattr(self, 'output_device_id', None)
                )
                stream.write(samples_i16.tobytes())
                stream.stop_stream()
                stream.close()
        except Exception as e:
            wx.MessageBox(f"Test tone failed: {e}", "Error", wx.ICON_ERROR)

    def on_undo(self, e):
        if not self.undo_stack:
            self.announce("Nothing to undo.")
            self.SetStatusText("Nothing to undo.")
            return

        # Push current state to redo
        from copy import deepcopy
        current_state = {
            "tracks_audio": [deepcopy(t.audio_segment) for t in self.track_manager.tracks],
            "alignment": deepcopy(self.word_alignment),
            "transcript": self.workspace.GetValue()
        }
        self.redo_stack.append(current_state)

        # Pop and restore
        state = self.undo_stack.pop()

        # Restore tracks
        for i, audio in enumerate(state["tracks_audio"]):
            if i < len(self.track_manager.tracks):
                self.track_manager.tracks[i].audio_segment = audio

        self.word_alignment = state["alignment"]
        self.workspace.SetValue(state["transcript"])

        self._remix_audio()
        self._refresh_track_list()
        self._update_undo_menu_state()
        undo_count = len(self.undo_stack)
        msg = f"Undone. {undo_count} undo steps remaining."
        self.announce(msg)
        self.SetStatusText(msg)

    def on_redo(self, e):
        if not self.redo_stack:
            self.announce("Nothing to redo.")
            self.SetStatusText("Nothing to redo.")
            return

        # Push current state back to undo
        from copy import deepcopy
        current_state = {
            "tracks_audio": [deepcopy(t.audio_segment) for t in self.track_manager.tracks],
            "alignment": deepcopy(self.word_alignment),
            "transcript": self.workspace.GetValue()
        }
        self.undo_stack.append(current_state)

        # Pop and restore from redo
        state = self.redo_stack.pop()

        for i, audio in enumerate(state["tracks_audio"]):
            if i < len(self.track_manager.tracks):
                self.track_manager.tracks[i].audio_segment = audio

        self.word_alignment = state["alignment"]
        self.workspace.SetValue(state["transcript"])

        self._remix_audio()
        self._refresh_track_list()
        self._update_undo_menu_state()
        redo_count = len(self.redo_stack)
        msg = f"Redone. {redo_count} redo steps remaining."
        self.announce(msg)
        self.SetStatusText(msg)

    def on_vol_up(self, e):
        idx = self.tracks_list.GetSelection()
        if idx != wx.NOT_FOUND:
            self.track_manager.tracks[idx].volume_db += 2.0
            self._remix_audio()
            self.SetStatusText(f"Volume Up: {self.track_manager.tracks[idx].volume_db}dB")

    def on_vol_down(self, e): 
        idx = self.tracks_list.GetSelection()
        if idx != wx.NOT_FOUND:
            self.track_manager.tracks[idx].volume_db -= 2.0
            self._remix_audio()
            self.SetStatusText(f"Volume Down: {self.track_manager.tracks[idx].volume_db}dB")

    # --- PROJECT MANAGEMENT ---
    def on_save_project(self, event):
        with wx.FileDialog(self, "Save Project", defaultDir=self.default_project_dir, 
                           wildcard="SpeechCraft Project (*.scproj)|*.scproj", 
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                # Ensure .scproj extension
                if not path.endswith(".scproj"): path += ".scproj"
                
                success, msg = project_handler.ProjectHandler.save_project(
                    path, self.track_manager, self.workspace.GetValue(), self.word_alignment, self.current_script)
                if success:
                    self.SetStatusText(f"Project saved: {os.path.basename(path)}")
                    wx.MessageBox(msg, "Success", wx.ICON_INFORMATION)
                else:
                    wx.MessageBox(msg, "Error", wx.ICON_ERROR)

    def on_load_project(self, event):
         with wx.FileDialog(self, "Load Project", defaultDir=self.default_project_dir, 
                           wildcard="SpeechCraft Project (*.scproj)|*.scproj", 
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                
                # Unload audio to release locks
                try:
                    import pygame
                    if pygame.mixer.get_init():
                        pygame.mixer.music.unload()
                except ImportError:
                    pass  # pygame not available
                
                success, data = project_handler.ProjectHandler.load_project(path, self.track_manager)
                if success:
                    self.workspace.SetValue(data["transcript"])
                    self.word_alignment = data["alignment"]
                    self.current_script = data["script"]
                    
                    self._refresh_track_list()
                    self._remix_audio()
                    
                    self.SetStatusText(f"Loaded project: {os.path.basename(path)}")
                    self.log_area.AppendText(f"Project loaded: {path}\n")
                    wx.Bell()
                else:
                    wx.MessageBox(data, "Error", wx.ICON_ERROR)

    def on_export_audio(self, event):
        wildcard = "WAV Audio (*.wav)|*.wav|MP3 Audio (*.mp3)|*.mp3"
        with wx.FileDialog(self, "Export Audio", defaultDir=os.path.expanduser("~/Music"), 
                           wildcard=wildcard, 
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                fmt = "mp3" if path.lower().endswith(".mp3") else "wav"
                
                success, msg = project_handler.ProjectHandler.export_mixdown(path, self.track_manager, fmt)
                if success:
                     self.SetStatusText(f"Exported to {path}")
                     wx.MessageBox(msg, "Success", wx.ICON_INFORMATION)
                else:
                     wx.MessageBox(msg, "Error", wx.ICON_ERROR)

    def on_export_presets(self, event):
        """Export custom presets to a JSON file."""
        with wx.FileDialog(
            self,
            "Export Presets",
            defaultDir=os.path.expanduser("~/Documents"),
            wildcard="SpeechCraft Presets (*.scpresets)|*.scpresets",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                # Ensure extension
                if not path.lower().endswith(".scpresets"):
                    path += ".scpresets"

                eq, comp, breath = preset_manager.load_custom_presets()
                if not eq and not comp and not breath:
                    wx.MessageBox(
                        "No custom presets to export. Save some presets first using the effect dialogs.",
                        "Nothing to Export",
                        wx.ICON_INFORMATION,
                    )
                    return

                if preset_manager.export_presets_to_file(path, eq, comp, breath):
                    self.announce(f"Exported {len(eq) + len(comp) + len(breath)} presets to {path}")
                    wx.MessageBox(
                        f"Exported presets to:\n{path}",
                        "Export Successful",
                        wx.ICON_INFORMATION,
                    )

    def on_import_presets(self, event):
        """Import presets from a JSON file."""
        with wx.FileDialog(
            self,
            "Import Presets",
            defaultDir=os.path.expanduser("~/Documents"),
            wildcard="SpeechCraft Presets (*.scpresets)|*.scpresets|All Files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as fd:
            if fd.ShowModal() == wx.ID_OK:
                path = fd.GetPath()
                result = preset_manager.import_presets_from_file(path)
                if result is not None:
                    eq, comp, breath = result
                    total = len(eq) + len(comp) + len(breath)
                    self.announce(f"Imported {total} presets from {path}")
                    wx.MessageBox(
                        f"Imported presets from:\n{path}\n\n"
                        f"EQ presets: {len(eq)}\n"
                        f"Compressor presets: {len(comp)}\n"
                        f"Breath smoothing presets: {len(breath)}\n\n"
                        "Restart the app or open an effect dialog to see the new presets.",
                        "Import Successful",
                        wx.ICON_INFORMATION,
                    )

    def on_batch_process(self, event):
        """Open the batch processing dialog."""
        dlg = BatchProcessDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def on_auto_ducker(self, event):
        # Interactive Ducker
        if not self.audio_loaded: return
        self._save_original_if_needed()
        tracks = self.track_manager.tracks
        choices = [t.name for t in tracks]
        if not choices:
             wx.MessageBox("No tracks available.", "Error", wx.ICON_ERROR)
             return
             
        dlg = wx.SingleChoiceDialog(self, 
            "Select the Voice (Leader) Track.\nAll other tracks will be ducked (volume lowered) when this track has audio.", 
            "Auto-Ducker", choices)
            
        if dlg.ShowModal() == wx.ID_OK:
            self.push_undo_state()  # Save state before destructive ducking
            selection_idx = dlg.GetSelection()
            voice_track = tracks[selection_idx]
            
            # 1. Update Track Type for Auto-Ducker Logic
            # The logic in audio_tracks.py relies on TrackType.VOICE
            # Unset VOICE from others to be safe
            for t in tracks:
                if t.track_type == audio_tracks.TrackType.VOICE:
                     t.track_type = audio_tracks.TrackType.MUSIC # Default fallback
            
            voice_track.track_type = audio_tracks.TrackType.VOICE
            
            # 2. Run Ducker
            msg = self.track_manager.apply_auto_ducking(reduction_db=-12.0)
            
            self._remix_audio()
            self.SetStatusText(msg)
            wx.MessageBox(msg, "Auto-Ducker Result", wx.ICON_INFORMATION)
        
        dlg.Destroy()

def main(splash=None):
    """Launch the main SpeechCraft window.

    Parameters
    ----------
    splash : Splash | None
        Optional Splash window shown during startup. If provided, we'll
        update each milestone as the main frame initialises and close
        the splash just before MainLoop() runs. If None, no splash was
        available (e.g. running headless) and we proceed directly.
    """
    app = wx.App()

    if splash is not None:
        # Mark the FFmpeg step. setup_ffmpeg() already ran at import
        # time (so AudioSegment was configured), but we re-run to get
        # a message string for the splash. The second call is cheap
        # because AudioSegment.<field> assignments are idempotent.
        try:
            ffmpeg_ok, ffmpeg_msg = setup_ffmpeg()
            splash.update(
                "Checking FFmpeg",
                ffmpeg_msg,
            )
        except Exception:
            splash.update("Checking FFmpeg", "Skipped")

        # Piper TTS check.
        try:
            from piper_tts_engine import PiperTTSEngine  # noqa: F401
            piper_path = _find_piper()
            if piper_path:
                splash.update(
                    "Checking Piper TTS",
                    f"Found Piper at {piper_path}",
                )
            else:
                splash.update(
                    "Checking Piper TTS",
                    "Piper.exe not found - TTS still works via Edge",
                )
        except Exception:
            splash.update("Checking Piper TTS", "Skipped")

        splash.update("Loading effects presets", "Built-in presets ready")
        splash.update("Loading recent projects", "Workspace ready")

    def _progress(step_name: str, status: str = "") -> None:
        """Called from SpeechCraftFrame.__init__ to update the splash.

        Lifecycle: this callback fires from inside the frame
        constructor, so it must be safe against a None splash. When
        splash is None the callback is a no-op so production code that
        built without a splash doesn't need to special-case it.
        """
        if splash is not None:
            splash.update(step_name, status)

    _progress("Preparing workspace", "Building the main window…")

    # Build the frame under the splash so the user sees progress
    # instead of an apparent freeze.
    frame = SpeechCraftFrame(progress=_progress)

    if splash is not None:
        # Frame is built. Close the splash before MainLoop so the user
        # sees the splash go away at the same instant the main
        # window appears — no flash of empty screen between.
        splash.close()

    frame.Show()
    # Force a refresh before MainLoop so the window paints at least
    # one frame even on machines where MainLoop is slow to enter.
    frame.Update()
    app.MainLoop()
    return 0


def _find_piper() -> str | None:
    """Return path to piper.exe or None.

    Mirrors the lookup in piper_tts_engine for the splash.
    """
    import shutil
    piper_path = shutil.which("piper")
    if piper_path:
        return piper_path
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, "piper.exe")
    return candidate if os.path.exists(candidate) else None

        
    def get_session_report(self):
        """Get the session report"""
        return getattr(self, 'session_report', "No session data available.")
        
    def Destroy(self):
        """Clean up voice actor monitor, network server and braille when dialog is destroyed"""
        if self.voice_actor_monitor:
            self.voice_actor_monitor.Destroy()
        if self.network_server:
            self.network_server.stop_server()
        if hasattr(self, 'braille') and self.braille:
            self.braille.clear()
        super().Destroy()

if __name__ == "__main__":
    main()