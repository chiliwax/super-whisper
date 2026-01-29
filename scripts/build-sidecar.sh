#!/bin/bash
# Build script for SuperWhisper Python sidecar

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_DIR="$PROJECT_ROOT/python"
TAURI_DIR="$PROJECT_ROOT/src-tauri"

# Detect platform
case "$(uname -s)" in
    Darwin*)
        PLATFORM="darwin"
        ARCH="$(uname -m)"
        if [ "$ARCH" = "arm64" ]; then
            TARGET_TRIPLE="aarch64-apple-darwin"
        else
            TARGET_TRIPLE="x86_64-apple-darwin"
        fi
        ;;
    Linux*)
        PLATFORM="linux"
        ARCH="$(uname -m)"
        if [ "$ARCH" = "aarch64" ]; then
            TARGET_TRIPLE="aarch64-unknown-linux-gnu"
        else
            TARGET_TRIPLE="x86_64-unknown-linux-gnu"
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        PLATFORM="windows"
        TARGET_TRIPLE="x86_64-pc-windows-msvc"
        ;;
    *)
        echo "Unsupported platform"
        exit 1
        ;;
esac

echo "Building SuperWhisper sidecar for $TARGET_TRIPLE..."

# Ensure we're in the python directory
cd "$PYTHON_DIR"

# Activate virtual environment if it exists
if [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

# Install PyInstaller if not present
pip install pyinstaller --quiet

# Build the sidecar
echo "Running PyInstaller..."
pyinstaller --clean --noconfirm superwhisper.spec

# Create binaries directory in src-tauri
BINARIES_DIR="$TAURI_DIR/binaries"
mkdir -p "$BINARIES_DIR"

# Copy the built executable with the correct name for Tauri
if [ "$PLATFORM" = "windows" ]; then
    cp "dist/superwhisper-backend.exe" "$BINARIES_DIR/superwhisper-backend-$TARGET_TRIPLE.exe"
else
    cp "dist/superwhisper-backend" "$BINARIES_DIR/superwhisper-backend-$TARGET_TRIPLE"
    chmod +x "$BINARIES_DIR/superwhisper-backend-$TARGET_TRIPLE"
fi

echo "Sidecar built successfully: $BINARIES_DIR/superwhisper-backend-$TARGET_TRIPLE"
