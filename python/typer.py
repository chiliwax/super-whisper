"""Auto-typing and clipboard management for SuperWhisper."""

import platform
import time
from typing import Optional

# Cross-platform typing simulation
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

# Clipboard management
try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False


class AutoTyper:
    """Handles text output to the focused window."""
    
    def __init__(self, mode: str = "clipboard", typing_speed: float = 0.01):
        """
        Initialize AutoTyper.
        
        Args:
            mode: "clipboard" or "simulate_typing"
            typing_speed: Delay between characters for simulate_typing mode
        """
        self.mode = mode
        self.typing_speed = typing_speed
        self._system = platform.system()
    
    def type_text(self, text: str) -> bool:
        """
        Type or paste text into the focused window.
        
        Args:
            text: The text to output
            
        Returns:
            True if successful, False otherwise
        """
        if self.mode == "clipboard":
            return self._paste_from_clipboard(text)
        else:
            return self._simulate_typing(text)
    
    def _paste_from_clipboard(self, text: str) -> bool:
        """Copy text to clipboard and paste it."""
        if not PYPERCLIP_AVAILABLE:
            return False
        
        try:
            # Save current clipboard content
            old_clipboard = None
            try:
                old_clipboard = pyperclip.paste()
            except:
                pass
            
            # Copy new text to clipboard
            pyperclip.copy(text)
            
            # Small delay to ensure clipboard is ready
            time.sleep(0.05)
            
            # Simulate Cmd+V (macOS) or Ctrl+V (Windows/Linux)
            if PYAUTOGUI_AVAILABLE:
                if self._system == "Darwin":
                    pyautogui.hotkey('command', 'v')
                else:
                    pyautogui.hotkey('ctrl', 'v')
                
                # Small delay after paste
                time.sleep(0.1)
                
                # Optionally restore old clipboard
                # (commented out to avoid confusion)
                # if old_clipboard is not None:
                #     pyperclip.copy(old_clipboard)
                
                return True
            
            return False
        except Exception as e:
            print(f"Paste error: {e}")
            return False
    
    def _simulate_typing(self, text: str) -> bool:
        """Simulate keyboard typing character by character."""
        if not PYAUTOGUI_AVAILABLE:
            return False
        
        try:
            # Disable pyautogui's built-in pause
            pyautogui.PAUSE = 0
            
            for char in text:
                pyautogui.write(char, interval=0)
                if self.typing_speed > 0:
                    time.sleep(self.typing_speed)
            
            return True
        except Exception as e:
            print(f"Typing error: {e}")
            return False
    
    def set_mode(self, mode: str):
        """Change the output mode."""
        if mode in ("clipboard", "simulate_typing"):
            self.mode = mode
    
    def set_typing_speed(self, speed: float):
        """Set the typing speed for simulate_typing mode."""
        self.typing_speed = max(0, speed)
    
    @staticmethod
    def is_available() -> dict:
        """Check which features are available."""
        return {
            "clipboard": PYPERCLIP_AVAILABLE,
            "simulate_typing": PYAUTOGUI_AVAILABLE,
            "paste": PYPERCLIP_AVAILABLE and PYAUTOGUI_AVAILABLE
        }


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard without pasting."""
    if not PYPERCLIP_AVAILABLE:
        return False
    try:
        pyperclip.copy(text)
        return True
    except:
        return False


def get_clipboard() -> Optional[str]:
    """Get current clipboard content."""
    if not PYPERCLIP_AVAILABLE:
        return None
    try:
        return pyperclip.paste()
    except:
        return None
