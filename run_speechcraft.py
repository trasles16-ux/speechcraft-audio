#!/usr/bin/env python3
"""
SpeechCraft Launcher with Error Logging
Catches crashes and logs them to a file for accessibility.
"""

import sys
import traceback
import os
import time
from pathlib import Path
from datetime import datetime

ERROR_LOG_NAME = "speechcraft_error.log"

# A second log that traces every step of the launch so silent-close
# bugs (where the EXE exits without raising anything) leave a paper
# trail. Goes to %LOCALAPPDATA%\SpeechCraft\speechcraft_launch.log
# (not the CWD, which differs depending on how the EXE was launched).
LAUNCH_LOG_NAME = "speechcraft_launch.log"


def _launch_log_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "SpeechCraft" / LAUNCH_LOG_NAME
    return Path.home() / ".speechcraft" / LAUNCH_LOG_NAME


def _launch_log(msg: str) -> None:
    """Append a timestamped line to the launch trace log."""
    try:
        log_path = _launch_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


_launch_log("=== launch_speechcraft START pid=" + str(os.getpid()) + " ===")


def _write_error_log(log_file: Path, exc_type, exc_value, exc_tb) -> None:
    """Write a structured, accessible error log."""
    error_message = f"""
SpeechCraft Error Log
====================
Time: {datetime.now().isoformat()}

Error Type: {exc_type.__name__}
Error Message: {exc_value}

Full Traceback:
{''.join(traceback.format_exception(exc_type, exc_value, exc_tb))}

Troubleshooting Steps:
1. Check that all dependencies are installed:
   pip install -r requirements.txt

2. Make sure you are in the correct directory (the one containing
   run_speechcraft.py).

3. Try installing missing packages individually:
   pip install wxPython numpy scipy pydub librosa sounddevice soundfile

4. Check Python version (requires 3.11+):
   python --version

5. Use Help -> Report a Bug to file this crash automatically.
"""
    log_file.write_text(error_message, encoding="utf-8")
    # Also append to the launch trace so a startup failure appears
    # in the same log the user checks.
    _launch_log(f"EXCEPTION {exc_type.__name__}: {exc_value}")
    _launch_log(''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))


