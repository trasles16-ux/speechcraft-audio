import time
import os
import traceback
from pywinauto.application import Application
from pywinauto import Desktop
try:
    import pyttsx3
    tts = pyttsx3.init()
    def speak(text):
        tts.say(text)
        tts.runAndWait()
except Exception:
    def speak(text):
        pass

# Path to your SpeechCraft launcher (update if needed)
APP_PATH = r"c:\python\breath_smoothing\audio_editor.py"
PYTHON_EXE = r"python"  # Use full path if needed
LOG_FILE = "accessibility_log.txt"

def log_error(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write("ERROR: " + msg + "\n")

try:
    speak("Launching SpeechCraft for accessibility scan.")
    app = Application(backend="uia").start(f'{PYTHON_EXE} "{APP_PATH}"')
    speak("Waiting for main window.")
    main_win = None
    for _ in range(30):
        try:
            main_win = app.window(title_re=".*SpeechCraft.*|.*Audio Editor.*|.*breath_smoothing.*")
            if main_win.exists():
                break
        except Exception:
            pass
        time.sleep(1)
    if not main_win or not main_win.exists():
        speak("Main window not found. Exiting.")
        log_error("Main window not found.")
        exit(1)
    main_win.set_focus()
    speak("Scanning controls for accessibility.")
    def log_control_info(ctrl, log, indent=0):
        props = ctrl.get_properties()
        log.write("  " * indent + f"Name: {props.get('name', '')}\n")
        log.write("  " * indent + f"Type: {props.get('control_type', '')}\n")
        log.write("  " * indent + f"Focusable: {props.get('is_keyboard_focusable', '')}\n")
        log.write("  " * indent + f"Shortcut: {props.get('access_key', '')}\n")
        log.write("  " * indent + f"Visible: {props.get('visible', '')}\n")
        log.write("  " * indent + f"Enabled: {props.get('enabled', '')}\n")
        log.write("  " * indent + "---\n")
        # Recursively log children
        for child in ctrl.children():
            log_control_info(child, log, indent + 1)
    with open(LOG_FILE, "w", encoding="utf-8") as log:
        log.write(f"Accessibility scan for {APP_PATH}\n\n")
        log_control_info(main_win, log)
    speak("Accessibility scan complete. Log file created.")
    time.sleep(2)
    main_win.close()
except Exception as e:
    speak("An error occurred. See log file for details.")
    log_error(traceback.format_exc())
