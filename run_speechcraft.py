#!/usr/bin/env python3
"""
SpeechCraft Launcher with Error Logging
Catches crashes and logs them to a file for accessibility
"""

import sys
import traceback
from pathlib import Path
from datetime import datetime

def launch_speechcraft():
    """Launch SpeechCraft with error handling"""
    
    log_file = Path("speechcraft_error.log")
    
    try:
        print("Starting SpeechCraft...")
        
        # Import and run the main app
        from audio_editor import main
        
        print("[OK] SpeechCraft launched successfully")
        main()
        
    except Exception as e:
        # Capture the full error
        error_message = f"""
SpeechCraft Error Log
====================
Time: {datetime.now().isoformat()}

Error Type: {type(e).__name__}
Error Message: {str(e)}

Full Traceback:
{traceback.format_exc()}

Troubleshooting Steps:
1. Check that all dependencies are installed:
   pip install -r requirements.txt

2. Make sure you're in the correct directory:
   cd c:\\python\\breath_smoothing

3. Try installing missing packages individually:
   pip install PyQt6 PyQt6-multimedia pydub librosa

4. Check Python version (requires 3.8+):
   python --version
"""
        
        # Write to log file
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(error_message)
        
        # Also print to console
        print(error_message)
        print(f"\n[ERROR] Error logged to: {log_file.absolute()}")
        # Announce error via speech
        try:
            import pyttsx3
            tts = pyttsx3.init()
            tts.say("SpeechCraft encountered an error. Please check the log file for details.")
            tts.runAndWait()
        except Exception:
            pass
        # Return error code
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = launch_speechcraft()
    sys.exit(exit_code)
