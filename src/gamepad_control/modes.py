"""Mode manager: routes controller input to outputs per active profile.

Button → action mappings come from config.toml [bindings.<mode>] sections
(see actions.py for the binding string format). Sticks and triggers are
per-mode structural behavior, not bindable.
"""

import sys
from enum import Enum
from typing import Callable

from . import actions
from . import controller as c
from .keys import KeyOutput
from .launcher import open_app
from .media import MediaOutput
from .mouse import MouseOutput
from .notify import notify


class Mode(Enum):
    MOUSE = "🖱 Mouse"
    MEDIA = "🎵 Media"
    TYPING = "⌨️ Typing"


_MODE_BY_NAME = {"mouse": Mode.MOUSE, "media": Mode.MEDIA, "typing": Mode.TYPING}

_BTN_BY_NAME = {
    "a": c.BTN_A, "b": c.BTN_B, "x": c.BTN_X, "y": c.BTN_Y,
    "back": c.BTN_BACK, "select": c.BTN_BACK,
    "guide": c.BTN_GUIDE, "home": c.BTN_GUIDE, "start": c.BTN_START,
    "clear": c.BTN_MISC1,
    "ls": c.BTN_LEFTSTICK, "rs": c.BTN_RIGHTSTICK,
    "lb": c.BTN_LB, "rb": c.BTN_RB,
    "dpad_up": c.BTN_DPAD_UP, "dpad_down": c.BTN_DPAD_DOWN,
    "dpad_left": c.BTN_DPAD_LEFT, "dpad_right": c.BTN_DPAD_RIGHT,
    "lt": c.BTN_LT, "rt": c.BTN_RT,
}

_QUIT_COMBO = {c.BTN_LB, c.BTN_RB, c.BTN_START}


class ModeManager:
    def __init__(self, cfg: dict, on_quit: Callable[[], None], on_mode_change: Callable[[Mode], None] | None = None):
        self.cfg = cfg
        self.mouse = MouseOutput(cfg)
        self.keys = KeyOutput(cfg)
        self.media = MediaOutput(cfg)
        self.on_quit = on_quit
        self.on_mode_change = on_mode_change
        self.mode = Mode.MOUSE
        self.paused = False
        self._order = [Mode.MOUSE, Mode.MEDIA, Mode.TYPING]
        self.runner = actions.ActionRunner(
            keys=self.keys,
            mouse=self.mouse,
            media=self.media,
            open_app=open_app,
            set_mode=lambda name: self.set_mode(_MODE_BY_NAME[name]),
            cycle_mode=self.cycle_mode,
            media_repeat_per_second=cfg["triggers"]["repeat_per_second"],
        )
        self.bindings = self._load_bindings(cfg)
        # analog triggers fire lt/rt virtual buttons when crossing the threshold
        self._trig_down = {c.BTN_LT: False, c.BTN_RT: False}

    @staticmethod
    def _load_bindings(cfg: dict) -> dict[Mode, dict[int, tuple]]:
        out: dict[Mode, dict[int, tuple]] = {m: {} for m in Mode}
        for mode_name, mode in _MODE_BY_NAME.items():
            section = cfg.get("bindings", {}).get(mode_name, {})
            for btn_name, binding in section.items():
                btn = _BTN_BY_NAME.get(btn_name.lower())
                if btn is None:
                    print(f"config warning: unknown button {btn_name!r} in [bindings.{mode_name}]", file=sys.stderr)
                    continue
                try:
                    out[mode][btn] = actions.parse(binding)
                except ValueError as e:
                    print(f"config warning: [bindings.{mode_name}] {btn_name}: {e}", file=sys.stderr)
        return out

    # --- mode switching ---

    def cycle_mode(self):
        i = self._order.index(self.mode)
        self.set_mode(self._order[(i + 1) % len(self._order)])

    def set_mode(self, mode: "Mode"):
        self._release_held()
        self.mode = mode
        notify("Gamepad Control", f"Mode: {mode.value}")
        if self.on_mode_change:
            self.on_mode_change(mode)

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        self._release_held()
        notify("Gamepad Control", "Paused" if self.paused else "Resumed")
        return self.paused

    def _release_held(self):
        """Drop anything held via bindings so it can't stick across mode/pause."""
        self.mouse.release()
        self.mouse.release(right=True)
        self.runner.speed_held.clear()
        self.runner.release_media_held()
        self.keys.release_all_arrows()
        self.keys.release_all_combos()

    # --- input routing (called from reader thread) ---

    def handle_button(self, btn: int, down: bool, held: set[int]):
        if down and _QUIT_COMBO <= (held | {btn}):
            self.on_quit()
            return
        if self.paused:
            return
        action = self.bindings[self.mode].get(btn)
        if action is not None:
            self.runner.run(action, down)

    def handle_frame(self, state: c.State, dt: float):
        if self.paused:
            return
        self.keys.arrow_repeat_tick()
        self.keys.combo_repeat_tick()
        self.runner.media_repeat_tick()
        self._trigger_edges(state)
        if self.mode is Mode.MOUSE:
            m = self.cfg["mouse"]
            mult = 1.0
            if "slow" in self.runner.speed_held:
                mult = m["slow_multiplier"]
            elif "fast" in self.runner.speed_held:
                mult = m["fast_multiplier"]
            self.mouse.move(state.left_x, state.left_y, dt, mult)
            self.mouse.scroll(state.right_x, state.right_y, dt)
        elif self.mode is Mode.MEDIA:
            self.mouse.move(state.left_x, state.left_y, dt, self.cfg["mouse"]["slow_multiplier"])

    def _trigger_edges(self, state: c.State):
        """Convert analog triggers into lt/rt virtual button presses."""
        thr = self.cfg["triggers"]["threshold"]
        for btn, val in ((c.BTN_LT, state.trigger_l), (c.BTN_RT, state.trigger_r)):
            down = val >= thr
            if down != self._trig_down[btn]:
                self._trig_down[btn] = down
                self.handle_button(btn, down, state.buttons)
