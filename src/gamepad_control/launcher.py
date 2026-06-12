"""App launcher via `open -a`."""

import subprocess


def open_app(name: str):
    subprocess.Popen(
        ["open", "-a", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# editors tried in order for "Edit Config"; `open -t` (default text editor)
# is the final fallback so this never fails outright
EDITOR_APPS = ["Visual Studio Code", "Cursor", "Zed", "Sublime Text", "TextMate"]


def open_in_editor(path: str):
    for app in EDITOR_APPS:
        r = subprocess.run(
            ["open", "-a", app, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            return
    subprocess.run(["open", "-t", str(path)])
