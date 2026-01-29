#!/bin/bash
# Full build script for SuperWhisper

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "Building SuperWhisper"
echo "========================================"

# Step 1: Build Python sidecar
echo ""
echo "Step 1: Building Python sidecar..."
echo "----------------------------------------"
"$SCRIPT_DIR/build-sidecar.sh"

# Step 2: Build Tauri app
echo ""
echo "Step 2: Building Tauri application..."
echo "----------------------------------------"
cd "$PROJECT_ROOT"
npm run tauri build

echo ""
echo "========================================"
echo "Build complete!"
echo "========================================"
echo ""
echo "Output locations:"
echo "  macOS: src-tauri/target/release/bundle/macos/SuperWhisper.app"
echo "  DMG:   src-tauri/target/release/bundle/dmg/"
