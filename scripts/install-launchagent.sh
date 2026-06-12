#!/usr/bin/env bash
# Install launchd agent: auto-start GamepadControl.app at login.
# Requires the packaged app at /Applications/GamepadControl.app
# (LaunchAgent must point at the .app binary — Accessibility permission
# granted to Terminal does NOT cover launchd-spawned processes).
set -euo pipefail

APP_BIN="/Applications/GamepadControl.app/Contents/MacOS/GamepadControl"
PLIST="$HOME/Library/LaunchAgents/com.wadjakorn.gamepad-control.plist"
LOG="$HOME/Library/Logs/gamepad-control.log"

if [[ ! -x "$APP_BIN" ]]; then
  echo "error: $APP_BIN not found — build with scripts/build-app.sh and copy to /Applications first" >&2
  exit 1
fi

mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wadjakorn.gamepad-control</string>
    <key>ProgramArguments</key>
    <array>
        <string>$APP_BIN</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <!-- launchd defaults agents to background QoS — the input loop gets
         throttled and the cursor stutters; Interactive = full priority -->
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>KeepAlive</key>
    <dict>
        <!-- restart on crash only; exit 0 (menu-bar Quit) stays quit -->
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "installed + started: $PLIST"
echo "logs: $LOG"
