#!/usr/bin/env python3
"""
Quick recording and transcription script for SuperWhisper.
Called by the Tauri app to perform the actual work.

Usage:
    python record_and_transcribe.py --start --device 2
    python record_and_transcribe.py --stop --output clipboard
"""

import sys
import json
import os
import tempfile
import time
import threading
import signal

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

# Global state
recording = False
audio_data = []
stream = None
SAMPLE_RATE = 16000

def record_audio(device_id=None, duration=None, send_levels=True):
    """Record audio from microphone."""
    global recording, audio_data, stream
    
    recording = True
    audio_data = []
    last_level_time = [0]  # Use list to allow modification in nested function
    
    def callback(indata, frames, time_info, status):
        if recording:
            audio_data.append(indata.copy())
            
            # Send audio level every 100ms
            if send_levels:
                current_time = time.time()
                if current_time - last_level_time[0] > 0.1:
                    level = float(np.abs(indata).mean())
                    # Amplify and normalize (0-1 range)
                    normalized = min(1.0, level * 50)
                    print(json.dumps({"audio_level": normalized}), flush=True)
                    last_level_time[0] = current_time
    
    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            device=device_id,
            callback=callback
        )
        stream.start()
        
        if duration:
            time.sleep(duration)
            stop_recording()
        else:
            # Wait for stop signal
            while recording:
                time.sleep(0.1)
        
        return True
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return False

def stop_recording():
    """Stop recording and return audio data."""
    global recording, audio_data, stream
    
    recording = False
    
    if stream:
        stream.stop()
        stream.close()
        stream = None
    
    if not audio_data:
        return None
    
    # Combine audio chunks
    audio = np.concatenate(audio_data, axis=0)
    # Convert to int16
    audio_int16 = (audio * 32767).astype(np.int16)
    return audio_int16

def transcribe_audio(audio_int16, model_name="nemo-parakeet-tdt-0.6b-v3", use_vad=False):
    """Transcribe audio using onnx_asr."""
    import onnx_asr
    
    # Check audio level
    audio_level = np.abs(audio_int16).mean()
    if audio_level < 100:
        return {"error": "Audio too quiet", "level": float(audio_level)}
    
    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav.write(f.name, SAMPLE_RATE, audio_int16)
        temp_path = f.name
    
    try:
        # Load model
        model = onnx_asr.load_model(model_name, providers=["CPUExecutionProvider"])
        
        # Transcribe
        result = model.recognize(temp_path)
        
        if result and result.strip():
            return {"text": result.strip(), "duration": len(audio_int16) / SAMPLE_RATE}
        else:
            return {"error": "No speech detected", "duration": len(audio_int16) / SAMPLE_RATE}
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except:
            pass

def copy_to_clipboard(text):
    """Copy text to clipboard."""
    import pyperclip
    pyperclip.copy(text)
    return True

def type_text(text):
    """Simulate typing/pasting text with full Unicode support (cross-platform)."""
    import subprocess
    import platform
    
    system = platform.system()
    
    try:
        import pyperclip
        
        # Copy text to clipboard (works on all platforms)
        pyperclip.copy(text)
        time.sleep(0.05)
        
        if system == 'Darwin':
            # macOS: Use osascript for Cmd+V
            subprocess.run([
                'osascript', '-e',
                'tell application "System Events" to keystroke "v" using command down'
            ], check=True)
            return True
            
        elif system == 'Windows':
            # Windows: Use PowerShell or pyautogui for Ctrl+V
            try:
                import pyautogui
                pyautogui.hotkey('ctrl', 'v')
                return True
            except:
                # Fallback: PowerShell
                subprocess.run([
                    'powershell', '-command',
                    '[System.Windows.Forms.SendKeys]::SendWait("^v")'
                ], check=True)
                return True
                
        else:
            # Linux: Use xdotool or pyautogui for Ctrl+V
            try:
                # Try xdotool first (more reliable on Linux)
                subprocess.run(['xdotool', 'key', 'ctrl+v'], check=True)
                return True
            except FileNotFoundError:
                # Fallback to pyautogui
                try:
                    import pyautogui
                    pyautogui.hotkey('ctrl', 'v')
                    return True
                except:
                    pass
            return False
            
    except Exception as e:
        print(json.dumps({"typing_error": str(e)}), file=sys.stderr)
        return False

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Record and transcribe audio')
    parser.add_argument('--device', type=int, default=None, help='Audio device ID')
    parser.add_argument('--duration', type=float, default=None, help='Recording duration in seconds')
    parser.add_argument('--model', type=str, default='nemo-parakeet-tdt-0.6b-v3', help='Model name')
    parser.add_argument('--vad', action='store_true', help='Use VAD')
    parser.add_argument('--output', type=str, choices=['clipboard', 'simulate_typing', 'stdout', 'json'], default='json', help='Output mode')
    
    args = parser.parse_args()
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        global recording
        recording = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Record audio
    print(json.dumps({"status": "recording"}), flush=True)
    
    if args.duration:
        record_audio(device_id=args.device, duration=args.duration)
    else:
        # Start recording in background, wait for signal
        thread = threading.Thread(target=record_audio, args=(args.device,))
        thread.start()
        
        # Wait for input to stop (or Ctrl+C)
        try:
            input()  # Wait for newline
        except EOFError:
            pass
        
        global recording
        recording = False
        thread.join(timeout=2)
    
    # Get audio data
    audio_int16 = stop_recording()
    
    if audio_int16 is None or len(audio_int16) == 0:
        result = {"error": "No audio recorded"}
    else:
        print(json.dumps({"status": "transcribing", "duration": len(audio_int16) / SAMPLE_RATE}), flush=True)
        
        # Transcribe
        result = transcribe_audio(audio_int16, model_name=args.model, use_vad=args.vad)
    
    # Output result
    if 'text' in result:
        if args.output == 'clipboard':
            copy_to_clipboard(result['text'])
            result['copied'] = True
        elif args.output == 'simulate_typing':
            if type_text(result['text']):
                result['typed'] = True
            else:
                # Fallback to clipboard if typing fails
                copy_to_clipboard(result['text'])
                result['copied'] = True
                result['typing_failed'] = True
    
    if args.output == 'stdout' and 'text' in result:
        print(result['text'])
    else:
        print(json.dumps(result), flush=True)

if __name__ == '__main__':
    main()
