"""SDL GameController input layer.

Runs the read loop in its own thread (verified safe on macOS by spike).
Standardized Xbox layout via SDL GameControllerDB; ships a custom mapping
for HyperX Clutch on macOS (absent from both built-in and community DBs).
"""

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .log import log

# macOS USB GUID for HyperX Clutch — not in any GameControllerDB; derived from
# the community Linux entry (identical 15-button/6-axis/1-hat shape).
HYPERX_CLUTCH_MAC = (
    "03006003f00300008d04000000010000,HyperX Clutch,"
    "a:b0,b:b1,x:b3,y:b4,back:b10,start:b11,guide:b12,"
    "leftshoulder:b6,rightshoulder:b7,leftstick:b13,rightstick:b14,"
    "lefttrigger:a5,righttrigger:a4,"
    "leftx:a0,lefty:a1,rightx:a2,righty:a3,"
    "dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,"
    "platform:Mac OS X,"
)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
existing = os.environ.get("SDL_GAMECONTROLLERCONFIG", "")
os.environ["SDL_GAMECONTROLLERCONFIG"] = (
    existing + "\n" + HYPERX_CLUTCH_MAC if existing else HYPERX_CLUTCH_MAC
)

AXIS_MAX = 32767.0


@dataclass
class State:
    """Normalized snapshot of analog inputs, refreshed every frame."""

    left_x: float = 0.0
    left_y: float = 0.0
    right_x: float = 0.0
    right_y: float = 0.0
    trigger_l: float = 0.0
    trigger_r: float = 0.0
    buttons: set[int] = field(default_factory=set)  # currently-held buttons


