"""Always-on diagnostic log; launchd routes stdout to ~/Library/Logs/gamepad-control.log."""

import time


def log(msg: str):
    # flush=True: PyInstaller/launchd stdout is block-buffered — without it
    # lines appear hours late or never
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
