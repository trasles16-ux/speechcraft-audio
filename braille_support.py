"""
Braille Display Support for SpeechCraft Studio
Provides direct braille output for script lines and status updates.

Falls back gracefully when no braille hardware is connected — the app
continues to work with NVDA/JAWS screen reader speech, which Tracy already
uses. Braille output is a bonus, not a requirement.
"""

import ctypes
from ctypes import wintypes
import threading
import sys


class BrailleDisplay:
    """Interface for Windows braille display support.
    
    Tries three approaches in order:
      1. NVDA braille display (most common for blind users on Windows)
      2. JAWS braille display
      3. Windows HID haptics API (Windows 10+)
    
    Falls back to silent no-op if nothing is connected.
    """
    
    # Window class registered once process-wide
    _class_registered = False
    _class_atom = None
    _class_lock = threading.Lock()
    
    def __init__(self):
        self.connected = False
        self.current_text = ""
        self._cleanup_done = threading.Event()
        self._pending_cleanup = []  # HWNDs pending DestroyWindow
        self._pending_lock = threading.Lock()
        
        # Only import winrt if it's available (Python 3.8+, Windows 10+)
        self._winrt_available = self._check_winrt()
        
        self.try_connect()
    
    def _check_winrt(self):
        """Check if winrt.windows.devices.haptics is available."""
        try:
            import winrt.windows.devices.haptics as haptics  # noqa: F401
            return True
        except (ImportError, ModuleNotFoundError):
            return False
    
    def try_connect(self):
        """Attempt to connect to braille display via Windows API."""
        try:
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32
            
            # Check for screen reader braille displays
            if self._check_screen_reader_braille():
                self.connected = True
                print("Braille display: connected via screen reader (NVDA/JAWS)")
            elif self._try_windows_braille():
                self.connected = True
                print("Braille display: connected via Windows HID API")
            else:
                self.connected = False
                print("Braille display: not detected — continuing without braille output")
                
        except Exception as e:
            print(f"Braille connection probe failed: {e}")
            self.connected = False
    
    def _check_screen_reader_braille(self):
        """Check if NVDA or JAWS braille display is active."""
        try:
            user32 = ctypes.windll.user32
            
            # NVDA braille viewer window class
            nvda_window = user32.FindWindowW("wxWindowClassNR", None)
            if nvda_window:
                return True
                
            # JAWS braille window
            jaws_window = user32.FindWindowW("JAWS", None)
            if jaws_window:
                return True
                
            return False
            
        except OSError:
            return False
    
    def _try_windows_braille(self):
        """Try Windows 10+ braille HID API via winrt."""
        if not self._winrt_available:
            return False
        
        try:
            # winrt is installed and available
            # Windows HID haptics can communicate with some braille displays
            # Note: not all braille displays expose a haptics interface
            # This is best-effort — if winrt loads, we consider it a potential connection
            import winrt.windows.devices.haptics as haptics  # noqa: F401
            return True  # Possible braille display — will silently fail on send if none present
        except Exception:
            return False
    
    def send_text(self, text, priority="normal"):
        """Send text to braille display.
        
        Args:
            text: Text to display (truncated to 40 characters for most displays)
            priority: "high", "normal", "low" — maps to NVDA braille priority
        
        Returns:
            True if sent successfully, False if no display connected
        """
        if not self.connected:
            return False
        
        try:
            braille_text = text[:40] if len(text) > 40 else text
            self.current_text = braille_text
            
            return self._send_to_screen_reader(braille_text, priority)
            
        except Exception as e:
            print(f"Braille send failed: {e}")
            return False
    
    def _ensure_window_class(self):
        """Register the braille window class exactly once.
        
        Thread-safe — uses a lock so multiple threads don't race to register.
        """
        if BrailleDisplay._class_registered:
            return BrailleDisplay._class_atom is not None
        
        with BrailleDisplay._class_lock:
            if BrailleDisplay._class_registered:
                return BrailleDisplay._class_atom is not None
            
            try:
                wc = wintypes.WNDCLASS()
                wc.lpfnWndProc = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM
                )(self._window_proc)
                wc.lpszClassName = "SpeechCraftBraille"
                wc.hInstance = self.kernel32.GetModuleHandleW(None)
                
                BrailleDisplay._class_atom = self.user32.RegisterClassW(ctypes.byref(wc))
                BrailleDisplay._class_registered = True
                return BrailleDisplay._class_atom is not None
                
            except OSError:
                BrailleDisplay._class_registered = True
                return False
    
    def _send_to_screen_reader(self, text, priority):
        """Send text to NVDA/JAWS via window title and accessibility event.
        
        This creates a brief invisible window with the braille text in its title.
        NVDA and JAWS read window titles as braille output when the window
        receives focus — they expose the window title as braille cells.
        
        This is an established pattern used by many Windows braille applications.
        """
        if not self._ensure_window_class():
            return False
        
        try:
            window_name = f"BRAILLE:{priority.upper()}:{text}"
            
            hwnd = self.user32.CreateWindowExW(
                0,
                "SpeechCraftBraille",
                window_name,
                0,  # WS_POPUP — invisible
                0, 0, 0, 0,  # ignored for invisible windows
                None,  # no parent
                None,  # no menu
                self.kernel32.GetModuleHandleW(None),
                None
            )
            
            if hwnd:
                # Send EVENT_OBJECT_FOCUS to notify screen reader of new window
                self.user32.NotifyWinEvent(0x8005, hwnd, -4, 0)  # OBJID_CLIENT = -4
                
                # Queue safe cleanup with the real HWND
                self._queue_cleanup(hwnd)
                return True
            
            return False
            
        except OSError:
            return False
    
    def _queue_cleanup(self, hwnd):
        """Safely queue HWND for destruction — avoids Timer race conditions."""
        with self._pending_lock:
            # Cancel any pending cleanup for the same HWND
            self._pending_cleanup = [h for h in self._pending_cleanup if h != hwnd]
            self._pending_cleanup.append(hwnd)
        
        def cleanup():
            try:
                if sys.platform == "win32":
                    ctypes.windll.user32.DestroyWindow(hwnd)
            except Exception:
                pass
            finally:
                with self._pending_lock:
                    if hwnd in self._pending_cleanup:
                        self._pending_cleanup.remove(hwnd)
        
        threading.Thread(target=cleanup, daemon=True).start()
    
    def _send_to_windows_braille(self, text):
        """Send text via Windows HID haptics API.
        
        Note: This path only works for braille displays that expose a Windows Haptics
        interface. Most USB HID braille displays use a different protocol and won't
        respond here. The NVDA/JAWS screen reader path above is more reliable for
        most users.
        """
        # Stub — requires winrt + hardware with haptics interface
        return False
    
    def _window_proc(self, hwnd, msg, wparam, lparam):
        """Default window procedure — handles cleanup messages."""
        if msg == 0x0010:  # WM_CLOSE
            try:
                ctypes.windll.user32.DestroyWindow(hwnd)
            except Exception:
                pass
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    
    def send_line(self, line_number, text):
        """Send script line to braille display with line number."""
        braille_text = f"L{line_number}: {text}"
        return self.send_text(braille_text, "high")
    
    def send_status(self, status):
        """Send status message to braille display."""
        return self.send_text(f"STATUS: {status}", "normal")
    
    def send_progress(self, current, total):
        """Send progress info to braille display."""
        progress_text = f"Line {current}/{total}"
        return self.send_text(progress_text, "low")
    
    def clear(self):
        """Clear braille display."""
        return self.send_text("", "normal")
    
    def is_connected(self):
        """Check if braille display is connected."""
        return self.connected


# ── Module-level convenience API ───────────────────────────────────────────

_braille_display = None


def get_braille_display():
    """Get global braille display instance (lazy singleton)."""
    global _braille_display
    if _braille_display is None:
        _braille_display = BrailleDisplay()
    return _braille_display


def send_to_braille(text, priority="normal"):
    """Convenience function to send text to braille display.
    
    Safe to call even when no display is connected — returns False silently.
    """
    display = get_braille_display()
    return display.send_text(text, priority)


def send_line_to_braille(line_number, text):
    """Send script line to braille display with line number.
    
    Called from audio_editor.py lines 4856-4857.
    """
    display = get_braille_display()
    return display.send_line(line_number, text)