class ControllerReader:
    """Polls the first connected controller at ~120Hz on a daemon thread."""

    def __init__(
        self,
        on_button: Callable[[int, bool], None],
        on_frame: Callable[[State, float], None],
        on_connect: Callable[[str], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        hz: float = 120.0,
        debug: bool = False,
    ):
        self.on_button = on_button
        self.on_frame = on_frame
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.interval = 1.0 / hz
        self.debug = debug
        self.state = State()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pinned_since: float | None = None  # sdl axes-pinned guard timer

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="gamepad-reader")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    # --- thread body ---

    def _run(self):
        import pygame
        import pygame._sdl2.controller as sdl2c

        pygame.init()
        sdl2c.init()
        self._pg, self._sdl2c = pygame, sdl2c

        backend, pad = self._acquire()
        try:
            last = time.monotonic()
            last_retry = 0.0
            while not self._stop.is_set():
                now = time.monotonic()
                dt, last = now - last, now

                if pad is None:
                    if now - last_retry >= 1.0:
                        last_retry = now
                        backend, pad = self._acquire()
                    time.sleep(self.interval)
                    continue

                if backend == "sdl":
                    pygame.event.pump()
                    for ev in pygame.event.get():
                        pad = self._handle_event(ev, pad)
                    if pad is not None:
                        self._read_axes(pad)
                        # runtime guard: all 4 stick axes pinned at exactly
                        # -32768 (= -1.0) means SDL stopped receiving reports
                        # (BT transition) — real sticks idle near 0. Skip
                        # on_frame while pinned (else cursor flies top-left),
                        # drop the pad after 0.5s so reacquire picks hidapi.
                        s = self.state
                        if (s.left_x, s.left_y, s.right_x, s.right_y) == (-1.0, -1.0, -1.0, -1.0):
                            if self._pinned_since is None:
                                self._pinned_since = now
                            elif now - self._pinned_since > 0.5:
                                log("sdl axes pinned at -32768 -> dropping pad, reacquiring")
                                self._pinned_since = None
                                pad.quit()
                                pad = None
                                self.state = State()
                                if self.on_disconnect:
                                    self.on_disconnect()
                        else:
                            self._pinned_since = None
                            self.on_frame(self.state, dt)
                else:  # hid
                    if self.debug and now - getattr(self, "_dbg_t", 0) >= 1.0:
                        self._dbg_t = now
                        s = self.state
                        print(
                            f"[hid] lx={s.left_x:+.3f} ly={s.left_y:+.3f} "
                            f"rx={s.right_x:+.3f} ry={s.right_y:+.3f} "
                            f"lt={s.trigger_l:.2f} rt={s.trigger_r:.2f}"
                        )
                    edges = pad.poll(self.state)
                    if edges is None:
                        log("hid device lost -> disconnect")
                        pad.close()
                        pad = None
                        self.state = State()
                        if self.on_disconnect:
                            self.on_disconnect()
                    else:
                        for btn, down in edges:
                            self.on_button(btn, down)
                        self.on_frame(self.state, dt)

                time.sleep(self.interval)
        finally:
            if pad is not None:
                pad.quit() if backend == "sdl" else pad.close()
            sdl2c.quit()
            pygame.quit()

    def _acquire(self):
        """Bluetooth pad -> hidapi, anything else -> SDL.

        hidapi is checked FIRST: on macOS BT, SDL sometimes receives a few
        garbled reports right after connect and then goes silent — axes
        freeze at garbage values (e.g. [-26778, -565]) that defeat the
        all--32768 dead-probe, and the stale stick drifts the cursor.
        find_device matches Bluetooth only (bus_type gate), so SDL still
        handles USB/2.4GHz, where it works fine.
        """
        from . import hid_backend

        found = hid_backend.find_device()
        if found is not None:
            path, name = found
            try:
                hidpad = hid_backend.HidPad(path)
                log(f"connected hid: {name}")
                if self.on_connect:
                    self.on_connect(name, "bluetooth")
                return "hid", hidpad
            except OSError as e:
                log(f"hid open failed ({path!r}): {e}")
                # fall through to SDL as last resort

        # refresh SDL's device list — hot-plug is only visible after a pump
        self._pg.event.pump()
        self._pg.event.clear()
        pad = self._open_first()
        if pad is not None:
            axes = self._sdl_probe_axes(pad)
            dead = all(a == -32768 for a in axes)
            log(f"sdl probe {pad.name!r} axes={axes} -> {'dead' if dead else 'alive'}")
            if not dead:
                log(f"connected sdl: {pad.name}")
                if self.on_connect:
                    self.on_connect(pad.name, "wired")
                return "sdl", pad
            pad.quit()
        return "sdl", None

    def _sdl_probe_axes(self, pad) -> list[int]:
        """Raw stick axis values after a settle window. All exactly -32768 =
        no reports arriving (real sticks idle near 0) — caller falls back."""
        pg = self._pg
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            pg.event.pump()
            time.sleep(0.02)
        return [
            pad.get_axis(a)
            for a in (
                pg.CONTROLLER_AXIS_LEFTX,
                pg.CONTROLLER_AXIS_LEFTY,
                pg.CONTROLLER_AXIS_RIGHTX,
                pg.CONTROLLER_AXIS_RIGHTY,
            )
        ]

    def _open_first(self):
        sdl2c = self._sdl2c
        for i in range(sdl2c.get_count()):
            if sdl2c.is_controller(i):
                pad = sdl2c.Controller(i)
                if self.debug:
                    print(f"[controller] SDL opened: {pad.name}")
                return pad
        if self.debug:
            print("[controller] no controller found, waiting for hot-plug")
        return None

    def _handle_event(self, ev, pad):
        pg = self._pg
        if ev.type == pg.CONTROLLERBUTTONDOWN:
            self.state.buttons.add(ev.button)
            if self.debug:
                print(f"[controller] button down: {ev.button}")
            self.on_button(ev.button, True)
        elif ev.type == pg.CONTROLLERBUTTONUP:
            self.state.buttons.discard(ev.button)
            self.on_button(ev.button, False)
        elif ev.type == pg.CONTROLLERDEVICEADDED and pad is None:
            pad = self._open_first()
        elif ev.type == pg.CONTROLLERDEVICEREMOVED and pad is not None:
            log("sdl removed event -> disconnect")
            pad.quit()
            pad = None
            self.state = State()
            if self.on_disconnect:
                self.on_disconnect()
        return pad

    def _read_axes(self, pad):
        pg, s = self._pg, self.state
        s.left_x = pad.get_axis(pg.CONTROLLER_AXIS_LEFTX) / AXIS_MAX
        s.left_y = pad.get_axis(pg.CONTROLLER_AXIS_LEFTY) / AXIS_MAX
        s.right_x = pad.get_axis(pg.CONTROLLER_AXIS_RIGHTX) / AXIS_MAX
        s.right_y = pad.get_axis(pg.CONTROLLER_AXIS_RIGHTY) / AXIS_MAX
        s.trigger_l = pad.get_axis(pg.CONTROLLER_AXIS_TRIGGERLEFT) / AXIS_MAX
        s.trigger_r = pad.get_axis(pg.CONTROLLER_AXIS_TRIGGERRIGHT) / AXIS_MAX


# Button constants mirrored so other modules don't import pygame (it must not
# be imported on the main thread before the reader thread initializes it).
BTN_A = 0
BTN_B = 1
BTN_X = 2
BTN_Y = 3
BTN_BACK = 4
BTN_GUIDE = 5
BTN_START = 6
BTN_LEFTSTICK = 7
BTN_RIGHTSTICK = 8
BTN_LB = 9
BTN_RB = 10
BTN_DPAD_UP = 11
BTN_DPAD_DOWN = 12
BTN_DPAD_LEFT = 13
BTN_DPAD_RIGHT = 14
BTN_MISC1 = 15  # SDL misc1 — extra button (e.g. HyperX Clutch "Clear")
# virtual buttons: analog triggers crossing [triggers].threshold (see modes.py)
BTN_LT = 16
BTN_RT = 17
