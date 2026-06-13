"""Mouse output: cursor movement, clicks/drag, smooth pixel scrolling."""

import math

import time

from pynput.mouse import Button, Controller as MouseController
from Quartz import (
    CGDisplayBounds,
    CGEventCreateScrollWheelEvent,
    CGEventPost,
    CGGetActiveDisplayList,
    kCGHIDEventTap,
    kCGScrollEventUnitPixel,
)


def _shape_vec(x: float, y: float, deadzone: float, exponent: float) -> tuple[float, float]:
    """Radial deadzone + power curve on the vector magnitude.

    Per-axis shaping warps diagonals (cross-shaped deadzone, curve crushes
    the smaller component) — circular stick motion comes out square. Shaping
    the magnitude and keeping the direction preserves angles.
    """
    mag = math.hypot(x, y)
    if mag < deadzone:
        return 0.0, 0.0
    shaped = (min(1.0, (mag - deadzone) / (1.0 - deadzone))) ** exponent
    scale = shaped / mag
    return x * scale, y * scale


class MouseOutput:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mouse = MouseController()
        # sub-pixel remainders so slow deflections still accumulate movement
        self._rx = 0.0
        self._ry = 0.0
        self._srx = 0.0
        self._sry = 0.0

    def move(self, x: float, y: float, dt: float, speed_mult: float = 1.0):
        m = self.cfg["mouse"]
        sx, sy = _shape_vec(x, y, m["deadzone"], m["accel_exponent"])
        vx = sx * m["base_speed"] * speed_mult
        vy = sy * m["base_speed"] * speed_mult
        if vx == 0.0 and vy == 0.0:
            self._rx = self._ry = 0.0
            return
        self._rx += vx * dt
        self._ry += vy * dt
        dx, dy = int(self._rx), int(self._ry)
        if dx or dy:
            self._rx -= dx
            self._ry -= dy
            # clamp the target to the screen: macOS pins the visible cursor at
            # the edge but the event-stream position keeps going offscreen, so
            # without this the stick has to "travel back" before re-entering
            px, py = self.mouse.position
            tx, ty = self._clamp(px + dx, py + dy)
            self.mouse.move(tx - px, ty - py)

    _rects: list[tuple[float, float, float, float]] | None = None
    _rects_t = 0.0

    def _clamp(self, x: float, y: float) -> tuple[float, float]:
        """Clamp the target onto the nearest display.

        Per-display (not the union rect): with offset multi-monitor layouts
        the union has dead corners with no screen — the cursor would park
        offscreen there, same symptom as no clamping at all.
        """
        now = time.monotonic()
        if self._rects is None or now - self._rects_t > 5.0:
            _, ids, cnt = CGGetActiveDisplayList(16, None, None)
            self._rects = [
                (r.origin.x, r.origin.y,
                 r.origin.x + r.size.width - 1, r.origin.y + r.size.height - 1)
                for r in (CGDisplayBounds(d) for d in ids[:cnt])
            ]
            self._rects_t = now
        best, best_d = (x, y), None
        for x0, y0, x1, y1 in self._rects:
            cx, cy = min(max(x, x0), x1), min(max(y, y0), y1)
            d = (cx - x) ** 2 + (cy - y) ** 2
            if d == 0:
                return x, y
            if best_d is None or d < best_d:
                best, best_d = (cx, cy), d
        return best

    def scroll(self, x: float, y: float, dt: float):
        s = self.cfg["scroll"]
        sx, sy = _shape_vec(x, y, s["deadzone"], 1.5)
        vx = sx * s["speed"]
        vy = sy * s["speed"]
        if vx == 0.0 and vy == 0.0:
            self._srx = self._sry = 0.0
            return
        direction = 1.0 if s.get("natural", True) else -1.0
        self._srx += -vx * dt * direction
        self._sry += -vy * dt * direction
        dx, dy = int(self._srx), int(self._sry)
        if dx or dy:
            self._srx -= dx
            self._sry -= dy
            ev = CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitPixel, 2, dy, dx)
            CGEventPost(kCGHIDEventTap, ev)

    def press(self, right: bool = False):
        self.mouse.press(Button.right if right else Button.left)

    def release(self, right: bool = False):
        self.mouse.release(Button.right if right else Button.left)

    def click_multi(self, count: int):
        # double = select word, triple = select line/paragraph (macOS text views)
        self.mouse.click(Button.left, count)
