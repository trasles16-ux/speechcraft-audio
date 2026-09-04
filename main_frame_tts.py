"""TTS menu handlers for SpeechCraftFrame (mixin).

This file contains the two TTS-related menu handlers extracted from
``audio_editor.py``. They are provided as a **Python mixin** so they
can be added to ``SpeechCraftFrame`` by changing one line of the
class declaration instead of moving ~240 lines of code around.

Why a mixin, not a submodule import?
------------------------------------
A mixin is the standard Python pattern for "add these methods to a
class without creating an inheritance tree". ``SpeechCraftFrame``
keeps its own ``__init__`` and state; these two methods are stateless
from the mixin's perspective — they only call ``self.on_add_track``
and ``self.SetStatusText``, both of which are defined on the
concrete frame before any menu callback fires.

The contract (for future maintainers):
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
* ``self.on_add_track(name=, audio=)`` must be defined on the
  owning frame.
* ``self.SetStatusText(text)`` must be defined on the owning frame.
* No other frame state is read or written.

Usage in audio_editor.py:

    from main_frame_tts import TTSMenuMixin

    class SpeechCraftFrame(TTSMenuMixin, wx.Frame):
        ...

This is how PR #5 ties the extracted code back into the live app.
"""

import os
import threading

import wx
from pydub import AudioSegment


