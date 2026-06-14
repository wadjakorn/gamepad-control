"""KeyCastr-style on-screen keystroke overlay (toggleable, default off).

A floating, click-through NSPanel showing the most recent button→action triggers
as fading pills, anchored to the bottom-left of whichever screen the cursor is on.

Threading: feed() is called from the controller reader thread and only appends to
a lock-guarded list — it never touches AppKit. All panel/view work happens on the
main run loop, driven by a rumps.Timer (which schedules on the main NSRunLoop).
"""

import sys
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

_CORNERS = ("bottom_left", "bottom_right", "top_left", "top_right")


def _parse_hex(s):
    """'#RRGGBB' / '#RGB' / bare hex -> (r, g, b) floats 0-1, or None on error."""
    if not isinstance(s, str):
        return None
    h = s.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except ValueError:
        return None
    return (r, g, b)


class _Entry:
    __slots__ = ("view", "born")

    def __init__(self, view, born):
        self.view = view
        self.born = born


class KeystrokeOverlay:
    def __init__(self, cfg: dict):
        self.enabled = False
        self._panel = None
        self._pill_bg = None
        self._text_color = None
        self._timer = None
        self._entries: list[_Entry] = []
        self._screen_frame = None  # last anchored screen frame (origin+size)
        # reader thread -> main thread handoff
        self._lock = threading.Lock()
        self._pending: list[str] = []
        self._apply_cfg(cfg)

    def _apply_cfg(self, cfg: dict):
        """Read the [overlay] block into style fields. Bad values warn + default."""
        o = cfg.get("overlay", {}) if isinstance(cfg.get("overlay"), dict) else {}
        self.fade_seconds = float(o.get("fade_seconds", 1.5))
        self.max_lines = int(o.get("max_lines", 6))
        self.font_size = float(o.get("font_size", 15))
        self.margin = float(o.get("margin", 40))

        corner = str(o.get("corner", "bottom_left"))
        if corner not in _CORNERS:
            print(
                f"config warning: overlay.corner '{corner}' invalid "
                f"(use one of {', '.join(_CORNERS)}); using bottom_left",
                file=sys.stderr,
            )
            corner = "bottom_left"
        self.corner = corner
        self._right = corner in ("bottom_right", "top_right")
        self._top = corner in ("top_left", "top_right")

        self._pill_rgb = self._hex_or_default(o.get("pill_color", "#000000"), (0.0, 0.0, 0.0), "pill_color")
        self._text_rgb = self._hex_or_default(o.get("text_color", "#FFFFFF"), (1.0, 1.0, 1.0), "text_color")

        opacity = o.get("pill_opacity", 0.72)
        try:
            opacity = float(opacity)
        except (TypeError, ValueError):
            opacity = -1
        if not 0.0 <= opacity <= 1.0:
            print(
                f"config warning: overlay.pill_opacity '{o.get('pill_opacity')}' "
                "out of range 0-1; using 0.72",
                file=sys.stderr,
            )
            opacity = 0.72
        self.pill_opacity = opacity

    @staticmethod
    def _hex_or_default(value, default_rgb, key):
        rgb = _parse_hex(value)
        if rgb is None:
            print(
                f"config warning: overlay.{key} '{value}' is not a valid hex "
                "color (e.g. \"#1e90ff\"); using default",
                file=sys.stderr,
            )
            return default_rgb
        return rgb

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

    def _panel_height(self):
        return self.max_lines * (_ROW_HEIGHT + _ROW_GAP)

    def _anchor_origin(self, vf):
        """Bottom-left panel origin for the configured corner on visibleFrame vf."""
        if self._right:
            x = vf.origin.x + vf.size.width - self.margin - _PANEL_WIDTH
        else:
            x = vf.origin.x + self.margin
        if self._top:
            y = vf.origin.y + vf.size.height - self.margin - self._panel_height()
        else:
            y = vf.origin.y + self.margin
        return (x, y)

    def _build_colors(self):
        self._pill_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            *self._pill_rgb, self.pill_opacity
        ).CGColor()
        self._text_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            *self._text_rgb, 1.0
        )

    def _ensure_panel(self):
        if self._panel is not None:
            return
        screen = self._cursor_screen()
        vf = screen.visibleFrame()
        ox, oy = self._anchor_origin(vf)
        rect = NSMakeRect(ox, oy, _PANEL_WIDTH, self._panel_height())
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
        # build the pill/text colors once (per-pill creation spams a benign
        # ObjCPointerWarning to the log; cached refs keep it quiet and alive)
        self._build_colors()
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
        label.setTextColor_(self._text_color)
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
        # bottom corners: newest at the bottom, older stacked above (y up from 0).
        # top corners: newest at the panel top, older stacked below (y down).
        if self._top:
            y = self._panel_height() - _ROW_HEIGHT
            step = -(_ROW_HEIGHT + _ROW_GAP)
        else:
            y = 0.0
            step = _ROW_HEIGHT + _ROW_GAP
        for e in reversed(self._entries):
            f = e.view.frame()
            x = (_PANEL_WIDTH - f.size.width) if self._right else 0.0
            e.view.setFrameOrigin_((x, y))
            y += step

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
            self._panel.setFrameOrigin_(self._anchor_origin(vf))
            self._screen_frame = origin

    # --- live config reload (main thread) ---

    def apply_config(self, cfg: dict):
        """Re-read [overlay] knobs and apply. New pills pick up new colors; the
        panel re-anchors to the (possibly new) corner on the next tick."""
        self._apply_cfg(cfg)
        if self._panel is not None:
            self._build_colors()
            self._screen_frame = None  # force _follow_cursor_screen to re-anchor
