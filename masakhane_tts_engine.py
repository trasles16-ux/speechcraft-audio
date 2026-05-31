"""
Masakhane TTS Engine for SpeechCraft Studio
Open-source African language TTS from Masakhane NLP
Supports South African languages: Zulu, Xhosa, Afrikaans
"""

import os
import tempfile
import torch
import soundfile as sf
from typing import Optional, Dict

try:
    from transformers import VitsModel, AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

class MasakhaneEngine:
    """Wrapper for Masakhane African language TTS"""
    
    # Masakhane models for SA languages
    SA_MODELS = {
        "Zulu (Female)": "Sunbird/sunbird-zu",
        "Xhosa (Female)": "Sunbird/sunbird-xh", 
        "Afrikaans (Female)": "Sunbird/sunbird-af",
        "Sesotho (Female)": "Sunbird/sunbird-st",
        "Northern Sotho (Female)": "Sunbird/sunbird-nso"
    }
    
    def __init__(self):
        if not TRANSFORMERS_AVAILABLE:
            raise ImportError("transformers library required. Install: pip install transformers")
        
        self.models = {}
        self.tokenizers = {}
    
    @staticmethod
    def get_voices() -> Dict[str, str]:
        """Get available SA language voices"""
        return MasakhaneEngine.SA_MODELS.copy()
    
    def _load_model(self, voice_name: str):
        """Load model and tokenizer if not cached"""
        if voice_name in self.models:
            return
        
        model_id = self.SA_MODELS[voice_name]
        print(f"Loading {voice_name} model from Masakhane...")
        
        try:
            self.models[voice_name] = VitsModel.from_pretrained(model_id)
            self.tokenizers[voice_name] = AutoTokenizer.from_pretrained(model_id)
            print(f"{voice_name} loaded successfully.")
        except Exception as e:
            raise Exception(f"Failed to load {voice_name}: {e}")
    
    def synthesize(self, text: str, voice_name: str = "Zulu (Female)", 
                   speed: float = 1.0) -> str:
        """
        Synthesize text to speech using Masakhane TTS
        
        Args:
            text: Text to synthesize (in the target language)
            voice_name: Voice name from get_voices() keys
            speed: Speech speed (not supported yet)
        
        Returns:
            Path to generated audio file (WAV)
        """
        if not text.strip():
            raise ValueError("Text cannot be empty")
        
        if voice_name not in self.SA_MODELS:
            voice_name = "Zulu (Female)"
        
        # Load model if needed
        self._load_model(voice_name)
        
        # Create temp output
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        output_path = temp_file.name
        temp_file.close()
        
        try:
            # Tokenize
            inputs = self.tokenizers[voice_name](text, return_tensors="pt")
            
            # Generate
            with torch.no_grad():
                output = self.models[voice_name](**inputs).waveform
            
            # Save
            audio = output.squeeze().cpu().numpy()
            sf.write(output_path, audio, samplerate=22050)
            
            return output_path
            
        except Exception as e:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except:
                    pass
            raise Exception(f"Synthesis failed: {e}")

# Test function
if __name__ == "__main__":
    print("Testing Masakhane TTS Engine...")
    
    if not TRANSFORMERS_AVAILABLE:
        print("ERROR: transformers not installed")
        print("Install with: pip install transformers")
    else:
        try:
            engine = MasakhaneEngine()
            
            print("\nAvailable South African Language Voices:")
            for name in engine.get_voices().keys():
                print(f"  {name}")
            
            print("\nTesting Zulu synthesis...")
            print("Text: Sawubona, lena ukuhlolwa kwe-TTS")
            output = engine.synthesize(
                "Sawubona, lena ukuhlolwa kwe-TTS",
                "Zulu (Female)"
            )
            print(f"Success! Audio saved to: {output}")
            
        except Exception as e:
            print(f"Error: {e}")