class TTSMenuMixin:
    """TTS menu handlers for SpeechCraftFrame.

    Mixed in via Python's MRO. ``self`` is always the owning
    ``SpeechCraftFrame`` instance; the mixin does not create or
    manage any state of its own.
    """

    def on_edge_tts(self, event):
        """Edge TTS dialog for free text-to-speech."""
        try:
            from edge_tts_engine import EdgeTTSEngine
        except ImportError:
            wx.MessageBox(
                "Edge TTS is not available.\n\n"
                "Install with: pip install edge-tts",
                "Feature Unavailable",
                wx.ICON_WARNING,
            )
            return

        dlg = wx.Dialog(self, title="Edge TTS - Free Text-to-Speech", size=(550, 450))
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(dlg, label="Edge TTS (Microsoft)")
        title_font = title.GetFont()
        title_font.SetPointSize(12)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        info = wx.StaticText(
            dlg, label="Free, high-quality text-to-speech with South African voices"
        )
        vbox.Add(info, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        vbox.Add(wx.StaticText(dlg, label="Text to synthesize:"), 0, wx.ALL, 5)
        text_ctrl = wx.TextCtrl(dlg, style=wx.TE_MULTILINE, size=(-1, 100))
        text_ctrl.SetValue("Hello, this is a test of Edge TTS.")
        vbox.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        engine = EdgeTTSEngine()
        voices = list(engine.get_all_voices().keys())

        voice_box = wx.BoxSizer(wx.HORIZONTAL)
        voice_box.Add(wx.StaticText(dlg, label="Voice:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        voice_choice = wx.Choice(dlg, choices=voices)
        voice_choice.SetName("Edge TTS voice")  # NVDA: announces the role instead of "unknown"
        voice_choice.SetSelection(0)  # Default to first SA voice
        voice_box.Add(voice_choice, 1, wx.ALL, 5)
        vbox.Add(voice_box, 0, wx.EXPAND | wx.ALL, 5)

        speed_box = wx.BoxSizer(wx.HORIZONTAL)
        speed_box.Add(wx.StaticText(dlg, label="Speed:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        speed_slider = wx.Slider(dlg, value=0, minValue=-50, maxValue=50, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        speed_box.Add(speed_slider, 1, wx.ALL, 5)
        vbox.Add(speed_box, 0, wx.EXPAND | wx.ALL, 5)

        pitch_box = wx.BoxSizer(wx.HORIZONTAL)
        pitch_box.Add(wx.StaticText(dlg, label="Pitch:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        pitch_slider = wx.Slider(dlg, value=0, minValue=-50, maxValue=50, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        pitch_box.Add(pitch_slider, 1, wx.ALL, 5)
        vbox.Add(pitch_box, 0, wx.EXPAND | wx.ALL, 5)

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

            progress_dlg = wx.ProgressDialog(
                "Edge TTS",
                "Synthesizing speech...",
                maximum=100,
                parent=self,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE,
            )
            progress_dlg.Pulse()

            try:
                result = [None]
                error = [None]

                def synthesize_worker():
                    try:
                        tts_engine = EdgeTTSEngine()
                        output_path = tts_engine.synthesize(text, voice_name, speed, pitch)
                        result[0] = output_path
                    except Exception as exc:
                        error[0] = str(exc)

                thread = threading.Thread(target=synthesize_worker)
                thread.start()

                while thread.is_alive():
                    progress_dlg.Pulse()
                    wx.MilliSleep(100)

                progress_dlg.Destroy()

                if error[0]:
                    wx.MessageBox(f"Synthesis failed:\n{error[0]}", "Error", wx.ICON_ERROR)
                elif result[0]:
                    try:
                        audio = AudioSegment.from_wav(result[0])
                        self.on_add_track(name=f"Edge TTS: {voice_name}", audio=audio)
                        self.SetStatusText("Edge TTS complete! Added to new track.")
                        wx.MessageBox(
                            "Speech synthesis complete!\nAudio added to a new track.",
                            "Success",
                            wx.ICON_INFORMATION,
                        )
                        try:
                            os.remove(result[0])
                        except OSError:
                            pass
                    except Exception as exc:
                        wx.MessageBox(f"Failed to load synthesized audio:\n{exc}", "Error", wx.ICON_ERROR)

            except Exception as exc:
                progress_dlg.Destroy()
                wx.MessageBox(f"Edge TTS error:\n{exc}", "Error", wx.ICON_ERROR)

        dlg.Destroy()

    def on_piper_tts(self, event):
        """Piper TTS dialog — on-device neural TTS."""
        try:
            from piper_tts_engine import PiperTTSEngine
        except ImportError:
            wx.MessageBox(
                "Piper TTS is not available.\n\n"
                "Install with: pip install piper-tts",
                "Feature Unavailable",
                wx.ICON_WARNING,
            )
            return

        # Validate engine before opening the dialog so a missing piper.exe
        # surfaces as a clear message instead of crashing the dialog mid-build.
        try:
            PiperTTSEngine()
        except RuntimeError as exc:
            wx.MessageBox(str(exc), "Piper TTS — Setup Error", wx.ICON_ERROR)
            return

        dlg = wx.Dialog(self, title="Piper TTS — On-device Neural", size=(550, 450))
        vbox = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(dlg, label="Piper TTS (On-device Neural)")
        title.GetFont().SetPointSize(12)
        title.GetFont().SetWeight(wx.FONTWEIGHT_BOLD)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        info = wx.StaticText(
            dlg, label="High-quality neural TTS that runs locally — no internet required"
        )
        vbox.Add(info, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        vbox.Add(wx.StaticText(dlg, label="Text to synthesize:"), 0, wx.ALL, 5)
        text_ctrl = wx.TextCtrl(dlg, style=wx.TE_MULTILINE, size=(-1, 100))
        text_ctrl.SetValue("Hello, this is a test of Piper TTS.")
        vbox.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        voices = list(PiperTTSEngine.get_voices().keys())
        voice_box = wx.BoxSizer(wx.HORIZONTAL)
        voice_box.Add(wx.StaticText(dlg, label="Voice:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        voice_choice = wx.Choice(dlg, choices=voices)
        voice_choice.SetName("Piper voice")  # NVDA: announces "Piper voice list" instead of "unknown"
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

            progress_dlg = wx.ProgressDialog(
                "Piper TTS",
                "Synthesizing...",
                maximum=100,
                parent=self,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE,
            )
            progress_dlg.Pulse()

            try:
                result = [None]
                error = [None]

                def synthesize_worker():
                    try:
                        tts_engine = PiperTTSEngine()
                        result[0] = tts_engine.synthesize(text, voice_name)
                    except Exception as exc:
                        error[0] = str(exc)

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
                    self.SetStatusText("Piper TTS complete! Added to new track.")
                    wx.MessageBox(
                        "Speech synthesis complete!\nAudio added to a new track.",
                        "Success",
                        wx.ICON_INFORMATION,
                    )
                    try:
                        os.remove(result[0])
                    except OSError:
                        pass
            except Exception as exc:
                progress_dlg.Destroy()
                wx.MessageBox(f"Piper TTS error:\n{exc}", "Error", wx.ICON_ERROR)

        dlg.Destroy()
