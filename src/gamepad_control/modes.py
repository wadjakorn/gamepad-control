"""Mode manager: routes controller input to outputs per active profile.

Button → action mappings come from config.toml [bindings.<mode>] sections
(see actions.py for the binding string format). Sticks and triggers are
per-mode structural behavior, not bindable.
"""

import sys
import time
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

# human-readable button names for the keystroke overlay
_BTN_DISPLAY = {
    c.BTN_A: "A", c.BTN_B: "B", c.BTN_X: "X", c.BTN_Y: "Y",
    c.BTN_BACK: "Back", c.BTN_GUIDE: "Guide", c.BTN_START: "Start",
    c.BTN_MISC1: "Clear", c.BTN_LEFTSTICK: "LS", c.BTN_RIGHTSTICK: "RS",
    c.BTN_LB: "LB", c.BTN_RB: "RB",
    c.BTN_DPAD_UP: "D-pad ↑", c.BTN_DPAD_DOWN: "D-pad ↓",
    c.BTN_DPAD_LEFT: "D-pad ←", c.BTN_DPAD_RIGHT: "D-pad →",
    c.BTN_LT: "LT", c.BTN_RT: "RT",
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
        self.bindings, self.binding_labels = self._load_bindings(cfg)
        self.chords, self.chord_labels = self._load_chords(cfg)
        # optional sink for the keystroke overlay: called with a "<btn> → <raw>"
        # label on every press that fires an action (set from __main__)
        self.on_trigger: Callable[[str], None] | None = None
        # held chord modifiers: modifier btn -> [press_time, consumed]
        self._mod_held: dict[int, list] = {}
        # non-modifier buttons currently down -> the action used at press, so
        # release uses the SAME action even if the chord layer changed mid-hold
        self._active: dict[int, tuple] = {}
        # tap of a modifier within this window (and no chord pressed) fires its base
        self._tap_timeout = cfg.get("chords", {}).get("tap_timeout", 0.3)
        # analog triggers fire lt/rt virtual buttons when crossing the threshold
        self._trig_down = {c.BTN_LT: False, c.BTN_RT: False}

    @staticmethod
    def _load_bindings(cfg: dict):
        """Return (parsed, labels): btn->action tuple and btn->raw binding string."""
        out: dict[Mode, dict[int, tuple]] = {m: {} for m in Mode}
        labels: dict[Mode, dict[int, str]] = {m: {} for m in Mode}
        for mode_name, mode in _MODE_BY_NAME.items():
            section = cfg.get("bindings", {}).get(mode_name, {})
            for btn_name, binding in section.items():
                btn = _BTN_BY_NAME.get(btn_name.lower())
                if btn is None:
                    print(f"config warning: unknown button {btn_name!r} in [bindings.{mode_name}]", file=sys.stderr)
                    continue
                try:
                    out[mode][btn] = actions.parse(binding)
                    labels[mode][btn] = binding
                except ValueError as e:
                    print(f"config warning: [bindings.{mode_name}] {btn_name}: {e}", file=sys.stderr)
        return out, labels

    @staticmethod
    def _load_chords(cfg: dict):
        """Parse [chords.<mode>.<modifier>] layers: hold modifier, other buttons remap.

        Returns (parsed, labels): mode->mod->btn->action and the matching raw strings.
        """
        out: dict[Mode, dict[int, dict[int, tuple]]] = {m: {} for m in Mode}
        labels: dict[Mode, dict[int, dict[int, str]]] = {m: {} for m in Mode}
        for mode_name, mode in _MODE_BY_NAME.items():
            section = cfg.get("chords", {}).get(mode_name, {})
            for mod_name, layer in section.items():
                if not isinstance(layer, dict):
                    continue  # e.g. the top-level tap_timeout key
                mod = _BTN_BY_NAME.get(mod_name.lower())
                if mod is None:
                    print(f"config warning: unknown modifier {mod_name!r} in [chords.{mode_name}]", file=sys.stderr)
                    continue
                for btn_name, binding in layer.items():
                    btn = _BTN_BY_NAME.get(btn_name.lower())
                    if btn is None:
                        print(f"config warning: unknown button {btn_name!r} in [chords.{mode_name}.{mod_name}]", file=sys.stderr)
                        continue
                    try:
                        out[mode].setdefault(mod, {})[btn] = actions.parse(binding)
                        labels[mode].setdefault(mod, {})[btn] = binding
                    except ValueError as e:
                        print(f"config warning: [chords.{mode_name}.{mod_name}] {btn_name}: {e}", file=sys.stderr)
        return out, labels

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

    def reload(self):
        """Re-read config.toml and apply live — no app restart.

        Re-assigns the cfg reference on each output (single atomic attr swap, so
        the reader thread never sees a torn dict) and rebuilds the init-cached
        tables. mouse/keys/media read self.cfg live, so the swap is enough there.
        """
        from .config import load
        cfg = load()
        self.cfg = cfg
        self.mouse.cfg = cfg
        self.keys.cfg = cfg
        self.media.cfg = cfg
        self.bindings, self.binding_labels = self._load_bindings(cfg)
        self.chords, self.chord_labels = self._load_chords(cfg)
        self._tap_timeout = cfg.get("chords", {}).get("tap_timeout", 0.3)
        self.runner.media_repeat_per_second = cfg["triggers"]["repeat_per_second"]
        self._release_held()  # drop anything held under the old bindings

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
        self._mod_held.clear()
        self._active.clear()

    # --- input routing (called from reader thread) ---

    def handle_button(self, btn: int, down: bool, held: set[int]):
        if down and _QUIT_COMBO <= (held | {btn}):
            self.on_quit()
            return
        if self.paused:
            return
        if down:
            if btn in self.chords.get(self.mode, {}):
                # a modifier here: enter its layer; base fires only on a quick tap
                self._mod_held[btn] = [time.monotonic(), False]
                return
            action, label = self._resolve(btn)
            if action is not None:
                self._active[btn] = action
                self.runner.run(action, True)
                self._emit(action, label)
        else:
            if btn in self._mod_held:
                press_t, consumed = self._mod_held.pop(btn)
                if not consumed and time.monotonic() - press_t < self._tap_timeout:
                    base = self.bindings[self.mode].get(btn)
                    if base is not None:  # tap = run its own binding as down+up
                        self.runner.run(base, True)
                        self.runner.run(base, False)
                        self._emit(base, self._label(btn))
                return
            action = self._active.pop(btn, None) or self.bindings[self.mode].get(btn)
            if action is not None:
                self.runner.run(action, False)

    def _resolve(self, btn: int):
        """(action, overlay label). Chord layer if a holding modifier maps btn, else base."""
        for mod_btn, st in self._mod_held.items():
            layer = self.chords[self.mode].get(mod_btn, {})
            if btn in layer:
                st[1] = True  # consumed -> suppress this modifier's tap
                raw = self.chord_labels.get(self.mode, {}).get(mod_btn, {}).get(btn)
                return layer[btn], self._label(btn, mod_btn, raw)
        return self.bindings[self.mode].get(btn), self._label(btn)

    def _label(self, btn: int, mod_btn: int | None = None, raw: str | None = None) -> str:
        """'X → key:cmd+tab' or 'LT+A → key:cmd+c' for the keystroke overlay."""
        if raw is None:
            raw = self.binding_labels.get(self.mode, {}).get(btn, "")
        name = _BTN_DISPLAY.get(btn, str(btn))
        if mod_btn is not None:
            name = f"{_BTN_DISPLAY.get(mod_btn, mod_btn)}+{name}"
        return f"{name} → {raw}" if raw else name

    def _emit(self, action, label: str):
        if self.on_trigger and action and action[0] != "none" and label:
            self.on_trigger(label)

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
