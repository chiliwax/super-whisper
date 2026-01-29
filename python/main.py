#!/usr/bin/env python3
"""
SuperWhisper Python Backend - JSON CLI Interface

This script provides a JSON-based command interface for the Tauri frontend.
Communication happens via stdin (commands) and stdout (events).
"""

import sys
import json
import threading
from typing import Optional

from config import Config, get_available_models
from audio import AudioRecorder, list_devices, get_audio_level, get_audio_duration
from transcriber import Transcriber
from typer import AutoTyper


class SuperWhisperBackend:
    """Main backend class handling all operations."""
    
    def __init__(self):
        self.config = Config.load()
        self.recorder = AudioRecorder(device_id=self.config.device_id)
        self.transcriber: Optional[Transcriber] = None
        self.typer = AutoTyper(
            mode=self.config.output_mode,
            typing_speed=self.config.typing_speed
        )
        self._running = True
        self._transcription_thread: Optional[threading.Thread] = None
    
    def emit(self, event: str, **data):
        """Send an event to the frontend."""
        message = {"event": event, **data}
        print(json.dumps(message), flush=True)
    
    def handle_command(self, cmd: dict):
        """Handle a command from the frontend."""
        command = cmd.get("cmd")
        
        if command == "init":
            self._handle_init()
        
        elif command == "start_recording":
            self._handle_start_recording()
        
        elif command == "stop_recording":
            self._handle_stop_recording()
        
        elif command == "get_devices":
            self._handle_get_devices()
        
        elif command == "get_models":
            self._handle_get_models()
        
        elif command == "get_config":
            self._handle_get_config()
        
        elif command == "set_config":
            self._handle_set_config(cmd)
        
        elif command == "quit":
            self._running = False
            self.emit("quit_ack")
        
        else:
            self.emit("error", message=f"Unknown command: {command}")
    
    def _handle_init(self):
        """Initialize the backend (load models)."""
        try:
            self.emit("status", message="Loading models...")
            
            self.transcriber = Transcriber(
                model_name=self.config.model,
                use_vad=self.config.use_vad,
                providers=self.config.providers
            )
            
            def on_progress(status):
                self.emit("loading_progress", status=status)
            
            self.transcriber.load(on_progress=on_progress)
            
            self.emit("init_complete", 
                     model=self.config.model,
                     vad_enabled=self.config.use_vad)
        
        except Exception as e:
            self.emit("error", message=f"Init failed: {str(e)}")
    
    def _handle_start_recording(self):
        """Start audio recording."""
        if self.recorder.is_recording:
            self.emit("error", message="Already recording")
            return
        
        if self._transcription_thread and self._transcription_thread.is_alive():
            self.emit("error", message="Still transcribing previous recording")
            return
        
        # Set up audio level callback
        def on_audio_level(level: float, waveform: list):
            self.emit("audio_level", level=level, waveform=waveform)
        
        self.recorder.on_audio_level = on_audio_level
        
        try:
            self.recorder.start()
            self.emit("recording_started")
        except Exception as e:
            self.emit("error", message=f"Failed to start recording: {str(e)}")
    
    def _handle_stop_recording(self):
        """Stop recording and start transcription."""
        if not self.recorder.is_recording:
            self.emit("error", message="Not recording")
            return
        
        audio_data = self.recorder.stop()
        
        if audio_data is None or len(audio_data) == 0:
            self.emit("error", message="No audio recorded")
            return
        
        duration = get_audio_duration(audio_data)
        level = get_audio_level(audio_data)
        
        self.emit("recording_stopped", duration=duration, level=level)
        
        # Start transcription in background thread
        self._transcription_thread = threading.Thread(
            target=self._do_transcription,
            args=(audio_data,),
            daemon=True
        )
        self._transcription_thread.start()
    
    def _do_transcription(self, audio_data):
        """Run transcription in background."""
        try:
            self.emit("transcription_started")
            
            if self.transcriber is None:
                self.emit("error", message="Transcriber not initialized")
                return
            
            result = self.transcriber.transcribe(audio_data)
            
            if result:
                self.emit("transcription_done", text=result)
                
                # Auto-type if configured
                if self.config.output_mode != "none":
                    success = self.typer.type_text(result)
                    self.emit("text_typed", success=success, mode=self.config.output_mode)
            else:
                self.emit("transcription_done", text="", message="No speech detected")
        
        except Exception as e:
            self.emit("error", message=f"Transcription failed: {str(e)}")
    
    def _handle_get_devices(self):
        """Get list of available audio devices."""
        devices = list_devices()
        self.emit("devices", devices=devices)
    
    def _handle_get_models(self):
        """Get list of available models."""
        models = get_available_models()
        self.emit("models", models=models)
    
    def _handle_get_config(self):
        """Get current configuration."""
        self.emit("config", **self.config.to_dict())
    
    def _handle_set_config(self, cmd: dict):
        """Update configuration."""
        key = cmd.get("key")
        value = cmd.get("value")
        
        if key is None:
            self.emit("error", message="Missing config key")
            return
        
        try:
            # Update config
            self.config.update(**{key: value})
            self.config.save()
            
            # Apply changes to running components
            if key == "device_id":
                self.recorder.device_id = value
            elif key == "output_mode":
                self.typer.set_mode(value)
            elif key == "typing_speed":
                self.typer.set_typing_speed(value)
            elif key == "model" and self.transcriber:
                self.transcriber.change_model(value)
            elif key == "use_vad" and self.transcriber:
                self.transcriber.set_vad(value)
            
            self.emit("config_updated", key=key, value=value)
        
        except Exception as e:
            self.emit("error", message=f"Failed to update config: {str(e)}")
    
    def run(self):
        """Main loop - read commands from stdin."""
        self.emit("ready")
        
        while self._running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                cmd = json.loads(line)
                self.handle_command(cmd)
            
            except json.JSONDecodeError as e:
                self.emit("error", message=f"Invalid JSON: {str(e)}")
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.emit("error", message=f"Unexpected error: {str(e)}")
        
        self.emit("shutdown")


def main():
    """Entry point."""
    backend = SuperWhisperBackend()
    backend.run()


if __name__ == "__main__":
    main()
