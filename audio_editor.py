import wx
import os
import threading
import sounddevice as sd
from pathlib import Path
from pydub import AudioSegment
from pydub.utils import which
import numpy as np
import webbrowser
import pyttsx3 # For accessible announcements
import pyaudio
import struct
import audio_tracks  # Moved out of try-except to ensure visibility
import project_handler # Moved out to ensure visibility
import config  # For EQ and compressor presets
import preset_manager  # For custom preset save/load/import/export
import batch_processor  # For batch processing multiple files

# Configure FFmpeg path - simplified startup check
def setup_ffmpeg():
    """Setup FFmpeg if available"""
    import shutil
    
    # Check local directory first
    local_ffmpeg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        AudioSegment.converter = local_ffmpeg
        AudioSegment.ffmpeg = local_ffmpeg
        AudioSegment.ffprobe = local_ffmpeg
        print(f"Using local FFmpeg: {local_ffmpeg}")
        return True
    
    # Check system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        AudioSegment.converter = system_ffmpeg
        AudioSegment.ffmpeg = system_ffmpeg
        AudioSegment.ffprobe = shutil.which("ffprobe") or system_ffmpeg
        print(f"Using system FFmpeg: {system_ffmpeg}")
        return True
    
    # FFmpeg not found - will be handled by dialog later
    return False

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

class AudioClipboard:
    """Stores cut audio segments and their associated word segments for pasting"""
    _segment = None
    _word_segments = []
    
    @classmethod
    def set(cls, segment, word_segments=None):
        cls._segment = segment
        cls._word_segments = word_segments or []
        
    @classmethod
    def get(cls):
        return cls._segment, cls._word_segments
    
    @classmethod
    def has_content(cls):
        return cls._segment is not None

class EffectSettingsDialog(wx.Dialog):
    def __init__(self, parent, title, params):
        # params: dict of {label: (value, min, max)} or {label: value}
        super().__init__(parent, title=title)
        self.params = params
        self.controls = {}
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        fgs = wx.FlexGridSizer(len(params), 2, 10, 10)
        
        for label, val in params.items():
            st = wx.StaticText(self, label=label)
            if isinstance(val, tuple):
                ctrl = wx.Slider(self, value=int(val[0]), minValue=int(val[1]), maxValue=int(val[2]), style=wx.SL_HORIZONTAL | wx.SL_LABELS)
            else:
                ctrl = wx.TextCtrl(self, value=str(val))
            
            fgs.Add(st)
            fgs.Add(ctrl, 1, wx.EXPAND)
            self.controls[label] = ctrl
            
        sizer.Add(fgs, 1, wx.ALL | wx.EXPAND, 15)
        
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        self.SetSizerAndFit(sizer)

    def get_values(self):
        results = {}
        for label, ctrl in self.controls.items():
            if isinstance(ctrl, wx.Slider):
                results[label] = float(ctrl.GetValue())
            else:
                results[label] = ctrl.GetValue()
        return results

