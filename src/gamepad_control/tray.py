"""Menu bar app shell (rumps). Owns the main NSApplication run loop."""

import rumps

from .config import editable_config_path
from .launcher import open_in_editor
from .modes import Mode


class TrayApp(rumps.App):
    def __init__(self, manager, reader):
        super().__init__("🖱", quit_button=None)
        self.manager = manager
        self.reader = reader
        self._pause_item = rumps.MenuItem("Pause", callback=self._toggle_pause)
        self._status_item = rumps.MenuItem("Controller: …")
        self._status_item.set_callback(None)
        self.menu = [
            self._status_item,
            None,
            rumps.MenuItem("Mode: Mouse", callback=lambda _: self._set_mode(Mode.MOUSE)),
            rumps.MenuItem("Mode: Media", callback=lambda _: self._set_mode(Mode.MEDIA)),
            rumps.MenuItem("Mode: Typing", callback=lambda _: self._set_mode(Mode.TYPING)),
            None,
            rumps.MenuItem("Edit Config…", callback=self._edit_config),
            self._pause_item,
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        # poll shared state from the main thread — rumps/AppKit UI updates must
        # not happen on the reader thread
        self._timer = rumps.Timer(self._refresh, 0.5)
        self._timer.start()

    def set_controller_name(self, name: str | None):
        # written from reader thread; only read by _refresh on main thread
        self._controller_name = name

    _controller_name: str | None = None

    def _refresh(self, _):
        icon = self.manager.mode.value.split()[0]
        self.title = f"{icon}⏸" if self.manager.paused else icon
        name = self._controller_name
        self._status_item.title = f"Controller: {name or 'not connected'}"

    def _set_mode(self, mode: Mode):
        self.manager.set_mode(mode)

    def _edit_config(self, _):
        open_in_editor(editable_config_path())

    def _toggle_pause(self, _):
        paused = self.manager.toggle_pause()
        self._pause_item.title = "Resume" if paused else "Pause"

    def _quit(self, _=None):
        self.reader.stop()
        rumps.quit_application()
