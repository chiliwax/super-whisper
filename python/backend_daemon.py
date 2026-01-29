#!/usr/bin/env python3
"""
Persistent backend daemon for SuperWhisper.
Keeps the model loaded in memory for fast transcription.

Communication via stdin/stdout JSON.
Commands:
  {"cmd": "load_model", "model": "nemo-parakeet-tdt-0.6b-v3"}
  {"cmd": "start_recording", "device": 2}
  {"cmd": "stop_recording"}
  {"cmd": "transcribe", "output": "clipboard"}
  {"cmd": "quit"}
"""

import sys
import json
import os
import tempfile
import time
import threading
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

# Global state
recording = False
audio_data = []
stream = None
current_model = None
current_model_name = None
SAMPLE_RATE = 16000


def send_response(data):
    """Send JSON response to stdout."""
    print(json.dumps(data), flush=True)


def send_error(message):
    """Send error response."""
    send_response({"error": message})


def load_model(model_name):
    """Load ASR model into memory."""
    global current_model, current_model_name
    
    if current_model_name == model_name and current_model is not None:
        send_response({"status": "model_already_loaded", "model": model_name})
        return True
    
    try:
        import onnx_asr
        send_response({"status": "loading_model", "model": model_name})
        current_model = onnx_asr.load_model(model_name, providers=["CPUExecutionProvider"])
        current_model_name = model_name
        send_response({"status": "model_loaded", "model": model_name})
        return True
    except Exception as e:
        send_error(f"Failed to load model: {e}")
        return False


def start_recording(device_id=None):
    """Start recording audio."""
    global recording, audio_data, stream
    
    if recording:
        send_error("Already recording")
        return False
    
    recording = True
    audio_data = []
    last_level_time = [0]
    
    def callback(indata, frames, time_info, status):
        if recording:
            audio_data.append(indata.copy())
            
            # Send audio level every 100ms
            current_time = time.time()
            if current_time - last_level_time[0] > 0.1:
                level = float(np.abs(indata).mean())
                normalized = min(1.0, level * 50)
                send_response({"audio_level": normalized})
                last_level_time[0] = current_time
    
    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            device=device_id,
            callback=callback
        )
        stream.start()
        send_response({"status": "recording_started", "device": device_id})
        return True
    except Exception as e:
        recording = False
        send_error(f"Failed to start recording: {e}")
        return False


def stop_recording():
    """Stop recording and return audio data."""
    global recording, audio_data, stream
    
    if not recording:
        send_error("Not recording")
        return None
    
    recording = False
    
    if stream:
        stream.stop()
        stream.close()
        stream = None
    
    if not audio_data:
        return None
    
    # Combine audio chunks
    audio = np.concatenate(audio_data, axis=0)
    audio_int16 = (audio * 32767).astype(np.int16)
    
    duration = len(audio_int16) / SAMPLE_RATE
    send_response({"status": "recording_stopped", "duration": duration})
    
    return audio_int16


def transcribe(audio_int16, output_mode="json"):
    """Transcribe audio using loaded model."""
    global current_model
    
    if current_model is None:
        send_error("No model loaded")
        return None
    
    # Check audio level
    audio_level = np.abs(audio_int16).mean()
    if audio_level < 100:
        send_response({"error": "Audio too quiet", "level": float(audio_level)})
        return None
    
    send_response({"status": "transcribing"})
    
    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav.write(f.name, SAMPLE_RATE, audio_int16)
        temp_path = f.name
    
    try:
        # Transcribe with already-loaded model (FAST!)
        start_time = time.time()
        result = current_model.recognize(temp_path)
        elapsed = time.time() - start_time
        
        if result and result.strip():
            text = result.strip()
            response = {
                "text": text,
                "duration": len(audio_int16) / SAMPLE_RATE,
                "transcription_time": elapsed
            }
            
            # Handle output mode
            if output_mode == 'clipboard':
                if copy_to_clipboard(text):
                    response['copied'] = True
            elif output_mode == 'simulate_typing':
                if type_text(text):
                    response['typed'] = True
                else:
                    copy_to_clipboard(text)
                    response['copied'] = True
                    response['typing_failed'] = True
            
            send_response(response)
            return text
        else:
            send_response({"error": "No speech detected", "duration": len(audio_int16) / SAMPLE_RATE})
            return None
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass


def copy_to_clipboard(text):
    """Copy text to clipboard."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception as e:
        return False


def type_text(text):
    """Simulate typing/pasting text with full Unicode support."""
    import subprocess
    import platform
    
    system = platform.system()
    
    try:
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.05)
        
        if system == 'Darwin':
            subprocess.run([
                'osascript', '-e',
                'tell application "System Events" to keystroke "v" using command down'
            ], check=True)
            return True
        elif system == 'Windows':
            try:
                import pyautogui
                pyautogui.hotkey('ctrl', 'v')
                return True
            except:
                subprocess.run([
                    'powershell', '-command',
                    '[System.Windows.Forms.SendKeys]::SendWait("^v")'
                ], check=True)
                return True
        else:
            try:
                subprocess.run(['xdotool', 'key', 'ctrl+v'], check=True)
                return True
            except FileNotFoundError:
                try:
                    import pyautogui
                    pyautogui.hotkey('ctrl', 'v')
                    return True
                except:
                    pass
            return False
    except Exception as e:
        return False


def handle_command(cmd_data):
    """Handle a command from stdin."""
    global audio_data
    
    cmd = cmd_data.get('cmd')
    
    if cmd == 'load_model':
        model = cmd_data.get('model', 'nemo-parakeet-tdt-0.6b-v3')
        load_model(model)
    
    elif cmd == 'start_recording':
        device = cmd_data.get('device')
        start_recording(device)
    
    elif cmd == 'stop_recording':
        audio = stop_recording()
        if audio is not None:
            audio_data_cache = audio  # Store for transcribe
            # Store in global for later transcribe
            handle_command._last_audio = audio
    
    elif cmd == 'transcribe':
        output_mode = cmd_data.get('output', 'json')
        audio = getattr(handle_command, '_last_audio', None)
        if audio is not None:
            transcribe(audio, output_mode)
            handle_command._last_audio = None
        else:
            send_error("No audio to transcribe")
    
    elif cmd == 'stop_and_transcribe':
        # Combined command for faster response
        output_mode = cmd_data.get('output', 'json')
        audio = stop_recording()
        if audio is not None:
            transcribe(audio, output_mode)
    
    elif cmd == 'ping':
        send_response({"status": "pong", "model_loaded": current_model is not None})
    
    elif cmd == 'quit':
        send_response({"status": "quitting"})
        sys.exit(0)
    
    else:
        send_error(f"Unknown command: {cmd}")


def main():
    """Main loop - read commands from stdin."""
    send_response({"status": "ready", "pid": os.getpid()})
    
    # Handle signals
    def signal_handler(sig, frame):
        global recording
        recording = False
        send_response({"status": "interrupted"})
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Main command loop
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            line = line.strip()
            if not line:
                continue
            
            try:
                cmd_data = json.loads(line)
                handle_command(cmd_data)
            except json.JSONDecodeError as e:
                send_error(f"Invalid JSON: {e}")
        
        except EOFError:
            break
        except Exception as e:
            send_error(f"Error: {e}")
    
    send_response({"status": "exiting"})


if __name__ == '__main__':
    main()
