#!/bin/bash
set -e

# Build FlowJoe macOS .app bundle
# Usage: ./scripts/build_mac.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Building FlowJoe.app ==="
echo "Project: $PROJECT_DIR"
echo ""

# Check for PyInstaller
if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller not found. Installing..."
    pip install pyinstaller
fi

# Clean previous builds
rm -rf build/ dist/

# Build using spec file
echo "Running PyInstaller..."
pyinstaller flowkit_gui.spec --noconfirm

echo ""
echo "=== Build complete ==="
echo "App bundle: dist/FlowJoe.app"
echo ""

# Ad-hoc sign the app
echo "Signing with ad-hoc identity..."
codesign --force --deep --sign - "dist/FlowJoe.app"
echo "Signing complete."

echo ""
echo "To test: open dist/FlowJoe.app"
