#!/bin/bash
# Restart gamepad-control (run after editing config.toml).
# kill -9: plain kill on the `uv run` wrapper leaves the python child alive,
# which keeps the hid device open and blocks the new instance.
cd "$(dirname "$0")/.."
pkill -9 -f gamepad_control
sleep 1
nohup uv run python -m gamepad_control > /tmp/gp_app.log 2>&1 &
sleep 2
if pgrep -f gamepad_control > /dev/null; then
    echo "restarted ✓ (log: /tmp/gp_app.log)"
else
    echo "FAILED — log:"
    cat /tmp/gp_app.log
fi