def launch_speechcraft() -> int:
    """Launch SpeechCraft with error handling and post-crash bug-report offer."""
    log_file = Path(ERROR_LOG_NAME)

    _launch_log("launch_speechcraft entered")
    print("Starting SpeechCraft...")

    # Personalise SpeechCraft wizard: shown automatically on first
    # launch (wizard_completed=False), skipped on later launches.
    # Re-openable from Help -> Personalise SpeechCraft any time.
    #
    # Replaces the v1.2.0 Core/Full onboarding dialog. The new
    # wizard gives the user per-feature choices (which is a richer
    # story than the binary Core/Full choice).
    try:
        # If the NSIS installer dropped a PreferredBundle.txt sidecar
        # (the edition the user picked at install time), merge it into
        # setup.json as preferred_bundle before the wizard opens.
        # Pure JSON merge - no wx dependency, safe to run headless.
        from prefs import merge_installer_edition
        _launch_log("merging installer edition sidecar")
        merge_installer_edition()
    except Exception as exc:
        _launch_log(f"merge_installer_edition failed: {exc!r}")

    try:
        from setup_wizard import should_show_wizard_on_launch, run_setup_wizard
        _launch_log(
            f"wizard_completed={should_show_wizard_on_launch() is False} "
            f"(False = show wizard)"
        )
        if should_show_wizard_on_launch():
            _launch_log("running setup wizard")
            completed, aborted = run_setup_wizard()
            _launch_log(
                f"wizard finished completed={completed} aborted={aborted}"
            )
            if completed:
                print("[OK] Personalise SpeechCraft completed")
            elif aborted:
                print("[INFO] Personalise SpeechCraft cancelled")
    except Exception as exc:
        _launch_log(f"setup wizard failed: {exc!r}")
        # If the wizard fails for any reason (no display, wx missing,
        # import error, etc.) we silently proceed. The user can still
        # open the wizard from Help -> Personalise SpeechCraft later.
        # Defaults are loaded from setup.json; missing file -> defaults.
        pass

    # Splash is shown BEFORE the rest of the launch sequence so the
    # user immediately sees an accessible loading surface. Each major
    # startup phase updates a checkmark on the splash via Splash.update().
    # If anything stalls, the user can read where we got stuck; if
    # everything succeeds, the splash dismisses when the main frame
    # is ready. The splash is wx-dependent, so it's only attempted when
    # wx is importable — bare `python run_speechcraft.py` from a
    # broken venv still falls through to the import-error path.
    splash = None
    try:
        _launch_log("importing wx + creating Splash")
        import wx  # noqa: F401  # smoke test: is wx usable at all?
        from splash import Splash
        splash = Splash()
        _launch_log("Splash created")
    except Exception as exc:
        _launch_log(f"Splash create failed: {exc!r}")
        # No splash possible (import error, headless, etc.). The plain
        # print() below still gives sighted devs something to look at.
        pass

    # Install the excepthook so crashes raised AFTER wx is initialised
    # are still captured. wx apps swallow uncaught exceptions inside
    # the main loop, so the launcher-level try/except only catches
    # import-time and main()-time failures.
    def _threaded_excepthook(args):
        _write_error_log(log_file, args.exc_type, args.exc_value, args.exc_traceback)
        sys.stderr.write(
            f"[SpeechCraft] Unhandled exception in thread; "
            f"see {log_file.absolute()}\n"
        )

    def _global_excepthook(exc_type, exc_value, exc_tb):
        _write_error_log(log_file, exc_type, exc_value, exc_tb)
        # Defer to the default handler so the user still sees a
        # traceback on stderr and pyttsx3 announcement.
        sys.__excepthook__(exc_type, exc_value, exc_tb)

        # If wx is alive, offer the in-app bug-report dialog. We
        # do this from the main thread; if the crash came from a
        # background thread, the launcher-level handler above
        # already wrote the log, so the user can relaunch and find
        # the log attached.
        try:
            import wx  # noqa: F401
        except Exception:
            return
        try:
            from bug_report_dialog import BugReportDialog
            from crash_submit import read_log_tail
        except Exception:
            return
        log_tail = read_log_tail(log_file)
        # wx.CallAfter to make sure we land on the UI thread.
        wx.CallAfter(_offer_bug_report, log_tail)

    sys.excepthook = _global_excepthook
    try:
        import threading
        threading.excepthook = _threaded_excepthook  # type: ignore[attr-defined]
    except Exception:
        # Python < 3.8 fallback (we require 3.11+, but be defensive)
        pass

    try:
        # Each milestone below maps 1:1 to a step the Splash announces.
        # If splash failed to create, the .update() calls are no-ops via
        # the getattr default.
        if splash is not None:
            splash.update("Loading user interface", "Importing wxPython")
        _launch_log("importing audio_editor.main")
        from audio_editor import main
        _launch_log("audio_editor.main imported, calling main()")
        print("[OK] SpeechCraft launched successfully")
        # …and we hand control straight to main(). The main frame will
        # appear behind the splash on the same screen, then the splash
        # auto-closes via the wx.App-level logic in audio_editor.main().
        result = main(splash=splash)
        _launch_log(f"main() returned {result!r}")
        return result
    except Exception as e:
        _launch_log(f"audio_editor.main raised: {e!r}")
        _write_error_log(log_file, type(e), e, e.__traceback__)
        print(f"\n[ERROR] Error logged to: {log_file.absolute()}")

        if splash is not None:
            try:
                splash.update("Loading user interface", f"Error: {e}")
            except Exception:
                pass

        # Announce error via speech if a TTS engine is available
        try:
            import pyttsx3
            tts = pyttsx3.init()
            tts.say(
                "SpeechCraft encountered an error. The error log was "
                "saved. You can launch the app again and use Help -> "
                "Report a Bug to file it automatically."
            )
            tts.runAndWait()
        except Exception:
            pass
        return 1

    return 0


def _offer_bug_report(log_tail: str | None) -> None:
    """Show the bug-report dialog after a crash. Runs on the UI thread."""
    import wx
    try:
        from bug_report_dialog import BugReportDialog
    except Exception:
        return
    try:
        app = wx.GetApp()
        if app is None:
            return
        # Parent to the top-level frame if available, else None.
        parent = None
        for window in app.GetTopLevelWindows():
            if window.IsShown():
                parent = window
                break
        dlg = BugReportDialog(parent, log_tail=log_tail)
        # Pre-fill the Title with a crash-style summary so the user
        # only has to type a description, not retype the whole thing.
        dlg.set_title("SpeechCraft crashed")
        dlg.show()
    except Exception:
        # Never let the post-crash offer itself crash the app.
        pass


if __name__ == "__main__":
    # Ensure wx is imported before main() — needed for the excepthook
    # fallback path to find it. audio_editor.main() imports wx itself.
    sys.exit(launch_speechcraft())
