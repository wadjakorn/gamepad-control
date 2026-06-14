"""Menu bar app shell (rumps). Owns the main NSApplication run loop."""

import rumps

from .config import editable_config_path
from .launcher import open_in_editor
from .modes import Mode
from .notify import notify


class TrayApp(rumps.App):
    def __init__(self, manager, reader, overlay=None):
        super().__init__("🖱", quit_button=None)
        self.manager = manager
        self.reader = reader
        self.overlay = overlay
        self._overlay_item = rumps.MenuItem("Keystroke Overlay", callback=self._toggle_overlay)
        self._overlay_item.state = 0  # off by default
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
            rumps.MenuItem("Reload Config", callback=self._reload_config),
            self._overlay_item,
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

    def _reload_config(self, _):
        self.manager.reload()
        if self.overlay is not None:
            from . import config
            self.overlay.apply_config(config.load())
        notify("Gamepad Control", "Config reloaded")

    def _toggle_overlay(self, item):
        if self.overlay is None:
            return
        item.state = 0 if item.state else 1
        self.overlay.set_enabled(bool(item.state))

    def _toggle_pause(self, _):
        paused = self.manager.toggle_pause()
        self._pause_item.title = "Resume" if paused else "Pause"

    def _quit(self, _=None):
        self.reader.stop()
        rumps.quit_application()
