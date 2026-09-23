"""Piper TTS Engine for SpeechCraft Studio.

Wraps the Piper TTS executable. Model/voice files AND the Piper
executable itself are managed by :mod:`feature_manager` — this engine
reads them from the dest dir the feature manager installed, not from a
hardcoded URL list.

Default voices are en_GB (Cori / Alan) from rhasspy/piper-voices.
South African voices do not exist publicly yet; en_GB is the working
default until the SA voice project lands.

Lazy install (v1.3.5): if Piper or a voice isn't on disk when the
engine is constructed or ``synthesize`` is called, the engine asks
:func:`dialogs.lazy_install.prompt_and_install` to prompt the user
and download with progress UI. Pass ``parent=None`` (the default) to
disable the prompt — useful for headless / test contexts.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

import feature_manager


def _default_models_dir() -> Path:
    """Where feature_manager installs Piper voices."""
    return feature_manager.DEFAULT_STATE_FILE.parent / "feature_assets"


class PiperTTSEngine:
    """Wrapper for Piper TTS, backed by feature_manager's voice registry."""

    #: Display-name -> (feature, asset_name) pairs served by feature_manager.
    VOICES: Dict[str, tuple] = {
        "English GB (Female — Cori)": ("piper_tts", "en_GB.cori"),
        "English GB (Male — Alan)":   ("piper_tts", "en_GB.alan"),
    }

    DEFAULT_VOICE = "English GB (Female — Cori)"

    def __init__(
        self,
        models_dir: Optional[str] = None,
        *,
        parent=None,
        allow_prompt: bool = True,
    ):
        """Initialise the engine.

        Args:
            models_dir: directory holding feature_manager-installed
                assets. Defaults to the feature_manager dest dir under
                PREFS_DIR.
            parent: wx.Window or None. Used as the parent for the
                lazy-install dialog. Defaults to None — call sites in
                the UI pass their main frame.
            allow_prompt: when False, the engine raises RuntimeError
                if Piper or a voice is missing instead of prompting.
                Tests use this; production callers leave it True.
        """
        if models_dir is None:
            models_dir = str(_default_models_dir())
        self.models_dir = Path(models_dir)
        # Stash for ``synthesize`` so a caller can construct the engine
        # once and synthesise many times without re-passing the parent.
        self._parent = parent
        self._allow_prompt = allow_prompt

        # Find or download piper.exe. Core installs don't bundle it;
        # the lazy-install flow offers to download on first use.
        self.piper_path = self._find_piper()
        if not self.piper_path:
            if not allow_prompt or parent is None:
                raise RuntimeError(
                    "Piper executable not found. Download from:\n"
                    "https://github.com/rhasspy/piper/releases\n"
                    "Extract piper.exe to your PATH or current directory"
                )
            # The Core build path: prompt and install.
            from dialogs.lazy_install import prompt_and_install
            installed = prompt_and_install(
                "piper_tts", "executable", parent=parent
            )
            if not installed:
                raise RuntimeError(
                    "Piper executable was not installed. Piper TTS "
                    "needs piper.exe to run; install it via Help → "
                    "Personalise SpeechCraft or download manually from "
                    "github.com/rhasspy/piper/releases."
                )
            self.piper_path = self._find_piper()
            if not self.piper_path:
                # The asset was downloaded but the executable lookup
                # still can't find it — bad state, surface a clear error.
                raise RuntimeError(
                    "Piper executable was downloaded but could not be "
                    "located on disk. Try Help → Personalise SpeechCraft "
                    "and check the Piper status."
                )

    # ------------------------------------------------------------------
    # Voice / asset plumbing
    # ------------------------------------------------------------------

    @staticmethod
    def get_voices() -> Dict[str, dict]:
        """List available voices, with a ``ready`` state per voice."""
        result: Dict[str, dict] = {}
        for name, (feature, asset) in PiperTTSEngine.VOICES.items():
            ready = feature_manager.is_ready(feature, asset)
            result[name] = {"feature": feature, "asset": asset, "ready": ready}
        return result

    def _resolve_voice_files(
        self,
        voice_name: str,
        *,
        parent=None,
        allow_prompt: bool = True,
    ) -> tuple[Path, Path]:
        """Locate model + config files for a voice, downloading if needed.

        Returns (model_path, config_path). Raises if the asset was not
        downloadable, the user declined the prompt, or the download
        failed.

        If ``allow_prompt`` is True and ``parent`` is not None, missing
        voices trigger the standard lazy-install flow: a Yes/No prompt
        and, on Yes, a progress dialog while :func:`feature_manager.ensure_ready`
        runs. Pass ``allow_prompt=False`` to fall back to the legacy
        silent-download behaviour (or just raise on missing assets).
        """
        if voice_name not in self.VOICES:
            voice_name = self.DEFAULT_VOICE
        feature, asset = self.VOICES[voice_name]

        asset_dir = self.models_dir / feature / asset
        model_path = asset_dir / "model"
        config_path = asset_dir / "config"

        # If already on disk, use it
        if model_path.exists() and config_path.exists():
            return model_path, config_path

        # Not on disk: silent download, prompt, or raise — depending on
        # how the engine was constructed and called.
        if allow_prompt and parent is not None:
            from dialogs.lazy_install import prompt_and_install
            ok = prompt_and_install(feature, asset, parent=parent)
            if not ok:
                raise RuntimeError(
                    f"Voice {voice_name!r} needs its model files, but "
                    "the install was cancelled or failed."
                )
        else:
            # Legacy silent path (no UI). Tests and headless callers use
            # this; production UI callers always pass a parent.
            if not feature_manager.is_downloadable(feature, asset):
                raise RuntimeError(
                    f"Voice {voice_name!r} has no downloadable assets yet."
                )
            feature_manager.ensure_ready(
                feature,
                asset,
                dest_dir=self.models_dir,
            )
        if not model_path.exists() or not config_path.exists():
            raise RuntimeError(
                f"Voice {voice_name!r} files missing after download: "
                f"{model_path} / {config_path}"
            )
        return model_path, config_path

    # ------------------------------------------------------------------
    # Piper executable discovery
    # ------------------------------------------------------------------

    def _find_piper(self) -> Optional[str]:
        # 1. Bundled / installed via feature_manager.
        from feature_manager import is_ready, asset_key
        if is_ready("piper_tts", "executable"):
            exe = (
                feature_manager.DEFAULT_STATE_FILE.parent
                / "feature_assets"
                / "piper_tts"
                / "executable"
                / "piper.exe"
            )
            if exe.exists():
                return str(exe)
        # 2. CWD (legacy behaviour — piper.exe next to SpeechCraft).
        if os.path.exists("piper.exe"):
            return os.path.abspath("piper.exe")
        # 3. PATH lookup.
        try:
            result = subprocess.run(
                ["piper", "--version"], capture_output=True, text=True
            )
            if result.returncode == 0:
                return "piper"
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def synthesize(self, text: str,
                   voice_name: str = DEFAULT_VOICE,
                   speed: float = 1.0,
                   *,
                   parent=None,
                   allow_prompt: bool = True) -> str:
        """Synthesize text to a WAV file using Piper TTS.

        Returns the path to the generated WAV.

        ``parent`` and ``allow_prompt`` are forwarded to
        :meth:`_resolve_voice_files` — when the voice isn't on disk
        and a wx parent is available, the user is prompted to download
        with progress UI. Pass ``allow_prompt=False`` to keep the
        legacy silent behaviour (test / headless callers).
        """
        if not text.strip():
            raise ValueError("Text cannot be empty")

        if voice_name not in self.VOICES:
            voice_name = self.DEFAULT_VOICE

        # Fall back to the engine's stored parent / prompt settings when
        # the caller didn't override.
        if parent is None:
            parent = getattr(self, "_parent", None)
        if parent is not None and allow_prompt:
            # Already constructed with a parent — re-use it.
            pass
        model_path, config_path = self._resolve_voice_files(
            voice_name,
            parent=parent,
            allow_prompt=allow_prompt,
        )

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        output_path = temp_file.name
        temp_file.close()

        try:
            cmd = [
                self.piper_path,
                "--model", str(model_path),
                "--config", str(config_path),
                "--output_file", output_path,
            ]
            if speed != 1.0:
                cmd.extend(["--length_scale", str(1.0 / speed)])

            subprocess.run(
                cmd,
                input=text,
                text=True,
                capture_output=True,
                check=True,
            )
            return output_path

        except Exception:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            raise


if __name__ == "__main__":
    print("Testing Piper TTS Engine...")
    try:
        engine = PiperTTSEngine()
        print("\nAvailable voices:")
        for name, info in engine.get_voices().items():
            print(f"  {name} — ready={info['ready']}")
        output = engine.synthesize("Hello, this is a Piper TTS test.")
        print(f"Success! Audio saved to: {output}")
    except Exception as e:
        print(f"Error: {e}")
