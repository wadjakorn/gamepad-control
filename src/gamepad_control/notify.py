"""User feedback via macOS notifications (osascript — no extra permissions)."""

import subprocess


def notify(title: str, message: str = ""):
    script = f'display notification "{message}" with title "{title}"'
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
