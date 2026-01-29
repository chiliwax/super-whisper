"""Configuration management for SuperWhisper."""

import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, Literal

# Default config location
CONFIG_DIR = Path.home() / ".super-whisper"
CONFIG_FILE = CONFIG_DIR / "config.json"

@dataclass
class Config:
    """Application configuration."""
    # Audio settings
    device_id: Optional[int] = None
    sample_rate: int = 16000
    
    # Model settings
    model: str = "nemo-parakeet-tdt-0.6b-v3"
    use_vad: bool = False
    
    # Hotkey settings
    hotkey: str = "cmd_r"  # Default: Right Command
    
    # Output settings
    output_mode: Literal["simulate_typing", "clipboard"] = "clipboard"
    typing_speed: float = 0.01  # Delay between characters for simulate_typing
    
    # Providers
    providers: list = field(default_factory=lambda: ["CPUExecutionProvider"])
    
    def save(self, path: Optional[Path] = None):
        """Save configuration to JSON file."""
        config_path = path or CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(asdict(self), f, indent=2)
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        """Load configuration from JSON file."""
        config_path = path or CONFIG_FILE
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    data = json.load(f)
                return cls(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)
    
    def update(self, **kwargs):
        """Update configuration values."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


# Available models
AVAILABLE_MODELS = {
    "nemo-parakeet-tdt-0.6b-v3": {
        "name": "Parakeet TDT v3 (Best quality)",
        "languages": ["en", "multilingual"],
        "size": "600M"
    },
    "whisper-base": {
        "name": "Whisper Base",
        "languages": ["multilingual"],
        "size": "74M"
    },
    "onnx-community/whisper-large-v3-turbo": {
        "name": "Whisper Large v3 Turbo",
        "languages": ["multilingual"],
        "size": "1.5G"
    },
    "alphacep/vosk-model-small-en-us": {
        "name": "Vosk Small EN (Lightweight)",
        "languages": ["en"],
        "size": "40M"
    }
}

def get_available_models() -> dict:
    """Get list of available models."""
    return AVAILABLE_MODELS
