"""
Piper TTS Engine for SpeechCraft Studio
Open-source, offline TTS with South African voice support
"""

import os
import tempfile
import subprocess
from typing import Optional, Dict

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

class PiperTTSEngine:
    """Wrapper for Piper TTS with South African voice support"""
    
    # Available SA voices (community trained)
    SA_VOICES = {
        "English SA (Female - Carina)": {
            "model": "en_ZA-carina-medium",
            "url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_ZA/carina/medium/en_ZA-carina-medium.onnx",
            "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_ZA/carina/medium/en_ZA-carina-medium.onnx.json"
        }
    }
    
    def __init__(self, models_dir: str = None):
        """
        Initialize Piper TTS Engine
        
        Args:
            models_dir: Directory to store downloaded models (default: ./piper_models)
        """
        if models_dir is None:
            models_dir = os.path.join(os.getcwd(), "piper_models")
        
        self.models_dir = models_dir
        os.makedirs(self.models_dir, exist_ok=True)
        
        # Check for piper executable
        self.piper_path = self._find_piper()
        if not self.piper_path:
            raise RuntimeError(
                "Piper executable not found. Download from:\n"
                "https://github.com/rhasspy/piper/releases\n"
                "Extract piper.exe to your PATH or current directory"
            )
    
    def _find_piper(self) -> Optional[str]:
        """Find piper executable"""
        # Check current directory
        if os.path.exists("piper.exe"):
            return os.path.abspath("piper.exe")
        
        # Check PATH
        try:
            result = subprocess.run(["piper", "--version"], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                return "piper"
        except:
            pass
        
        return None
    
    def _download_model(self, voice_name: str) -> tuple:
        """Download model and config if not exists"""
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests library required. Install: pip install requests")
        
        voice_info = self.SA_VOICES[voice_name]
        model_name = voice_info["model"]
        
        model_path = os.path.join(self.models_dir, f"{model_name}.onnx")
        config_path = os.path.join(self.models_dir, f"{model_name}.onnx.json")
        
        # Download model if needed
        if not os.path.exists(model_path):
            print(f"Downloading {model_name} model...")
            response = requests.get(voice_info["url"])
            response.raise_for_status()
            with open(model_path, "wb") as f:
                f.write(response.content)
            print("Model downloaded.")
        
        # Download config if needed
        if not os.path.exists(config_path):
            print(f"Downloading {model_name} config...")
            response = requests.get(voice_info["config_url"])
            response.raise_for_status()
            with open(config_path, "wb") as f:
                f.write(response.content)
            print("Config downloaded.")
        
        return model_path, config_path
    
    @staticmethod
    def get_voices() -> Dict[str, dict]:
        """Get available SA voices"""
        return PiperTTSEngine.SA_VOICES.copy()
    
    def synthesize(self, text: str, voice_name: str = "English SA (Female - Carina)",
                   speed: float = 1.0) -> str:
        """
        Synthesize text to speech using Piper TTS
        
        Args:
            text: Text to synthesize
            voice_name: Voice name from get_voices() keys
            speed: Speech speed (0.5 to 2.0, default 1.0)
        
        Returns:
            Path to generated audio file (WAV)
        """
        if not text.strip():
            raise ValueError("Text cannot be empty")
        
        if voice_name not in self.SA_VOICES:
            voice_name = "English SA (Female - Carina)"
        
        # Download model if needed
        model_path, config_path = self._download_model(voice_name)
        
        # Create temp output file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        output_path = temp_file.name
        temp_file.close()
        
        # Run piper
        try:
            cmd = [
                self.piper_path,
                "--model", model_path,
                "--config", config_path,
                "--output_file", output_path
            ]
            
            if speed != 1.0:
                cmd.extend(["--length_scale", str(1.0 / speed)])
            
            result = subprocess.run(
                cmd,
                input=text,
                text=True,
                capture_output=True,
                check=True
            )
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except:
                    pass
            raise Exception(f"Piper TTS failed: {e.stderr}")
        except Exception as e:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except:
                    pass
            raise e

# Test function
if __name__ == "__main__":
    print("Testing Piper TTS Engine...")
    
    try:
        engine = PiperTTSEngine()
        
        print("\nAvailable South African Voices:")
        for name in engine.get_voices().keys():
            print(f"  {name}")
        
        print("\nTesting synthesis...")
        output = engine.synthesize(
            "Hello, this is a test of Piper TTS with a South African voice.",
            "English SA (Female - Carina)"
        )
        print(f"Success! Audio saved to: {output}")
        
    except Exception as e:
        print(f"Error: {e}")
