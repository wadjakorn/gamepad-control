"""KeyCastr-style on-screen keystroke overlay (toggleable, default off).

A floating, click-through NSPanel showing the most recent button→action triggers
as fading pills, anchored to the bottom-left of whichever screen the cursor is on.

Threading: feed() is called from the controller reader thread and only appends to
a lock-guarded list — it never touches AppKit. All panel/view work happens on the
main run loop, driven by a rumps.Timer (which schedules on the main NSRunLoop).
"""

import threading
import time

import rumps
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)

# above normal/floating windows but below the screen saver; high enough to sit
# over full-screen apps. (NSScreenSaverWindowLevel == 1000.)
_OVERLAY_LEVEL = 1000

_PANEL_WIDTH = 460.0
_ROW_HEIGHT = 34.0
_ROW_GAP = 6.0
_PILL_PAD_X = 14.0


class _Entry:
    __slots__ = ("view", "born")

    def __init__(self, view, born):
        self.view = view
        self.born = born


class KeystrokeOverlay:
    def __init__(self, cfg: dict):
        o = cfg.get("overlay", {}) if isinstance(cfg.get("overlay"), dict) else {}
        self.fade_seconds = float(o.get("fade_seconds", 1.5))
        self.max_lines = int(o.get("max_lines", 6))
        self.font_size = float(o.get("font_size", 15))
        self.margin = float(o.get("margin", 40))
        self.enabled = False

        self._panel = None
        self._pill_bg = None
        self._timer = None
        self._entries: list[_Entry] = []
        self._screen_frame = None  # last anchored screen frame (origin+size)
        # reader thread -> main thread handoff
        self._lock = threading.Lock()
        self._pending: list[str] = []

    # --- reader thread ---

    def feed(self, text: str):
        """Append a trigger label. No-op (and no allocation churn) while disabled."""
        if not self.enabled:
            return
        with self._lock:
            self._pending.append(text)

    # --- main thread (menu callbacks + timer) ---

    def set_enabled(self, on: bool):
        self.enabled = on
        if on:
            self._ensure_panel()
            self._panel.orderFront_(None)
            if self._timer is None:
                self._timer = rumps.Timer(self._tick, 1.0 / 30)
                self._timer.start()
        else:
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
            with self._lock:
                self._pending.clear()
            self._clear_entries()
            if self._panel is not None:
                self._panel.orderOut_(None)

    def _ensure_panel(self):
        if self._panel is not None:
            return
        screen = self._cursor_screen()
        vf = screen.visibleFrame()
        rect = NSMakeRect(
            vf.origin.x + self.margin,
            vf.origin.y + self.margin,
            _PANEL_WIDTH,
            self.max_lines * (_ROW_HEIGHT + _ROW_GAP),
        )
        mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, mask, NSBackingStoreBuffered, False
        )
        panel.setLevel_(_OVERLAY_LEVEL)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setIgnoresMouseEvents_(True)  # click-through
        panel.setHasShadow_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, rect.size.width, rect.size.height))
        content.setWantsLayer_(True)
        panel.setContentView_(content)
        # build the pill background CGColor once (per-pill creation spams a benign
        # ObjCPointerWarning to the log; one cached ref keeps it quiet and alive)
        self._pill_bg = NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.72).CGColor()
        self._panel = panel
        self._screen_frame = (vf.origin.x, vf.origin.y)

    def _tick(self, _timer):
        # drain new labels into pill views
        with self._lock:
            new = self._pending
            self._pending = []
        for text in new:
            self._add_entry(text)
        self._follow_cursor_screen()
        self._age_and_layout()

    def _add_entry(self, text: str):
        if self._panel is None:
            return
        content = self._panel.contentView()
        row = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _PANEL_WIDTH, _ROW_HEIGHT))
        row.setWantsLayer_(True)
        layer = row.layer()
        layer.setCornerRadius_(_ROW_HEIGHT / 2)
        layer.setBackgroundColor_(self._pill_bg)
        label = NSTextField.labelWithString_(text)
        label.setFont_(NSFont.monospacedSystemFontOfSize_weight_(self.font_size, 0.4))
        label.setTextColor_(NSColor.whiteColor())
        label.setBackgroundColor_(NSColor.clearColor())
        label.setBezeled_(False)
        label.setEditable_(False)
        label.sizeToFit()
        lf = label.frame()
        width = min(_PANEL_WIDTH, lf.size.width + 2 * _PILL_PAD_X)
        row.setFrame_(NSMakeRect(0, 0, width, _ROW_HEIGHT))
        label.setFrame_(
            NSMakeRect(_PILL_PAD_X, (_ROW_HEIGHT - lf.size.height) / 2, lf.size.width, lf.size.height)
        )
        row.addSubview_(label)
        content.addSubview_(row)
        self._entries.append(_Entry(row, time.monotonic()))
        # cap: drop oldest beyond max_lines
        while len(self._entries) > self.max_lines:
            old = self._entries.pop(0)
            old.view.removeFromSuperview()

    def _age_and_layout(self):
        now = time.monotonic()
        kept = []
        for e in self._entries:
            age = now - e.born
            if age >= self.fade_seconds:
                e.view.removeFromSuperview()
                continue
            # solid until the last 0.5s, then linear fade to 0
            tail = 0.5
            if age <= self.fade_seconds - tail:
                alpha = 1.0
            else:
                alpha = max(0.0, (self.fade_seconds - age) / tail)
            e.view.setAlphaValue_(alpha)
            kept.append(e)
        self._entries = kept
        # newest at the bottom, older stacked above
        y = 0.0
        for e in reversed(self._entries):
            f = e.view.frame()
            e.view.setFrameOrigin_((0.0, y))
            y += f.size.height + _ROW_GAP

    def _clear_entries(self):
        for e in self._entries:
            e.view.removeFromSuperview()
        self._entries = []

    # --- screen following ---

    def _cursor_screen(self):
        loc = NSEvent.mouseLocation()
        for s in NSScreen.screens():
            f = s.frame()
            if (f.origin.x <= loc.x < f.origin.x + f.size.width
                    and f.origin.y <= loc.y < f.origin.y + f.size.height):
                return s
        return NSScreen.screens()[0]

    def _follow_cursor_screen(self):
        if self._panel is None:
            return
        vf = self._cursor_screen().visibleFrame()
        origin = (vf.origin.x, vf.origin.y)
        if origin != self._screen_frame:
            self._panel.setFrameOrigin_((vf.origin.x + self.margin, vf.origin.y + self.margin))
            self._screen_frame = origin
