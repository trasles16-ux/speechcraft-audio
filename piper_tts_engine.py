"""Piper TTS Engine for SpeechCraft Studio.

Wraps the Piper TTS executable. Model/voice files are managed by
:mod:`feature_manager` — this engine reads them from the dest dir the
feature manager installed, not from a hardcoded URL list.

Default voices are en_GB (Cori / Alan) from rhasspy/piper-voices.
South African voices do not exist publicly yet; en_GB is the working
default until the SA voice project lands.
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

    def __init__(self, models_dir: Optional[str] = None):
        """Initialise the engine.

        Args:
            models_dir: directory holding feature_manager-installed
                assets. Defaults to the feature_manager dest dir under
                PREFS_DIR.
        """
        if models_dir is None:
            models_dir = str(_default_models_dir())
        self.models_dir = Path(models_dir)

        self.piper_path = self._find_piper()
        if not self.piper_path:
            raise RuntimeError(
                "Piper executable not found. Download from:\n"
                "https://github.com/rhasspy/piper/releases\n"
                "Extract piper.exe to your PATH or current directory"
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

    def _resolve_voice_files(self, voice_name: str) -> tuple[Path, Path]:
        """Locate model + config files for a voice, downloading if needed.

        Returns (model_path, config_path). Raises if the asset was not
        downloadable or the download failed.
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

        # Otherwise download via feature_manager
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
    # Piper executable discovery (unchanged behaviour)
    # ------------------------------------------------------------------

    def _find_piper(self) -> Optional[str]:
        if os.path.exists("piper.exe"):
            return os.path.abspath("piper.exe")
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
                   speed: float = 1.0) -> str:
        """Synthesize text to a WAV file using Piper TTS.

        Returns the path to the generated WAV.
        """
        if not text.strip():
            raise ValueError("Text cannot be empty")

        if voice_name not in self.VOICES:
            voice_name = self.DEFAULT_VOICE

        model_path, config_path = self._resolve_voice_files(voice_name)

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
