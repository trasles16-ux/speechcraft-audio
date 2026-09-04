"""Effect, preset, and batch-processing dialogs extracted from audio_editor.py.

Pattern: these are self-contained ``wx.Dialog`` subclasses that do not
reference ``SpeechCraftFrame`` or its workspace. They were the first
extraction target (PR #3 of the audio_editor.py decomposition plan)
because they have zero coupling to the main frame and can move
verbatim with only an import update.

Why a ``dialogs/`` subdir and not flat?
---------------------------------------
The decomposition plan extracts four kinds of concerns into four
locations:

- ``dialogs/effects_dialogs.py`` -- effect / preset / batch dialogs
  (this file)
- ``dialogs/recording_dialogs.py`` -- recording + studio dialogs
- ``main_frame_tts.py`` -- TTS menu handlers (mixin)
- ``main_frame_effects.py`` -- effects menu handlers (mixin)

A ``dialogs/`` subdir keeps the modal dialogs (which have no frame
state) separate from the frame mixins (which do). Future dialogs
should go in ``dialogs/``; future menu handlers should go in
``main_frame_<feature>.py``.
"""

import os
from pathlib import Path

import numpy as np
import sounddevice as sd
import wx
from pydub import AudioSegment

import audio_effects
import batch_processor
import config
import preset_manager

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

        self.right_sizer.Layout()
        self.right_sizer.Fit(self.right_panel)
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
        self.right_sizer.Layout()
        self.right_sizer.Fit(self.right_panel)
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
        self.right_sizer.Layout()
        self.right_sizer.Fit(self.right_panel)

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
        self.right_sizer.Layout()
        self.right_sizer.Fit(self.right_panel)
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
        """Return dict of {freq: gain_db} for all bands."""
        if self.show_advanced:
            return {freq: self.band_sliders[label].GetValue()
                    for freq, label in zip(audio_effects.Equalizer.BAND_FREQUENCIES,
                                           audio_effects.Equalizer.BAND_LABELS)}
        else:
            # Use same logic as _update_display to get bands
            if self.selected_preset in config.EQ_PRESETS:
                return {freq: gain for freq, gain in config.EQ_PRESETS[self.selected_preset]["bands"]}
            else:
                eq, _, _ = preset_manager.load_custom_presets()
                bands = eq.get(self.selected_preset, {}).get("bands", [(0, 0)] * 5)
                return {freq: gain for freq, gain in bands}

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
        self.file_list = wx.ListBox(panel, style=wx.LB_SINGLE)
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

        if self.preset_sizer.GetStaticBox().GetParent() is not None:
            self.preset_sizer.GetStaticBox().GetParent().GetSizer().Fit(self.preset_sizer.GetStaticBox())
        self.Layout()
        sizer = self.GetSizer()
        if sizer is not None:
            sizer.Fit(self)

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