class BreathSmoothingPresetDialog(wx.Dialog):
    """Breath smoothing dialog with strength presets and wet/dry control.

    Layout:
      - Strength presets (Light / Medium / Heavy) with descriptions
      - Sensitivity slider (how many breaths to detect)
      - Wet/Dry mix slider (how much processing to apply)
    """

    def __init__(self, parent, title="Breath Smoothing"):
        super().__init__(parent, title=title)
        built_in = [k for k in config.BREATH_SMOOTHING_LEVELS if k != "Disabled"]
        custom = self._load_custom_names()
        self.preset_names = built_in + custom
        self.selected_preset = "Medium"
        self._active_base_preset = "Medium"  # tracks which built-in preset is the base
        self._build_ui()
        self.SetAffirmativeId(wx.ID_OK)
        self.Centre()

    def _get_base_preset(self):
        """Return the built-in preset values to use as base (cutoff_hz, fade_ms).
        When a custom preset is selected, we fall back to Medium as the base.
        """
        if self.selected_preset in config.BREATH_SMOOTHING_LEVELS:
            return config.BREATH_SMOOTHING_LEVELS[self.selected_preset]
        return config.BREATH_SMOOTHING_LEVELS[self._active_base_preset]

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        # --- Strength Presets ---
        preset_box = wx.StaticBox(self, label="Strength")
        preset_sizer = wx.StaticBoxSizer(preset_box, wx.VERTICAL)

        self.preset_radios = {}
        for name in self.preset_names:
            if name == "Medium":
                style = wx.RB_GROUP
            else:
                style = 0
            radio = wx.RadioButton(self, label=name, style=style)
            # Built-in presets have descriptions; custom presets show a generic note
            if name in config.BREATH_SMOOTHING_LEVELS:
                desc = config.BREATH_SMOOTHING_LEVELS[name]["description"]
            else:
                desc = "Custom preset — values loaded from saved settings"
            radio.SetToolTip(desc)
            self.preset_radios[name] = radio
            preset_sizer.Add(radio, 0, wx.ALL, 4)

            desc_st = wx.StaticText(self, label=desc)
            desc_st.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            desc_st.SetForegroundColour(wx.Colour(80, 80, 80))
            indent = wx.BoxSizer(wx.HORIZONTAL)
            indent.AddSpacer(16)
            indent.Add(desc_st)
            preset_sizer.Add(indent, 0, wx.BOTTOM | wx.LEFT, 2)

        outer.Add(preset_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # --- Sensitivity ---
        sens_box = wx.BoxSizer(wx.HORIZONTAL)
        sens_label = wx.StaticText(self, label="Sensitivity:")
        sens_label.SetMinSize((100, -1))
        self.sens_slider = wx.Slider(self, value=50, minValue=1, maxValue=100,
                                     style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.sens_slider.SetToolTip("Higher = detect more breaths. Adjust until most breaths are caught without tagging normal speech.")
        sens_box.Add(sens_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sens_box.Add(self.sens_slider, 1, wx.EXPAND)
        outer.Add(sens_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # --- Wet/Dry Mix ---
        mix_box = wx.BoxSizer(wx.HORIZONTAL)
        mix_label = wx.StaticText(self, label="Effect amount:")
        mix_label.SetMinSize((100, -1))
        self.mix_slider = wx.Slider(self, value=100, minValue=1, maxValue=100,
                                    style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.mix_slider.SetToolTip("100% = full processing. Lower values blend in more of the original breath sound for a more natural result.")
        mix_box.Add(mix_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        mix_box.Add(self.mix_slider, 1, wx.EXPAND)
        outer.Add(mix_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Percentage labels under sliders
        sens_pct = wx.BoxSizer(wx.HORIZONTAL)
        self.sens_pct_st = wx.StaticText(self, label="Detects moderate breath sounds")
        self.sens_pct_st.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        sens_pct.AddSpacer(108)
        sens_pct.Add(self.sens_pct_st)
        outer.Add(sens_pct, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.mix_pct_st = wx.StaticText(self, label="Full processing applied")
        self.mix_pct_st.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        mix_pct = wx.BoxSizer(wx.HORIZONTAL)
        mix_pct.AddSpacer(108)
        mix_pct.Add(self.mix_pct_st)
        outer.Add(mix_pct, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Update descriptions when sliders move
        self.sens_slider.Bind(wx.EVT_SLIDER, self._update_hint_labels)
        self.mix_slider.Bind(wx.EVT_SLIDER, self._update_hint_labels)

        # Bind preset radios
        for name, radio in self.preset_radios.items():
            self.Bind(wx.EVT_RADIOBUTTON, self._on_preset_selected, radio)

        # Preset radio binding for Medium default
        self.preset_radios["Medium"].SetValue(True)

        # Custom button row (Save + Manage + OK + Cancel)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label="Save as Preset...")
        manage_btn = wx.Button(self, label="Manage Custom...")
        ok_btn = wx.Button(self, wx.ID_OK)
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_as_preset)
        manage_btn.Bind(wx.EVT_BUTTON, self._on_manage_custom)
        btn_row.AddMany([
            (save_btn, 0, wx.ALL, 4),
            (manage_btn, 0, wx.ALL, 4),
            (wx.StaticText(self, label=""), 1, wx.EXPAND),
            (ok_btn, 0, wx.ALL, 4),
            (cancel_btn, 0, wx.ALL, 4),
        ])
        outer.Add(btn_row, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        self.SetSizerAndFit(outer)

    def _on_preset_selected(self, event):
        for name, radio in self.preset_radios.items():
            if radio.GetValue():
                self.selected_preset = name
                # Track base built-in preset for cutoff/fade values
                if name in config.BREATH_SMOOTHING_LEVELS:
                    self._active_base_preset = name
                # Load custom preset values into sliders if custom
                if name not in config.BREATH_SMOOTHING_LEVELS:
                    _, _, breath = preset_manager.load_custom_presets()
                    vals = breath.get(name, {})
                    if vals:
                        # Sensitivity: rms_thresh (0.01-0.10) -> slider (1-100)
                        rms = vals.get("rms_thresh", 0.05)
                        sens = int(round((1.0 - (rms - 0.01) / 0.09) * 100))
                        self.sens_slider.SetValue(max(1, min(100, sens)))
                        # Dry/wet: 0.0-1.0 -> slider 1-100
                        dw = vals.get("dry_wet", 1.0)
                        self.mix_slider.SetValue(int(round(dw * 100)))
                        self._update_hint_labels(None)
                break

    def _update_hint_labels(self, event):
        sens = self.sens_slider.GetValue()
        mix = self.mix_slider.GetValue()

        if sens <= 25:
            sens_hint = "Low sensitivity — only loud breaths detected"
        elif sens <= 75:
            sens_hint = "Medium sensitivity — most breaths detected"
        else:
            sens_hint = "High sensitivity — may also tag quiet speech"

        if mix <= 20:
            mix_hint = f"Very subtle ({mix}% effect) — mostly original breath sound"
        elif mix <= 60:
            mix_hint = f"Moderate ({mix}% effect) — balanced blend"
        elif mix <= 90:
            mix_hint = f"Strong ({mix}% effect) — clear processing"
        else:
            mix_hint = f"Full ({mix}% effect) — maximum breath reduction"

        self.sens_pct_st.SetLabel(sens_hint)
        self.mix_pct_st.SetLabel(mix_hint)
        self.SetSizerAndFit()

    def get_values(self):
        """Return dict with preset, sensitivity, and dry_wet."""
        base = self._get_base_preset()
        sens = self.sens_slider.GetValue() / 100.0  # 0.01 to 1.0
        dry_wet = self.mix_slider.GetValue() / 100.0  # 0.01 to 1.0
        return {
            "reduction_db": base["reduction_db"],
            "dry_wet": dry_wet,
            "rms_thresh": 0.01 + (1.0 - sens) * 0.09,  # sens=1 → thresh=0.01, sens=0 → thresh=0.10
            "preset_name": self.selected_preset,
        }

    def _load_custom_names(self):
        """Return list of custom breath smoothing preset names."""
        _, _, breath = preset_manager.load_custom_presets()
        return list(breath.keys())

    def _on_save_as_preset(self, event):
        """Prompt for a name and save the current breath smoothing settings as a custom preset."""
        dlg = wx.TextEntryDialog(
            self,
            "Enter a name for this breath smoothing preset:",
            "Save Breath Smoothing Preset",
            "",
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            name = dlg.GetValue().strip()
            if not name:
                wx.MessageBox("Please enter a preset name.", "Name Required", wx.ICON_WARNING)
                dlg.Destroy()
                return
            if name in config.BREATH_SMOOTHING_LEVELS:
                wx.MessageBox(
                    f"A built-in preset already has the name '{name}'. Please choose a different name.",
                    "Name Conflict",
                    wx.ICON_WARNING,
                )
                dlg.Destroy()
                return
            custom_names = self._load_custom_names()
            if name in custom_names:
                wx.MessageBox(
                    f"A preset named '{name}' already exists. Choose a different name.",
                    "Name Conflict",
                    wx.ICON_WARNING,
                )
                dlg.SetValue("")
                dlg.GetChildren()[1].SetFocus()
                dlg.Destroy()
                return

            vals = self.get_values()
            base = self._get_base_preset()
            params = {
                "reduction_db": vals["reduction_db"],
                "rms_thresh": vals["rms_thresh"],
                "dry_wet": vals["dry_wet"],
                "cutoff_hz": base["cutoff_hz"],
                "fade_ms": base["fade_ms"],
            }
            preset_manager.add_custom_breath_preset(name, params, "")
            self.GetParent().announce(f"Saved breath smoothing preset: {name}")
            wx.MessageBox(
                f"Saved preset '{name}'.\n\n"
                "Open the Breath Smoothing dialog again to see it in the list.",
                "Preset Saved",
                wx.ICON_INFORMATION,
            )
        dlg.Destroy()

    def _on_manage_custom(self, event):
        """Show a dialog listing custom breath smoothing presets with delete option."""
        custom = self._load_custom_names()
        if not custom:
            wx.MessageBox(
                "No custom breath smoothing presets yet.\n\nUse 'Save as Preset...' to create one.",
                "No Custom Presets",
                wx.ICON_INFORMATION,
            )
            return

        dlg = wx.Dialog(self, title="Manage Custom Breath Smoothing Presets", size=(450, 350))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dlg, label="Select a preset to delete:"), 0, wx.ALL, 8)

        list_ctrl = wx.ListBox(dlg, choices=custom, style=wx.LB_SINGLE)
        sizer.Add(list_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        delete_btn = wx.Button(dlg, label="Delete")
        close_btn = wx.Button(dlg, wx.ID_CLOSE)
        btn_row.AddMany([(delete_btn, 0, wx.ALL, 4), (wx.StaticText(dlg, label=""), 1, wx.EXPAND), (close_btn, 0, wx.ALL, 4)])
        sizer.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        def on_delete(evt):
            sel = list_ctrl.GetSelection()
            if sel == wx.NOT_FOUND:
                return
            name = custom[sel]
            if wx.MessageBox(f"Delete preset '{name}'?", "Confirm Delete", wx.YES_NO | wx.ICON_WARNING) == wx.YES:
                preset_manager.delete_custom_breath_preset(name)
                custom.pop(sel)
                list_ctrl.Set(custom)

        delete_btn.Bind(wx.EVT_BUTTON, on_delete)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        dlg.SetSizerAndFit(sizer)
        dlg.Centre()
        dlg.ShowModal()
        dlg.Destroy()


class CompressorPresetDialog(wx.Dialog):
    """Compressor dialog with voice presets and optional advanced controls.

    Layout:
      - Preset radio buttons with descriptions (left panel)
      - Parameter display / sliders (right panel)
      - "Show Advanced" checkbox reveals full sliders
    """

    def __init__(self, parent, title="Compressor — Voice Presets"):
        super().__init__(parent, title=title)
        self.preset_names = list(config.COMPRESSOR_PRESETS.keys()) + self._load_custom_names()
        self.selected_preset = "Voiceover/broadcast"
        self.show_advanced = False
        self.advanced_controls = {}  # label -> wx.Slider

        self._build_ui()
        self.SetAffirmativeId(wx.ID_OK)
        self.Centre()

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        main = wx.BoxSizer(wx.HORIZONTAL)

        # --- LEFT: Preset list ---
        left_box = wx.StaticBox(self, label="Preset")
        left_sizer = wx.StaticBoxSizer(left_box, wx.VERTICAL)

        self.preset_radios = {}
        for name in self.preset_names:
            if name == "Custom":
                continue  # handled via Advanced checkbox
            radio = wx.RadioButton(self, label=name, style=wx.RB_GROUP)
            desc = config.COMPRESSOR_PRESETS[name]["description"]
            radio.SetToolTip(desc)
            self.preset_radios[name] = radio
            left_sizer.Add(radio, 0, wx.ALL, 4)

            # Description below the radio
            desc_st = wx.StaticText(self, label=desc)
            desc_st.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            desc_st.SetForegroundColour(wx.Colour(80, 80, 80))
            # indent it
            indent = wx.BoxSizer(wx.HORIZONTAL)
            indent.AddSpacer(16)
            indent.Add(desc_st)
            left_sizer.Add(indent, 0, wx.BOTTOM | wx.LEFT, 2)

        left_sizer.AddSpacer(6)

        # Advanced checkbox
        self.advanced_check = wx.CheckBox(self, label="Show advanced controls")
        self.advanced_check.Bind(wx.EVT_CHECKBOX, self._on_advanced_toggle)
        left_sizer.Add(self.advanced_check, 0, wx.ALL, 4)

        main.Add(left_sizer, 1, wx.ALL | wx.EXPAND, 10)

        # --- RIGHT: Parameter display / sliders ---
        self.right_panel = wx.Panel(self)
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)
        self.right_panel.SetSizer(self.right_sizer)

        # Non-editable display of current preset values
        self.param_labels = {}
        param_names = ["Threshold (dB)", "Ratio (:1)", "Attack (x0.1ms)", "Release (ms)", "Makeup (dB)"]
        for pn in param_names:
            row = wx.BoxSizer(wx.HORIZONTAL)
            st = wx.StaticText(self.right_panel, label=pn + ":")
            st.SetMinSize((110, -1))
            val_st = wx.StaticText(self.right_panel, label="")
            row.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            row.Add(val_st, 1, wx.ALIGN_CENTER_VERTICAL)
            self.param_labels[pn] = val_st
            self.right_sizer.Add(row, 0, wx.ALL, 4)

        # Advanced sliders (hidden by default)
        adv_defaults = {
            "Threshold (dB)": (-20, -60, 0),
            "Ratio (:1)": (4, 1, 20),
            "Attack (x0.1ms)": (5, 1, 200),
            "Release (ms)": (50, 1, 1000),
            "Makeup (dB)": (0, -24, 24),
        }
        for pn, (default, lo, hi) in adv_defaults.items():
            row = wx.BoxSizer(wx.HORIZONTAL)
            st = wx.StaticText(self.right_panel, label=pn + ":")
            st.SetMinSize((110, -1))
            slider = wx.Slider(self.right_panel, value=int(default), minValue=int(lo),
                               maxValue=int(hi), style=wx.SL_HORIZONTAL | wx.SL_LABELS)
            slider.Show(False)
            row.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            row.Add(slider, 1, wx.EXPAND)
            self.right_sizer.Add(row, 0, wx.ALL, 4)
            self.advanced_controls[pn] = slider

        self.right_panel.GetSizerAndFit()
        main.Add(self.right_panel, 2, wx.ALL | wx.EXPAND, 10)
        outer.Add(main, 1, wx.EXPAND)

        # Bind preset radios
        for name, radio in self.preset_radios.items():
            self.Bind(wx.EVT_RADIOBUTTON, self._on_preset_selected, radio)

        # Custom button row (Save + Manage + OK + Cancel)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label="Save as Preset...")
        manage_btn = wx.Button(self, label="Manage Custom...")
        ok_btn = wx.Button(self, wx.ID_OK)
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_as_preset)
        manage_btn.Bind(wx.EVT_BUTTON, self._on_manage_custom)
        btn_row.AddMany([
            (save_btn, 0, wx.ALL, 4),
            (manage_btn, 0, wx.ALL, 4),
            (wx.StaticText(self, label=""), 1, wx.EXPAND),
            (ok_btn, 0, wx.ALL, 4),
            (cancel_btn, 0, wx.ALL, 4),
        ])
        outer.Add(btn_row, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        self.SetSizerAndFit(outer)
        self._update_display()

    def _on_preset_selected(self, event):
        for name, radio in self.preset_radios.items():
            if radio.GetValue():
                self.selected_preset = name
                break
        self._update_display()

    def _on_advanced_toggle(self, event):
        self.show_advanced = self.advanced_check.GetValue()
        for ctrl in self.advanced_controls.values():
            ctrl.Show(self.show_advanced)
        self.right_panel.GetSizerAndFit()
        self.SetSizerAndFit()
        self.Centre()

    def _update_display(self):
        # Load values from built-in or custom preset
        if self.selected_preset in config.COMPRESSOR_PRESETS:
            p = config.COMPRESSOR_PRESETS[self.selected_preset]
        else:
            _, comp, _ = preset_manager.load_custom_presets()
            p = comp.get(self.selected_preset, {})
            if not p:
                p = {"threshold_db": -20, "ratio": 4, "attack_ms": 5, "release_ms": 50, "makeup_db": 0}
        # Convert attack_ms to slider scale (slider 1 = 0.1ms, so value = ms / 0.1)
        attack_slider = round(p.get("attack_ms", 5) / 0.1)
        vals = {
            "Threshold (dB)": p.get("threshold_db", -20),
            "Ratio (:1)": p.get("ratio", 4),
            "Attack (x0.1ms)": attack_slider,
            "Release (ms)": p.get("release_ms", 50),
            "Makeup (dB)": p.get("makeup_db", 0),
        }
        for key, st in self.param_labels.items():
            val = vals.get(key, "")
            # Human-readable label for attack
            if key == "Attack (x0.1ms)":
                st.SetLabel(f"{vals[key]} (={vals[key]*0.1:.1f}ms)")
            else:
                st.SetLabel(str(val))
        self.right_panel.GetSizerAndFit()

    def get_values(self):
        """Return (preset_name, params_dict)."""
        if self.show_advanced:
            return {
                "threshold_db": self.advanced_controls["Threshold (dB)"].GetValue(),
                "ratio": self.advanced_controls["Ratio (:1)"].GetValue(),
                "attack_ms": self.advanced_controls["Attack (x0.1ms)"].GetValue() * 0.1,
                "release_ms": self.advanced_controls["Release (ms)"].GetValue(),
                "makeup_db": self.advanced_controls["Makeup (dB)"].GetValue(),
            }
        else:
            # Use same custom-preset logic as _update_display
            if self.selected_preset in config.COMPRESSOR_PRESETS:
                p = config.COMPRESSOR_PRESETS[self.selected_preset]
            else:
                _, comp, _ = preset_manager.load_custom_presets()
                p = comp.get(self.selected_preset, {})
            return {
                "threshold_db": p.get("threshold_db", -20),
                "ratio": p.get("ratio", 4),
                "attack_ms": p.get("attack_ms", 5),
                "release_ms": p.get("release_ms", 50),
                "makeup_db": p.get("makeup_db", 0),
            }

    def _load_custom_names(self):
        """Return list of custom compressor preset names."""
        _, comp, _ = preset_manager.load_custom_presets()
        return list(comp.keys())

    def _on_save_as_preset(self, event):
        """Prompt for a name and save the current compressor settings as a custom preset."""
        dlg = wx.TextEntryDialog(
            self,
            "Enter a name for this compressor preset:",
            "Save Compressor Preset",
            "",
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            name = dlg.GetValue().strip()
            if not name:
                wx.MessageBox("Please enter a preset name.", "Name Required", wx.ICON_WARNING)
                dlg.Destroy()
                return
            if name in config.COMPRESSOR_PRESETS:
                wx.MessageBox(
                    f"A built-in preset already has the name '{name}'. Please choose a different name.",
                    "Name Conflict",
                    wx.ICON_WARNING,
                )
                dlg.Destroy()
                return

            params = self.get_values()
            custom_names = self._load_custom_names()
            if name in custom_names:
                wx.MessageBox(
                    f"A preset named '{name}' already exists. Choose a different name.",
                    "Name Conflict",
                    wx.ICON_WARNING,
                )
                dlg.SetValue("")
                dlg.GetChildren()[1].SetFocus()
                dlg.Destroy()
                return
            preset_manager.add_custom_compressor_preset(name, params, "")
            self.GetParent().announce(f"Saved compressor preset: {name}")
            wx.MessageBox(
                f"Saved preset '{name}'.\n\n"
                "Open the Compressor dialog again to see it in the list.",
                "Preset Saved",
                wx.ICON_INFORMATION,
            )
        dlg.Destroy()

    def _on_manage_custom(self, event):
        """Show a dialog listing custom compressor presets with delete option."""
        custom = self._load_custom_names()
        if not custom:
            wx.MessageBox(
                "No custom compressor presets yet.\n\nUse 'Save as Preset...' to create one.",
                "No Custom Presets",
                wx.ICON_INFORMATION,
            )
            return

        dlg = wx.Dialog(self, title="Manage Custom Compressor Presets", size=(450, 350))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dlg, label="Select a preset to delete:"), 0, wx.ALL, 8)

        list_ctrl = wx.ListBox(dlg, choices=custom, style=wx.LB_SINGLE)
        sizer.Add(list_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        delete_btn = wx.Button(dlg, label="Delete")
        close_btn = wx.Button(dlg, wx.ID_CLOSE)
        btn_row.AddMany([(delete_btn, 0, wx.ALL, 4), (wx.StaticText(dlg, label=""), 1, wx.EXPAND), (close_btn, 0, wx.ALL, 4)])
        sizer.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        def on_delete(evt):
            sel = list_ctrl.GetSelection()
            if sel == wx.NOT_FOUND:
                return
            name = custom[sel]
            if wx.MessageBox(f"Delete preset '{name}'?", "Confirm Delete", wx.YES_NO | wx.ICON_WARNING) == wx.YES:
                preset_manager.delete_custom_compressor_preset(name)
                custom.pop(sel)
                list_ctrl.Set(custom)

        delete_btn.Bind(wx.EVT_BUTTON, on_delete)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        dlg.SetSizerAndFit(sizer)
        dlg.Centre()
        dlg.ShowModal()
        dlg.Destroy()


class EQPresetDialog(wx.Dialog):
    """5-band EQ dialog with voice presets and optional advanced controls.

    Layout:
      - Preset radio buttons with descriptions (left)
      - 5-band gain display / sliders (right)
      - "Show Advanced" checkbox reveals individual band sliders
    """

    def __init__(self, parent, title="Equalizer — Voice Presets"):
        super().__init__(parent, title=title)
        self.preset_names = list(config.EQ_PRESETS.keys()) + self._load_custom_names()
        self.selected_preset = "Radio/podcast ready"
        self.show_advanced = False
        self.band_sliders = {}  # band_label -> wx.Slider

        self._build_ui()
        self.SetAffirmativeId(wx.ID_OK)
        self.Centre()

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        main = wx.BoxSizer(wx.HORIZONTAL)

        # --- LEFT: Preset list ---
        left_box = wx.StaticBox(self, label="Preset")
        left_sizer = wx.StaticBoxSizer(left_box, wx.VERTICAL)

        self.preset_radios = {}
        for name in self.preset_names:
            if name == "Custom":
                continue
            radio = wx.RadioButton(self, label=name, style=wx.RB_GROUP)
            desc = config.EQ_PRESETS[name]["description"]
            radio.SetToolTip(desc)
            self.preset_radios[name] = radio
            left_sizer.Add(radio, 0, wx.ALL, 4)

            desc_st = wx.StaticText(self, label=desc)
            desc_st.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            desc_st.SetForegroundColour(wx.Colour(80, 80, 80))
            indent = wx.BoxSizer(wx.HORIZONTAL)
            indent.AddSpacer(16)
            indent.Add(desc_st)
            left_sizer.Add(indent, 0, wx.BOTTOM | wx.LEFT, 2)

        left_sizer.AddSpacer(6)
        self.advanced_check = wx.CheckBox(self, label="Show advanced controls")
        self.advanced_check.Bind(wx.EVT_CHECKBOX, self._on_advanced_toggle)
        left_sizer.Add(self.advanced_check, 0, wx.ALL, 4)

        main.Add(left_sizer, 1, wx.ALL | wx.EXPAND, 10)

        # --- RIGHT: Band display / sliders ---
        self.right_panel = wx.Panel(self)
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.band_labels = {}  # label -> StaticText showing gain
        for freq_hz, label in zip(audio_effects.Equalizer.BAND_FREQUENCIES,
                                   audio_effects.Equalizer.BAND_LABELS):
            row = wx.BoxSizer(wx.HORIZONTAL)
            st = wx.StaticText(self.right_panel, label=label)
            st.SetMinSize((200, -1))
            val_st = wx.StaticText(self.right_panel, label="0 dB")
            row.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            row.Add(val_st, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            self.band_labels[label] = val_st
            self.right_sizer.Add(row, 0, wx.ALL, 4)

        self.right_sizer.AddSpacer(6)

        # Advanced sliders for each band
        hint_st = wx.StaticText(self.right_panel, label="Advanced band controls:")
        hint_st.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        hint_st.Show(False)
        self.right_sizer.Add(hint_st, 0, wx.LEFT | wx.BOTTOM, 4)
        self._hint_st = hint_st

        for freq_hz, label in zip(audio_effects.Equalizer.BAND_FREQUENCIES,
                                   audio_effects.Equalizer.BAND_LABELS):
            row = wx.BoxSizer(wx.HORIZONTAL)
            st = wx.StaticText(self.right_panel, label=label.split(" ")[0] + " Hz:")
            st.SetMinSize((80, -1))
            slider = wx.Slider(self.right_panel, value=0, minValue=-12, maxValue=12,
                               style=wx.SL_HORIZONTAL | wx.SL_LABELS)
            slider.Show(False)
            row.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            row.Add(slider, 1, wx.EXPAND)
            self.right_sizer.Add(row, 0, wx.ALL, 4)
            self.band_sliders[label] = slider
            slider.Bind(wx.EVT_SLIDER, self._on_band_slider)

        self.right_panel.SetSizer(self.right_sizer)
        main.Add(self.right_panel, 2, wx.ALL | wx.EXPAND, 10)
        outer.Add(main, 1, wx.EXPAND)

        # Bind preset radios
        for name, radio in self.preset_radios.items():
            self.Bind(wx.EVT_RADIOBUTTON, self._on_preset_selected, radio)

        # Custom button row (Save + Manage + OK + Cancel)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label="Save as Preset...")
        manage_btn = wx.Button(self, label="Manage Custom...")
        ok_btn = wx.Button(self, wx.ID_OK)
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_as_preset)
        manage_btn.Bind(wx.EVT_BUTTON, self._on_manage_custom)
        btn_row.AddMany([
            (save_btn, 0, wx.ALL, 4),
            (manage_btn, 0, wx.ALL, 4),
            (wx.StaticText(self, label=""), 1, wx.EXPAND),  # Spacer
            (ok_btn, 0, wx.ALL, 4),
            (cancel_btn, 0, wx.ALL, 4),
        ])
        outer.Add(btn_row, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        self.SetSizerAndFit(outer)
        self._update_display()

    def _on_preset_selected(self, event):
        for name, radio in self.preset_radios.items():
            if radio.GetValue():
                self.selected_preset = name
                break
        self._update_display()

    def _on_advanced_toggle(self, event):
        self.show_advanced = self.advanced_check.GetValue()
        for slider in self.band_sliders.values():
            slider.Show(self.show_advanced)
        self._hint_st.Show(self.show_advanced)
        self.right_panel.GetSizerAndFit()
        self.SetSizerAndFit()
        self.Centre()

    def _on_band_slider(self, event):
        """Mirror slider changes to the display labels."""
        for label, slider in self.band_sliders.items():
            val = slider.GetValue()
            sign = "+" if val > 0 else ""
            self.band_labels[label].SetLabel(f"{sign}{val} dB")

    def _update_display(self):
        # Load bands from built-in or custom preset
        if self.selected_preset in config.EQ_PRESETS:
            bands = config.EQ_PRESETS[self.selected_preset]["bands"]
        else:
            eq, _, _ = preset_manager.load_custom_presets()
            bands = eq.get(self.selected_preset, {}).get("bands", [(0, 0)] * 5)
        for (freq, gain), label in zip(bands, audio_effects.Equalizer.BAND_LABELS):
            sign = "+" if gain > 0 else ""
            self.band_labels[label].SetLabel(f"{sign}{gain} dB")

        # If advanced is open, sync sliders too
        if self.show_advanced:
            for (freq, gain), label, slider in zip(
                    bands, audio_effects.Equalizer.BAND_LABELS,
                    self.band_sliders.values()):
                slider.SetValue(int(gain))

    def get_values(self):
        """Return list of (freq, gain_db) tuples for all 5 bands."""
        if self.show_advanced:
            return [(freq, self.band_sliders[label].GetValue())
                    for freq, label in zip(audio_effects.Equalizer.BAND_FREQUENCIES,
                                           audio_effects.Equalizer.BAND_LABELS)]
        else:
            # Use same logic as _update_display to get bands
            if self.selected_preset in config.EQ_PRESETS:
                return config.EQ_PRESETS[self.selected_preset]["bands"]
            else:
                eq, _, _ = preset_manager.load_custom_presets()
                return eq.get(self.selected_preset, {}).get("bands", [(0, 0)] * 5)

    def get_preset_name(self):
        return self.selected_preset

    def _load_custom_names(self):
        """Return list of custom EQ preset names (from saved file)."""
        eq, _, _ = preset_manager.load_custom_presets()
        return list(eq.keys())

    def _on_save_as_preset(self, event):
        """Prompt for a name and save the current EQ settings as a custom preset."""
        dlg = wx.TextEntryDialog(
            self,
            "Enter a name for this EQ preset:",
            "Save EQ Preset",
            "",
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            name = dlg.GetValue().strip()
            if not name:
                wx.MessageBox("Please enter a preset name.", "Name Required", wx.ICON_WARNING)
                dlg.Destroy()
                return
            if name in config.EQ_PRESETS:
                wx.MessageBox(
                    f"A built-in preset already has the name '{name}'. Please choose a different name.",
                    "Name Conflict",
                    wx.ICON_WARNING,
                )
                dlg.Destroy()
                return

            # Check custom preset name conflict
            custom_names = self._load_custom_names()
            if name in custom_names:
                wx.MessageBox(
                    f"A preset named '{name}' already exists. Choose a different name.",
                    "Name Conflict",
                    wx.ICON_WARNING,
                )
                dlg.SetValue("")
                dlg.GetChildren()[1].SetFocus()
                dlg.Destroy()
                return

            # Get current band values
            bands = self.get_values()  # list of (freq, gain_db)
            desc = ""
            preset_manager.add_custom_eq_preset(name, bands, desc)
            self.preset_names = list(config.EQ_PRESETS.keys()) + self._load_custom_names()
            self.GetParent().announce(f"Saved EQ preset: {name}")
            wx.MessageBox(f"Saved preset '{name}'.\n\nOpen the EQ dialog again to see it in the list.", "Preset Saved", wx.ICON_INFORMATION)
        dlg.Destroy()

    def _on_manage_custom(self, event):
        """Show a dialog listing custom presets with rename and delete options."""
        custom = self._load_custom_names()
        if not custom:
            wx.MessageBox(
                "No custom EQ presets yet.\n\nUse 'Save as Preset...' to create one.",
                "No Custom Presets",
                wx.ICON_INFORMATION,
            )
            return

        # Simple list with Delete buttons
        dlg = wx.Dialog(self, title="Manage Custom EQ Presets", size=(450, 350))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dlg, label="Select a preset to delete:"), 0, wx.ALL, 8)

        list_ctrl = wx.ListBox(dlg, choices=custom, style=wx.LB_SINGLE)
        sizer.Add(list_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        delete_btn = wx.Button(dlg, label="Delete")
        close_btn = wx.Button(dlg, wx.ID_CLOSE)
        btn_row.AddMany([(delete_btn, 0, wx.ALL, 4), (wx.StaticText(dlg, label=""), 1, wx.EXPAND), (close_btn, 0, wx.ALL, 4)])
        sizer.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        def on_delete(evt):
            sel = list_ctrl.GetSelection()
            if sel == wx.NOT_FOUND:
                return
            name = custom[sel]
            if wx.MessageBox(f"Delete preset '{name}'?", "Confirm Delete", wx.YES_NO | wx.ICON_WARNING) == wx.YES:
                preset_manager.delete_custom_eq_preset(name)
                custom.pop(sel)
                list_ctrl.Set(custom)

        delete_btn.Bind(wx.EVT_BUTTON, on_delete)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        dlg.SetSizerAndFit(sizer)
        dlg.Centre()
        dlg.ShowModal()
        dlg.Destroy()


# ============================================================================
# Room Tone Match Dialog
# ============================================================================
class RoomToneMatchDialog(wx.Dialog):
    """Dialog to generate a looped room-tone track from a reference ambiance region.

    The user selects a reference region from any track, chooses how many times
    to loop it (with crossfades), and the app creates a new mono AMBIENCE track.

    Layout:
      - Track selector (which track to take reference from)
      - Reference region: Start (s) and End (s)
      - Number of loops
      - Crossfade duration (ms)
      - Track name for the new room tone track
      - Level (dB)
      - Preview button to audition the reference region
    """

    def __init__(self, parent, track_names, track_durations):
        super().__init__(parent, title="Room Tone Match — SpeechCraft Studio",
                        size=(460, 430), style=wx.DEFAULT_DIALOG_STYLE)
        self.track_names = track_names
        self.track_durations = track_durations
        self.selected_track = 0
        self.ref_start_s = 0.0
        self.ref_end_s = 5.0
        self.num_loops = 3
        self.crossfade_ms = 100
        self.track_name = "Room Tone"
        self.level_db = -40
        self._build_ui()
        self._populate_from_selection()
        self.SetAffirmativeId(wx.ID_OK)
        self.Centre()

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        # --- Reference Track ---
        outer.Add(wx.StaticText(self, label="Reference track:"), 0, wx.ALL, 4)
        self.track_choice = wx.Choice(self)
        for name in self.track_names:
            self.track_choice.Append(name)
        self.track_choice.SetSelection(0)
        self.track_choice.Bind(wx.EVT_CHOICE, self._on_track_change)
        outer.Add(self.track_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        # --- Reference Region ---
        reg_box = wx.StaticBox(self, label="Reference region (seconds)")
        reg_sizer = wx.StaticBoxSizer(reg_box, wx.HORIZONTAL)
        self.start_st = wx.StaticText(self, label="Start:")
        self.start_st.SetMinSize((50, -1))
        self.start_tc = wx.TextCtrl(self, value="0.0", size=(70, -1),
                                    style=wx.TE_PROCESS_ENTER)
        self.start_tc.Bind(wx.EVT_TEXT_ENTER, self._on_region_change)
        self.end_st = wx.StaticText(self, label="  End:")
        self.end_st.SetMinSize((40, -1))
        self.end_tc = wx.TextCtrl(self, value="5.0", size=(70, -1),
                                  style=wx.TE_PROCESS_ENTER)
        self.end_tc.Bind(wx.EVT_TEXT_ENTER, self._on_region_change)
        self.preview_btn = wx.Button(self, label="Preview")
        self.preview_btn.Bind(wx.EVT_BUTTON, self._on_preview)
        reg_sizer.AddMany([
            (self.start_st, 0, wx.ALIGN_CENTER_VERTICAL),
            (self.start_tc, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4),
            (self.end_st, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8),
            (self.end_tc, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4),
            ((1, 1), 1, wx.EXPAND),
            (self.preview_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8),
        ])
        outer.Add(reg_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Loop Settings ---
        loop_box = wx.BoxSizer(wx.HORIZONTAL)
        loop_label = wx.StaticText(self, label="Number of loops:")
        loop_label.SetMinSize((130, -1))
        self.loop_spin = wx.SpinCtrl(self, value="3", min=1, max=999, size=(70, -1))
        loop_box.AddMany([
            (loop_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8),
            (self.loop_spin, 0),
        ])
        outer.Add(loop_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        cf_box = wx.BoxSizer(wx.HORIZONTAL)
        cf_label = wx.StaticText(self, label="Crossfade duration (ms):")
        cf_label.SetMinSize((170, -1))
        self.cf_spin = wx.SpinCtrl(self, value="100", min=0, max=2000, size=(70, -1))
        cf_box.AddMany([
            (cf_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8),
            (self.cf_spin, 0),
        ])
        outer.Add(cf_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Track Name ---
        name_box = wx.BoxSizer(wx.HORIZONTAL)
        name_label = wx.StaticText(self, label="New track name:")
        name_label.SetMinSize((130, -1))
        self.name_tc = wx.TextCtrl(self, value="Room Tone", size=(200, -1))
        name_box.AddMany([
            (name_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8),
            (self.name_tc, 1, wx.EXPAND),
        ])
        outer.Add(name_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Level ---
        lvl_box = wx.BoxSizer(wx.HORIZONTAL)
        lvl_label = wx.StaticText(self, label="Level (dB):")
        lvl_label.SetMinSize((130, -1))
        self.lvl_slider = wx.Slider(self, value=-40, minValue=-80, maxValue=0,
                                    style=wx.SL_HORIZONTAL | wx.SL_LABELS, size=(200, -1))
        lvl_box.AddMany([
            (lvl_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8),
            (self.lvl_slider, 1, wx.EXPAND),
        ])
        outer.Add(lvl_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Hint text ---
        hint = wx.StaticText(self, label=(
            "Tip: Select a region with only room ambiance (no speech). "
            "Use 3-5 loops to cover typical dialogue gaps. Keep the crossfade "
            "short (50-150 ms) to avoid audible seams."))
        hint.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        hint.SetForegroundColour(wx.Colour(90, 90, 90))
        outer.Add(hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Buttons ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        ok_btn = wx.Button(self, wx.ID_OK)
        ok_btn.SetDefault()
        btn_row.AddMany([
            ((1, 1), 1, wx.EXPAND),
            (cancel_btn, 0, wx.ALL, 4),
            (ok_btn, 0, wx.ALL, 4),
        ])
        outer.Add(btn_row, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizerAndFit(outer)

    def _populate_from_selection(self):
        """Pre-fill start/end from the selected track's duration."""
        self._on_track_change()

    def _on_track_change(self, event=None):
        """Update the default region when track changes."""
        idx = self.track_choice.GetSelection()
        if idx < 0:
            idx = 0
        dur = self.track_durations[idx] if idx < len(self.track_durations) else 0
        # Default to first 5 seconds or the full track if shorter
        end_default = min(5.0, dur)
        self.start_tc.SetValue("0.0")
        self.end_tc.SetValue(str(round(end_default, 1)))

    def _on_region_change(self, event=None):
        """Validate region when user edits start/end."""
        try:
            start = float(self.start_tc.GetValue())
            end = float(self.end_tc.GetValue())
            if end <= start:
                self.end_tc.SetValue(str(start + 1.0))
        except ValueError:
            pass

    def _on_preview(self, event=None):
        """Play the selected reference region for preview."""
        try:
            start = float(self.start_tc.GetValue())
            end = float(self.end_tc.GetValue())
            if end <= start:
                wx.MessageBox("End time must be greater than start time.", "Invalid Region", wx.ICON_WARNING)
                return
        except ValueError:
            wx.MessageBox("Please enter valid numbers for start and end times.", "Invalid Input", wx.ICON_WARNING)
            return

        frame: 'SpeechCraftFrame' = self.GetParent()
        idx = self.track_choice.GetSelection()
        if idx < 0 or idx >= len(frame.track_manager.tracks):
            wx.MessageBox("Invalid track selected.", "Cannot Preview", wx.ICON_WARNING)
            return
        ref_track = frame.track_manager.tracks[idx]
        if ref_track is None or ref_track.audio_segment is None:
            wx.MessageBox("No audio in selected track.", "Cannot Preview", wx.ICON_WARNING)
            return

        ref_seg = ref_track.audio_segment
        start_ms = int(start * 1000)
        end_ms = int(end * 1000)
        region = ref_seg[start_ms:end_ms]

        import numpy as np, sounddevice as sd
        arr = np.array(region.get_array_of_samples(), dtype=np.float32).reshape(region.channels, -1) / (2**15)
        if arr.shape[0] > 1:
            arr = arr.mean(axis=0)
        sd.play(arr.T, region.frame_rate)
        wx.CallLater(int(region.duration * 1000) + 100, sd.stop)

    def _collect_values(self):
        """Update instance attributes from UI controls. Called before EndModal."""
        self.selected_track = self.track_choice.GetSelection()
        try:
            self.ref_start_s = float(self.start_tc.GetValue())
        except ValueError:
            self.ref_start_s = 0.0
        try:
            self.ref_end_s = float(self.end_tc.GetValue())
        except ValueError:
            self.ref_end_s = 5.0
        self.num_loops = self.loop_spin.GetValue()
        self.crossfade_ms = self.cf_spin.GetValue()
        self.track_name = self.name_tc.GetValue().strip() or "Room Tone"
        self.level_db = self.lvl_slider.GetValue()

    def ShowModal(self):
        """Override ShowModal to collect values before returning."""
        result = super().ShowModal()
        if result == wx.ID_OK:
            self._collect_values()
        return result


# ============================================================================
# Batch Processing Dialog
# ============================================================================
class BatchProcessDialog(wx.Dialog):
    """Multi-step dialog for batch-processing a folder of audio files.

    Step 1 — Folder:   Select input and output folders, preview files
    Step 2 — Effect:   Choose effect type, preset, and parameters
    Step 3 — Process:   Run the batch with a progress bar and results log
    """

    def __init__(self, parent):
        super().__init__(parent, title="Batch Process — SpeechCraft Studio",
                        size=(700, 550), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.input_folder = ""
        self.output_folder = ""
        self.effect_type = "compressor"
        self.effect_params = {}
        self.selected_preset = "Voiceover/broadcast"
        self._build_ui()
        self.Centre()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        # Notebook with 3 pages: Folder, Effect, Process
        self.notebook = wx.Notebook(self)
        self._page_folder()
        self._page_effect()
        self._page_process()
        outer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)

        # Bottom buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.cancel_btn = wx.Button(self, wx.ID_CANCEL)
        self.prev_btn = wx.Button(self, label="< Back")
        self.next_btn = wx.Button(self, label="Next >")
        self.prev_btn.Bind(wx.EVT_BUTTON, self._on_prev)
        self.next_btn.Bind(wx.EVT_BUTTON, self._on_next)
        btn_row.AddMany([
            (self.cancel_btn, 0, wx.ALL, 4),
            ((1, 1), 1, wx.EXPAND),  # Spacer
            (self.prev_btn, 0, wx.ALL, 4),
            (self.next_btn, 0, wx.ALL, 4),
        ])
        outer.Add(btn_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizerAndFit(outer)
        self._update_buttons()

    # ------------------------------------------------------------------
    # Page 1 — Folder selection
    # ------------------------------------------------------------------
    def _page_folder(self):
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Input folder row
        in_row = wx.BoxSizer(wx.HORIZONTAL)
        in_row.Add(wx.StaticText(panel, label="Input folder:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.in_path_st = wx.StaticText(panel, label="< not selected >")
        self.in_path_st.SetForegroundColour(wx.Colour(100, 100, 100))
        in_browse = wx.Button(panel, label="Browse...")
        in_browse.Bind(wx.EVT_BUTTON, lambda e: self._browse_folder("input"))
        in_row.Add(self.in_path_st, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        in_row.Add(in_browse, 0)
        sizer.Add(in_row, 0, wx.EXPAND | wx.ALL, 8)

        # Output folder row
        out_row = wx.BoxSizer(wx.HORIZONTAL)
        out_row.Add(wx.StaticText(panel, label="Output folder:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.out_path_st = wx.StaticText(panel, label="< not selected >")
        self.out_path_st.SetForegroundColour(wx.Colour(100, 100, 100))
        out_browse = wx.Button(panel, label="Browse...")
        out_browse.Bind(wx.EVT_BUTTON, lambda e: self._browse_folder("output"))
        out_row.Add(self.out_path_st, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        out_row.Add(out_browse, 0)
        sizer.Add(out_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # File list
        sizer.Add(wx.StaticText(panel, label="Audio files found:"), 0, wx.LEFT | wx.BOTTOM, 4)
        self.file_list = wx.ListBox(panel, style=wx.LB_SINGLE | wx.LB_READONLY)
        sizer.Add(self.file_list, 1, wx.EXPAND | wx.ALL, 4)

        panel.SetSizerAndFit(sizer)
        self.notebook.AddPage(panel, "1. Folder")

    def _browse_folder(self, which):
        dlg = wx.DirDialog(self, f"Select {'input' if which == 'input' else 'output'} folder",
                           style=wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            if which == "input":
                self.input_folder = path
                self.in_path_st.SetLabel(path)
                self.in_path_st.SetForegroundColour(wx.Colour(0, 0, 0))
                self._refresh_file_list()
            else:
                self.output_folder = path
                self.out_path_st.SetLabel(path)
                self.out_path_st.SetForegroundColour(wx.Colour(0, 0, 0))
            self._update_buttons()
        dlg.Destroy()

    def _refresh_file_list(self):
        self.file_list.Clear()
        if not self.input_folder:
            return
        import batch_processor
        files = batch_processor.get_audio_files(self.input_folder)
        if not files:
            self.file_list.Append("  (no supported audio files found)")
            self.file_list.Enable(False)
        else:
            self.file_list.Enable(True)
            for f in files:
                self.file_list.Append(os.path.basename(f))
            self.file_list.SetSelection(0)

    # ------------------------------------------------------------------
    # Page 2 — Effect selection and configuration
    # ------------------------------------------------------------------
    def _page_effect(self):
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Effect type dropdown
        eff_row = wx.BoxSizer(wx.HORIZONTAL)
        eff_row.Add(wx.StaticText(panel, label="Effect:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.effect_choice = wx.Choice(panel, choices=[
            info["label"] for info in batch_processor.EFFECT_DEFINITIONS.values()
        ])
        self.effect_choice.SetSelection(1)  # Default: Compressor
        self.effect_choice.Bind(wx.EVT_CHOICE, self._on_effect_changed)
        eff_row.Add(self.effect_choice, 1, wx.EXPAND)
        sizer.Add(eff_row, 0, wx.EXPAND | wx.ALL, 8)

        # Preset section (changes per effect)
        self.preset_box = wx.StaticBox(panel, label="Preset")
        self.preset_sizer = wx.StaticBoxSizer(self.preset_box, wx.VERTICAL)
        sizer.Add(self.preset_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Advanced params section
        self.advanced_box = wx.StaticBox(panel, label="Parameters")
        self.advanced_sizer = wx.StaticBoxSizer(self.advanced_box, wx.VERTICAL)
        self.param_ctrls = {}  # label -> slider
        sizer.Add(self.advanced_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Output suffix note
        self.suffix_st = wx.StaticText(panel, label="Output files: filename_processed.wav")
        self.suffix_st.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.suffix_st, 0, wx.LEFT | wx.BOTTOM, 4)

        panel.SetSizerAndFit(sizer)
        self.notebook.AddPage(panel, "2. Effect")
        self._rebuild_preset_ui()

    def _on_effect_changed(self, event=None):
        idx = self.effect_choice.GetSelection()
        keys = list(batch_processor.EFFECT_DEFINITIONS.keys())
        self.effect_type = keys[idx]
        self._rebuild_preset_ui()

    def _rebuild_preset_ui(self):
        """Rebuild preset radio buttons and advanced param sliders."""
        # Clear preset section
        for child in self.preset_sizer.GetChildren():
            w = child.GetWindow()
            if w:
                w.Destroy()
        for child in self.advanced_sizer.GetChildren():
            w = child.GetWindow()
            if w:
                w.Destroy()
        self.param_ctrls.clear()

        info = batch_processor.EFFECT_DEFINITIONS.get(self.effect_type, {})
        presets = info.get("presets", {})
        self.preset_radios = {}
        self.preset_obj = None

        if presets:
            # Preset radios
            first = True
            for name, data in list(presets.items())[:6]:
                style = wx.RB_GROUP if first else 0
                first = False
                radio = wx.RadioButton(self.preset_sizer.GetStaticBox(), label=name, style=style)
                self.preset_radios[name] = radio
                self.preset_sizer.Add(radio, 0, wx.ALL, 2)
                if "description" in data:
                    desc = wx.StaticText(self.preset_sizer.GetStaticBox(),
                                         label=f"  {data['description']}")
                    desc.SetFont(wx.Font(7, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
                    desc.SetForegroundColour(wx.Colour(80, 80, 80))
                    self.preset_sizer.Add(desc, 0, wx.LEFT | wx.BOTTOM, 2)
            # Select first
            first_name = list(presets.keys())[0]
            self.preset_radios[first_name].SetValue(True)
            self.selected_preset = first_name
            for radio in self.preset_radios.values():
                radio.Bind(wx.EVT_RADIOBUTTON, self._on_preset_selected)

        # Build param controls based on effect type
        self._build_param_controls()

        self.preset_sizer.GetStaticBox().GetParent().GetSizer().Fit(self.preset_sizer.GetStaticBox())
        self.Layout()
        self.GetSizer().Fit(self)

    def _on_preset_selected(self, event=None):
        for name, radio in self.preset_radios.items():
            if radio.GetValue():
                self.selected_preset = name
                self._apply_preset_to_params()
                break

    def _apply_preset_to_params(self):
        """Update param sliders to match the selected preset."""
        info = batch_processor.EFFECT_DEFINITIONS.get(self.effect_type, {})
        presets = info.get("presets", {})
        if self.selected_preset not in presets:
            return
        preset_data = presets[self.selected_preset]

        if self.effect_type == "breath":
            self._set_slider("Reduction (dB)", preset_data.get("reduction_db", 6))
        elif self.effect_type == "compressor":
            self._set_slider("Threshold (dB)", preset_data.get("threshold_db", -20))
            self._set_slider("Ratio (:1)", preset_data.get("ratio", 4.0))
            self._set_slider("Attack (x0.1ms)", round(preset_data.get("attack_ms", 5.0) / 0.1))
            self._set_slider("Release (ms)", preset_data.get("release_ms", 50.0))
            self._set_slider("Makeup (dB)", preset_data.get("makeup_db", 0.0))
        elif self.effect_type == "eq":
            bands = preset_data.get("bands", [])
            for i, (freq, gain) in enumerate(bands):
                self._set_slider(f"Band {i+1} ({freq} Hz)", gain)

    def _set_slider(self, label, value):
        if label in self.param_ctrls:
            self.param_ctrls[label].SetValue(int(value))

    def _build_param_controls(self):
        """Add parameter sliders for the current effect type."""
        panels = {
            "breath": [
                ("Reduction (dB)", 0, -20, 0, 6),
                ("Sensitivity (1-100)", 50, 1, 100, 50),
                ("Dry/Wet %", 100, 0, 100, 100),
            ],
            "compressor": [
                ("Threshold (dB)", -20, -60, 0, -20),
                ("Ratio (:1)", 4, 1, 20, 4),
                ("Attack (x0.1ms)", 5, 1, 200, 5),
                ("Release (ms)", 50, 1, 1000, 50),
                ("Makeup (dB)", 0, -24, 24, 0),
            ],
            "eq": [
                ("Band 1 (100 Hz)", 0, -12, 12, 0),
                ("Band 2 (300 Hz)", 0, -12, 12, 0),
                ("Band 3 (1000 Hz)", 0, -12, 12, 0),
                ("Band 4 (3000 Hz)", 0, -12, 12, 0),
                ("Band 5 (8000 Hz)", 0, -12, 12, 0),
            ],
            "normalize": [
                ("Target peak (dB)", -1, -12, 0, -1),
            ],
            "denoise": [
                ("Threshold (dB)", -40, -80, 0, -40),
            ],
            "room": [
                ("Sensitivity (0-100)", 50, 0, 100, 50),
            ],
            "deesser": [
                ("Threshold (dB)", -20, -60, 0, -20),
            ],
        }
        rows = panels.get(self.effect_type, [])
        for label, default, lo, hi, init in rows:
            row = wx.BoxSizer(wx.HORIZONTAL)
            st = wx.StaticText(self.advanced_sizer.GetStaticBox(), label=label)
            st.SetMinSize((170, -1))
            slider = wx.Slider(self.advanced_sizer.GetStaticBox(), value=int(init),
                               minValue=int(lo), maxValue=int(hi),
                               style=wx.SL_HORIZONTAL | wx.SL_LABELS)
            slider.SetMinSize((200, -1))
            row.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            row.Add(slider, 1, wx.EXPAND)
            self.advanced_sizer.Add(row, 0, wx.ALL, 4)
            self.param_ctrls[label] = slider

    def _collect_params(self):
        """Collect current parameter values into a dict."""
        p = {}
        for label, slider in self.param_ctrls.items():
            p[label] = slider.GetValue()
        return p

    # ------------------------------------------------------------------
    # Page 3 — Progress and results
    # ------------------------------------------------------------------
    def _page_process(self):
        panel = wx.Panel(self.notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.progress_gauge = wx.Gauge(panel, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        sizer.Add(self.progress_gauge, 0, wx.EXPAND | wx.ALL, 8)

        self.progress_st = wx.StaticText(panel, label="Ready to process.")
        sizer.Add(self.progress_st, 0, wx.LEFT | wx.BOTTOM, 8)

        log_box = wx.StaticBox(panel, label="Results log")
        log_sizer = wx.StaticBoxSizer(log_box, wx.VERTICAL)
        self.log_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
                                     size=(-1, 150))
        log_sizer.Add(self.log_ctrl, 1, wx.EXPAND)
        sizer.Add(log_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizerAndFit(sizer)
        self.notebook.AddPage(panel, "3. Process")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _update_buttons(self):
        page = self.notebook.GetSelection()
        self.prev_btn.Enable(page > 0)
        if page == 2:
            self.next_btn.SetLabel("Process")
        else:
            self.next_btn.SetLabel("Next >")

    def _on_prev(self, event):
        cur = self.notebook.GetSelection()
        if cur > 0:
            self.notebook.SetSelection(cur - 1)
            self._update_buttons()

    def _on_next(self, event):
        cur = self.notebook.GetSelection()

        if cur == 0:
            # Folder page → validate
            if not self.input_folder:
                wx.MessageBox("Please select an input folder.", "Input Required", wx.ICON_WARNING)
                return
            if not self.output_folder:
                wx.MessageBox("Please select an output folder.", "Output Required", wx.ICON_WARNING)
                return
            self.notebook.SetSelection(1)
        elif cur == 1:
            # Effect page → validate
            self.notebook.SetSelection(2)
        elif cur == 2:
            # Process page → run
            self._run_batch()
            return

        self._update_buttons()

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------
    def _run_batch(self):
        self.next_btn.Enable(False)
        self.prev_btn.Enable(False)
        self.cancel_btn.Enable(False)
        self.progress_st.SetLabel("Starting batch...")
        self.progress_gauge.SetValue(0)
        self.log_ctrl.Clear()

        # Collect parameters
        params = self._collect_params()
        raw_params = self._params_to_effect_params(params)

        files = batch_processor.get_audio_files(self.input_folder)
        total = len(files)
        self.progress_gauge.SetRange(total)

        ok_count = 0
        fail_count = 0

        for i, inp_path in enumerate(files):
            basename = os.path.basename(inp_path)
            root, ext = os.path.splitext(basename)
            out_path = os.path.join(self.output_folder, f"{root}_processed{ext}")

            self.progress_st.SetLabel(f"Processing {i+1}/{total}: {basename}")
            self.log_ctrl.AppendText(f"[{i+1}/{total}] {basename} ... ")
            wx.Yield()

            success, msg = batch_processor.apply_effect_to_file(
                inp_path, out_path, self.effect_type, raw_params
            )
            if success:
                self.log_ctrl.AppendText(f"OK → {os.path.basename(out_path)}\n")
                ok_count += 1
            else:
                self.log_ctrl.AppendText(f"FAILED: {msg}\n")
                fail_count += 1

            self.progress_gauge.SetValue(i + 1)
            self.progress_gauge.Update()
            wx.Yield()

        self.progress_st.SetLabel(f"Done. {ok_count} succeeded, {fail_count} failed.")
        self.log_ctrl.AppendText(f"\nBatch complete: {ok_count} OK, {fail_count} failed.\n")
        self.next_btn.Enable(True)
        self.prev_btn.Enable(True)
        self.cancel_btn.Enable(True)
        self.next_btn.SetLabel("Close")

        # Bind next button to close since we're on last page
        self.next_btn.Unbind()
        self.next_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

    def _params_to_effect_params(self, params):
        """Convert UI slider params to the format expected by batch_processor."""
        et = self.effect_type
        if et == "breath":
            sens = params.get("Sensitivity (1-100)", 50) / 100.0
            return {
                "reduction_db": params.get("Reduction (dB)", 6),
                "rms_thresh": 0.01 + (1.0 - sens) * 0.09,
                "dry_wet": params.get("Dry/Wet %", 100) / 100.0,
            }
        elif et == "compressor":
            return {
                "threshold_db": params.get("Threshold (dB)", -20),
                "ratio": float(params.get("Ratio (:1)", 4)),
                "attack_ms": params.get("Attack (x0.1ms)", 5) * 0.1,
                "release_ms": params.get("Release (ms)", 50),
                "makeup_db": params.get("Makeup (dB)", 0),
            }
        elif et == "eq":
            return {
                "bands": [
                    (100, params.get("Band 1 (100 Hz)", 0)),
                    (300, params.get("Band 2 (300 Hz)", 0)),
                    (1000, params.get("Band 3 (1000 Hz)", 0)),
                    (3000, params.get("Band 4 (3000 Hz)", 0)),
                    (8000, params.get("Band 5 (8000 Hz)", 0)),
                ]
            }
        elif et == "normalize":
            return {"target_db": params.get("Target peak (dB)", -1)}
        elif et == "denoise":
            return {"threshold_db": params.get("Threshold (dB)", -40)}
        elif et == "room":
            return {"sensitivity": params.get("Sensitivity (0-100)", 50) / 100.0}
        elif et == "deesser":
            return {"threshold_db": params.get("Threshold (dB)", -20)}
        return params


class SpeechCraftFrame(wx.Frame):
    def __init__(self):
        print("STARTING INIT")
        super().__init__(parent=None, title='SpeechCraft Studio', size=(1000, 800))
        
        # Check FFmpeg before continuing
        self.check_ffmpeg_with_dialog()
        
        # Safety / Late Init for UI components
        self.workspace = None
        self.log_area = None
        self.tracks_list = None
        
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
        import audio_recorder
        self.recorder = audio_recorder.AudioRecorder(progress_callback=self.update_record_time)
        self.is_recording = False

        # Undo History
        self.undo_stack = []
        self.redo_stack = []
        
        # Initialize UI (THIS WAS MISSING!)
        self.init_ui()
        self.create_menus()
        self.CreateStatusBar()  # Create status bar AFTER menus
        
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
        self.add_item(m_speech, "&Masakhane TTS — African languages", self.on_masakhane_tts)
        self.menubar.Append(m_speech, "&Speech")

        # --- 6. HELP ---
        m_help = wx.Menu()
        self.add_item(m_help, "&User Manual\tF1", self.on_help_manual)
        self.add_item(m_help, "&Quick Reference\tF2", self.on_help_quick)
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

    def on_edge_tts(self, event):
        """Edge TTS dialog for free text-to-speech"""
        try:
            from edge_tts_engine import EdgeTTSEngine
        except ImportError:
            wx.MessageBox(
                "Edge TTS is not available.\n\n"
                "Install with: pip install edge-tts",
                "Feature Unavailable",
                wx.ICON_WARNING
            )
            return
        
        # Create dialog
        dlg = wx.Dialog(self, title="Edge TTS - Free Text-to-Speech", size=(550, 450))
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        title = wx.StaticText(dlg, label="Edge TTS (Microsoft)")
        title_font = title.GetFont()
        title_font.SetPointSize(12)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Info text
        info = wx.StaticText(dlg, label="Free, high-quality text-to-speech with South African voices")
        vbox.Add(info, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        # Text input
        vbox.Add(wx.StaticText(dlg, label="Text to synthesize:"), 0, wx.ALL, 5)
        text_ctrl = wx.TextCtrl(dlg, style=wx.TE_MULTILINE, size=(-1, 100))
        text_ctrl.SetValue("Hello, this is a test of Edge TTS.")
        vbox.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Voice selection
        engine = EdgeTTSEngine()
        voices = list(engine.get_all_voices().keys())
        
        voice_box = wx.BoxSizer(wx.HORIZONTAL)
        voice_box.Add(wx.StaticText(dlg, label="Voice:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        voice_choice = wx.Choice(dlg, choices=voices)
        voice_choice.SetSelection(0)  # Default to first SA voice
        voice_box.Add(voice_choice, 1, wx.ALL, 5)
        vbox.Add(voice_box, 0, wx.EXPAND | wx.ALL, 5)
        
        # Speed control
        speed_box = wx.BoxSizer(wx.HORIZONTAL)
        speed_box.Add(wx.StaticText(dlg, label="Speed:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        speed_slider = wx.Slider(dlg, value=0, minValue=-50, maxValue=50, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        speed_box.Add(speed_slider, 1, wx.ALL, 5)
        vbox.Add(speed_box, 0, wx.EXPAND | wx.ALL, 5)
        
        # Pitch control
        pitch_box = wx.BoxSizer(wx.HORIZONTAL)
        pitch_box.Add(wx.StaticText(dlg, label="Pitch:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        pitch_slider = wx.Slider(dlg, value=0, minValue=-50, maxValue=50, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        pitch_box.Add(pitch_slider, 1, wx.ALL, 5)
        vbox.Add(pitch_box, 0, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        synthesize_btn = wx.Button(dlg, wx.ID_OK, label="Synthesize")
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, label="Cancel")
        btn_sizer.Add(synthesize_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        vbox.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        dlg.SetSizer(vbox)
        
        if dlg.ShowModal() == wx.ID_OK:
            text = text_ctrl.GetValue().strip()
            voice_name = voice_choice.GetStringSelection()
            speed = speed_slider.GetValue()
            pitch = pitch_slider.GetValue()
            
            if not text:
                wx.MessageBox("Please enter text to synthesize.", "Error", wx.ICON_ERROR)
                dlg.Destroy()
                return
            
            # Show progress
            progress_dlg = wx.ProgressDialog(
                "Edge TTS",
                "Synthesizing speech...",
                maximum=100,
                parent=self,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE
            )
            progress_dlg.Pulse()
            
            try:
                # Perform synthesis in thread
                result = [None]
                error = [None]
                
                def synthesize_worker():
                    try:
                        tts_engine = EdgeTTSEngine()
                        output_path = tts_engine.synthesize(text, voice_name, speed, pitch)
                        result[0] = output_path
                    except Exception as e:
                        error[0] = str(e)
                
                thread = threading.Thread(target=synthesize_worker)
                thread.start()
                
                # Wait for completion
                while thread.is_alive():
                    progress_dlg.Pulse()
                    wx.MilliSleep(100)
                
                progress_dlg.Destroy()
                
                if error[0]:
                    wx.MessageBox(f"Synthesis failed:\n{error[0]}", "Error", wx.ICON_ERROR)
                elif result[0]:
                    # Load synthesized audio into a new track
                    try:
                        # Edge TTS now creates WAV directly
                        audio = AudioSegment.from_wav(result[0])
                        
                        self.on_add_track(name=f"Edge TTS: {voice_name}", audio=audio)
                        self.SetStatusText(f"Edge TTS complete! Added to new track.")
                        wx.MessageBox("Speech synthesis complete!\nAudio added to a new track.", "Success", wx.ICON_INFORMATION)
                        
                        # Clean up temp file
                        try:
                            os.remove(result[0])
                        except:
                            pass
                    except Exception as e:
                        wx.MessageBox(f"Failed to load synthesized audio:\n{e}", "Error", wx.ICON_ERROR)
                        
            except Exception as e:
                progress_dlg.Destroy()
                wx.MessageBox(f"Edge TTS error:\n{e}", "Error", wx.ICON_ERROR)
        
        dlg.Destroy()

    def on_piper_tts(self, event):
        """Piper TTS dialog — on-device neural TTS"""
        try:
            from piper_tts_engine import PiperTTSEngine
        except ImportError:
            wx.MessageBox(
                "Piper TTS is not available.\n\n"
                "Install with: pip install piper-tts",
                "Feature Unavailable", wx.ICON_WARNING
            )
            return

        dlg = wx.Dialog(self, title="Piper TTS — On-device Neural", size=(550, 450))
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(dlg, label="Piper TTS (On-device Neural)")
        title.GetFont().SetPointSize(12)
        title.GetFont().SetWeight(wx.FONTWEIGHT_BOLD)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        info = wx.StaticText(dlg, label="High-quality neural TTS that runs locally — no internet required")
        vbox.Add(info, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        vbox.Add(wx.StaticText(dlg, label="Text to synthesize:"), 0, wx.ALL, 5)
        text_ctrl = wx.TextCtrl(dlg, style=wx.TE_MULTILINE, size=(-1, 100))
        text_ctrl.SetValue("Hello, this is a test of Piper TTS.")
        vbox.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        engine = PiperTTSEngine()
        voices = list(engine.get_all_voices().keys())
        voice_box = wx.BoxSizer(wx.HORIZONTAL)
        voice_box.Add(wx.StaticText(dlg, label="Voice:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        voice_choice = wx.Choice(dlg, choices=voices)
        voice_choice.SetSelection(0)
        voice_box.Add(voice_choice, 1, wx.ALL, 5)
        vbox.Add(voice_box, 0, wx.EXPAND | wx.ALL, 5)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        synthesize_btn = wx.Button(dlg, wx.ID_OK, label="Synthesize")
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, label="Cancel")
        btn_sizer.Add(synthesize_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        vbox.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        dlg.SetSizer(vbox)

        if dlg.ShowModal() == wx.ID_OK:
            text = text_ctrl.GetValue().strip()
            voice_name = voice_choice.GetStringSelection()
            if not text:
                wx.MessageBox("Please enter text to synthesize.", "Error", wx.ICON_ERROR)
                dlg.Destroy()
                return

            progress_dlg = wx.ProgressDialog("Piper TTS", "Synthesizing...", maximum=100,
                parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
            progress_dlg.Pulse()

            try:
                result = [None]
                error = [None]

                def synthesize_worker():
                    try:
                        tts_engine = PiperTTSEngine()
                        result[0] = tts_engine.synthesize(text, voice_name)
                    except Exception as e:
                        error[0] = str(e)

                thread = threading.Thread(target=synthesize_worker)
                thread.start()
                while thread.is_alive():
                    progress_dlg.Pulse()
                    wx.MilliSleep(100)
                progress_dlg.Destroy()

                if error[0]:
                    wx.MessageBox(f"Synthesis failed:\n{error[0]}", "Error", wx.ICON_ERROR)
                elif result[0]:
                    audio = AudioSegment.from_wav(result[0])
                    self.on_add_track(name=f"Piper TTS: {voice_name}", audio=audio)
                    self.SetStatusText(f"Piper TTS complete! Added to new track.")
                    wx.MessageBox("Speech synthesis complete!\nAudio added to a new track.",
                        "Success", wx.ICON_INFORMATION)
                    try:
                        os.remove(result[0])
                    except:
                        pass
            except Exception as e:
                progress_dlg.Destroy()
                wx.MessageBox(f"Piper TTS error:\n{e}", "Error", wx.ICON_ERROR)

        dlg.Destroy()

    def on_masakhane_tts(self, event):
        """Masakhane TTS dialog — African language TTS"""
        try:
            from masakhane_tts_engine import MasakhaneTTSEngine
        except ImportError:
            wx.MessageBox(
                "Masakhane TTS is not available.\n\n"
                "Install with: pip install masakhane-tts",
                "Feature Unavailable", wx.ICON_WARNING
            )
            return

        dlg = wx.Dialog(self, title="Masakhane TTS — African Languages", size=(550, 450))
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(dlg, label="Masakhane TTS (African Languages)")
        title.GetFont().SetPointSize(12)
        title.GetFont().SetWeight(wx.FONTWEIGHT_BOLD)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        info = wx.StaticText(dlg, label="Open-source TTS for isiZulu, isiXhosa, Yoruba, and more")
        vbox.Add(info, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        vbox.Add(wx.StaticText(dlg, label="Text to synthesize:"), 0, wx.ALL, 5)
        text_ctrl = wx.TextCtrl(dlg, style=wx.TE_MULTILINE, size=(-1, 100))
        text_ctrl.SetValue("Sawubona, lokhu ukuhlola i-Masakhane TTS.")
        vbox.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        engine = MasakhaneTTSEngine()
        voices = list(engine.get_all_voices().keys())
        voice_box = wx.BoxSizer(wx.HORIZONTAL)
        voice_box.Add(wx.StaticText(dlg, label="Language:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        voice_choice = wx.Choice(dlg, choices=voices)
        voice_choice.SetSelection(0)
        voice_box.Add(voice_choice, 1, wx.ALL, 5)
        vbox.Add(voice_box, 0, wx.EXPAND | wx.ALL, 5)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        synthesize_btn = wx.Button(dlg, wx.ID_OK, label="Synthesize")
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, label="Cancel")
        btn_sizer.Add(synthesize_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        vbox.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        dlg.SetSizer(vbox)

        if dlg.ShowModal() == wx.ID_OK:
            text = text_ctrl.GetValue().strip()
            voice_name = voice_choice.GetStringSelection()
            if not text:
                wx.MessageBox("Please enter text to synthesize.", "Error", wx.ICON_ERROR)
                dlg.Destroy()
                return

            progress_dlg = wx.ProgressDialog("Masakhane TTS", "Synthesizing...", maximum=100,
                parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
            progress_dlg.Pulse()

            try:
                result = [None]
                error = [None]

                def synthesize_worker():
                    try:
                        tts_engine = MasakhaneTTSEngine()
                        result[0] = tts_engine.synthesize(text, voice_name)
                    except Exception as e:
                        error[0] = str(e)

                thread = threading.Thread(target=synthesize_worker)
                thread.start()
                while thread.is_alive():
                    progress_dlg.Pulse()
                    wx.MilliSleep(100)
                progress_dlg.Destroy()

                if error[0]:
                    wx.MessageBox(f"Synthesis failed:\n{error[0]}", "Error", wx.ICON_ERROR)
                elif result[0]:
                    audio = AudioSegment.from_wav(result[0])
                    self.on_add_track(name=f"Masakhane TTS: {voice_name}", audio=audio)
                    self.SetStatusText(f"Masakhane TTS complete! Added to new track.")
                    wx.MessageBox("Speech synthesis complete!\nAudio added to a new track.",
                        "Success", wx.ICON_INFORMATION)
                    try:
                        os.remove(result[0])
                    except:
                        pass
            except Exception as e:
                progress_dlg.Destroy()
                wx.MessageBox(f"Masakhane TTS error:\n{e}", "Error", wx.ICON_ERROR)

        dlg.Destroy()

def main():
    app = wx.App()
    frame = SpeechCraftFrame()
    frame.Show()
    app.MainLoop()

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