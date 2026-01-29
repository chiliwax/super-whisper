"""ASR transcription engine for SuperWhisper."""

import numpy as np
import scipy.io.wavfile as wav
import tempfile
from typing import Optional, List
from pathlib import Path

import onnx_asr
from onnx_asr.loader import load_vad

SAMPLE_RATE = 16000


class Transcriber:
    """Handles speech-to-text transcription with multiple model support."""
    
    def __init__(
        self,
        model_name: str = "nemo-parakeet-tdt-0.6b-v3",
        use_vad: bool = False,
        providers: Optional[List[str]] = None
    ):
        self.model_name = model_name
        self.use_vad = use_vad
        self.providers = providers or ["CPUExecutionProvider"]
        
        self.model = None
        self.vad_model = None
        self._loaded = False
    
    def load(self, on_progress: Optional[callable] = None) -> bool:
        """Load the ASR model (and VAD if enabled)."""
        try:
            if on_progress:
                on_progress("loading_vad" if self.use_vad else "loading_model")
            
            # Load VAD model if enabled
            if self.use_vad:
                self.vad_model = load_vad("silero", providers=self.providers)
            
            if on_progress:
                on_progress("loading_model")
            
            # Load ASR model
            self.model = onnx_asr.load_model(
                self.model_name,
                providers=self.providers
            )
            
            self._loaded = True
            if on_progress:
                on_progress("ready")
            
            return True
        except Exception as e:
            if on_progress:
                on_progress(f"error: {str(e)}")
            raise e
    
    def transcribe(self, audio_int16: np.ndarray) -> Optional[str]:
        """Transcribe audio data to text."""
        if not self._loaded:
            raise RuntimeError("Model not loaded. Call load() first.")
        
        # Check audio level
        audio_level = np.abs(audio_int16).mean()
        if audio_level < 100:
            return None
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav.write(f.name, SAMPLE_RATE, audio_int16)
            
            if self.use_vad and self.vad_model is not None:
                result = self._transcribe_with_vad(f.name, audio_int16)
            else:
                result = self.model.recognize(f.name)
            
            if result and result.strip():
                return result.strip()
            return None
    
    def _transcribe_with_vad(self, filepath: str, audio_int16: np.ndarray) -> str:
        """Transcribe using VAD segmentation for better accuracy on long audio."""
        # Convert to float32 for VAD (normalized -1 to 1)
        audio_float = audio_int16.astype(np.float32) / 32767.0
        
        # Prepare batch format for VAD
        waveforms = audio_float.reshape(1, -1)
        waveforms_len = np.array([len(audio_float)], dtype=np.int64)
        
        # Get speech segments with VAD
        segments_iter = self.vad_model.segment_batch(
            waveforms,
            waveforms_len,
            sample_rate=SAMPLE_RATE
        )
        
        # Collect all speech segments
        all_texts = []
        for segment_list in segments_iter:
            segments = list(segment_list)
            if not segments:
                continue
            
            for start, end in segments:
                # Extract segment audio
                segment_audio = audio_int16[start:end]
                if len(segment_audio) < SAMPLE_RATE * 0.1:  # Skip very short segments
                    continue
                
                # Save segment to temp file and transcribe
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as seg_f:
                    wav.write(seg_f.name, SAMPLE_RATE, segment_audio)
                    result = self.model.recognize(seg_f.name)
                    if result and result.strip():
                        all_texts.append(result.strip())
        
        return " ".join(all_texts)
    
    def change_model(self, model_name: str) -> bool:
        """Change the ASR model."""
        self.model_name = model_name
        self._loaded = False
        return self.load()
    
    def set_vad(self, enabled: bool) -> bool:
        """Enable or disable VAD."""
        if enabled != self.use_vad:
            self.use_vad = enabled
            self._loaded = False
            return self.load()
        return True
    
    @property
    def is_loaded(self) -> bool:
        return self._loaded


class TranscriptionResult:
    """Result of a transcription."""
    
    def __init__(
        self,
        text: str,
        duration: float,
        audio_level: float,
        segments: Optional[List[dict]] = None
    ):
        self.text = text
        self.duration = duration
        self.audio_level = audio_level
        self.segments = segments or []
    
    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "duration": self.duration,
            "audio_level": self.audio_level,
            "segments": self.segments
        }
