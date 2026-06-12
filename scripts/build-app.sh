#!/usr/bin/env bash
# Build standalone GamepadControl.app (distributable, no Python needed on target)
set -euo pipefail
cd "$(dirname "$0")/.."

uv run pyinstaller gamepad-control.spec --noconfirm
echo
echo "Built: dist/GamepadControl.app"
echo "Install: drag to /Applications, right-click → Open (unsigned),"
echo "then grant Accessibility in System Settings → Privacy & Security."
