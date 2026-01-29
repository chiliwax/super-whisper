# SuperWhisper

A voice-to-text transcription application built with Tauri and Python. Hold a hotkey to record, release to transcribe.

## Features

- 🎙️ **Push-to-talk recording** - Hold F13 (or configurable hotkey) to record
- 🤖 **Multiple ASR models** - Parakeet TDT v3, Whisper, and more
- 🔇 **VAD support** - Voice Activity Detection for better accuracy
- ⌨️ **Auto-typing** - Paste transcription directly or simulate typing
- 🖥️ **Cross-platform** - macOS, Windows, Linux support
- 🎨 **Modern UI** - Beautiful overlay and settings windows

## Architecture

```
SuperWhisper/
├── src/                    # Frontend (HTML/CSS/JS)
│   ├── index.html          # Recording overlay
│   ├── settings.html       # Settings window
│   ├── styles.css          # Styles
│   └── app.js, settings.js # Frontend logic
├── src-tauri/              # Tauri backend (Rust)
│   ├── src/lib.rs          # Main app logic
│   └── tauri.conf.json     # Tauri configuration
├── python/                 # Python ASR backend (sidecar)
│   ├── main.py             # JSON CLI interface
│   ├── transcriber.py      # ASR engine
│   ├── audio.py            # Audio capture
│   ├── typer.py            # Auto-typing
│   └── config.py           # Configuration
└── scripts/                # Build scripts
```

## Requirements

- **Node.js** 18+
- **Rust** 1.77+
- **Python** 3.10+
- **PyInstaller** (for building sidecar)

## Development Setup

### 1. Install dependencies

```bash
# Install Node.js dependencies
npm install

# Setup Python environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
pip install -r python/requirements.txt
```

### 2. Run in development mode

```bash
npm run tauri dev
```

### 3. Build for production

```bash
# Build Python sidecar first
./scripts/build-sidecar.sh

# Build Tauri app
npm run tauri build
```

Or use the all-in-one script:

```bash
./scripts/build-all.sh
```

## Configuration

Settings are stored in `~/.super-whisper/config.json`:

```json
{
  "device_id": null,
  "model": "nemo-parakeet-tdt-0.6b-v3",
  "use_vad": false,
  "hotkey": "f13",
  "output_mode": "clipboard"
}
```

### Available Models

| Model | Description | Size |
|-------|-------------|------|
| `nemo-parakeet-tdt-0.6b-v3` | Best quality, multilingual | 600MB |
| `whisper-base` | Good balance | 74MB |
| `onnx-community/whisper-large-v3-turbo` | High quality | 1.5GB |

### Hotkey Options

The default hotkey is **F13**. On Mac, you can remap a key (like Caps Lock or Right Option) to F13 using [Karabiner-Elements](https://karabiner-elements.pqrs.org/).

### Output Modes

- **clipboard**: Copies text to clipboard and pastes (Cmd+V)
- **simulate_typing**: Types characters one by one (slower but works everywhere)

## License

MIT
