"""Audio capture and processing for SuperWhisper."""

import numpy as np
import sounddevice as sd
from typing import Optional, Callable, List, Dict, Any
import threading

SAMPLE_RATE = 16000
CHANNELS = 1


class AudioRecorder:
    """Handles audio recording with real-time level monitoring."""
    
    def __init__(self, device_id: Optional[int] = None, sample_rate: int = SAMPLE_RATE):
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.recording = False
        self.audio_data: List[np.ndarray] = []
        self.stream: Optional[sd.InputStream] = None
        self.on_audio_level: Optional[Callable[[float, List[float]], None]] = None
        self._lock = threading.Lock()
    
    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any):
        """Callback for audio stream."""
        if self.recording:
            with self._lock:
                self.audio_data.append(indata.copy())
            
            # Calculate audio level and waveform for UI
            if self.on_audio_level:
                level = float(np.abs(indata).mean())
                # Downsample waveform for visualization (take every Nth sample)
                waveform = indata[::100, 0].tolist() if len(indata) > 100 else indata[:, 0].tolist()
                self.on_audio_level(level, waveform)
    
    def start(self) -> bool:
        """Start recording."""
        if self.recording:
            return False
        
        self.recording = True
        self.audio_data = []
        
        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                device=self.device_id,
                callback=self._audio_callback
            )
            self.stream.start()
            return True
        except Exception as e:
            self.recording = False
            raise e
    
    def stop(self) -> Optional[np.ndarray]:
        """Stop recording and return audio data."""
        if not self.recording:
            return None
        
        self.recording = False
        
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        
        with self._lock:
            if not self.audio_data:
                return None
            
            # Combine audio chunks
            audio = np.concatenate(self.audio_data, axis=0)
            # Convert float32 to int16 PCM format
            audio_int16 = (audio * 32767).astype(np.int16)
            return audio_int16
    
    def get_duration(self) -> float:
        """Get current recording duration in seconds."""
        with self._lock:
            if not self.audio_data:
                return 0.0
            total_samples = sum(len(chunk) for chunk in self.audio_data)
            return total_samples / self.sample_rate
    
    @property
    def is_recording(self) -> bool:
        return self.recording


def list_devices() -> List[Dict[str, Any]]:
    """List all available input devices."""
    devices = sd.query_devices()
    input_devices = []
    default_input = sd.default.device[0]
    
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            input_devices.append({
                "id": i,
                "name": dev['name'],
                "is_default": i == default_input,
                "channels": dev['max_input_channels'],
                "sample_rate": dev['default_samplerate']
            })
    
    return input_devices


def get_default_device_id() -> Optional[int]:
    """Get the default input device ID."""
    try:
        return sd.default.device[0]
    except:
        return None


def get_audio_level(audio_int16: np.ndarray) -> float:
    """Calculate average audio level."""
    return float(np.abs(audio_int16).mean())


def get_audio_duration(audio_int16: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    """Get audio duration in seconds."""
    return len(audio_int16) / sample_rate
