"""Keyboard output: shortcuts, arrow keys with repeat, text typing."""

import time

from pynput.keyboard import Controller as KeyController, Key


class KeyOutput:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.kb = KeyController()
        # arrow-repeat state: key -> (held_since, last_fire)
        self._held: dict[str, tuple[float, float]] = {}
        # held key-combos: keys tuple -> (held_since, last_fire)
        # modifiers stay pressed, final key repeats (e.g. hold = Cmd held, Tab cycles)
        self._held_combos: dict[tuple, tuple[float, float]] = {}

    # --- shortcuts ---

    def combo(self, *keys):
        """Press modifiers+key as discrete events (e.g. combo(Key.cmd, Key.tab))."""
        for k in keys[:-1]:
            self.kb.press(k)
        self.kb.press(keys[-1])
        self.kb.release(keys[-1])
        for k in reversed(keys[:-1]):
            self.kb.release(k)

    def app_switcher(self):
        self.combo(Key.cmd, Key.tab)

    def mission_control(self):
        self.combo(Key.ctrl, Key.up)

    def tap(self, key):
        self.kb.press(key)
        self.kb.release(key)

    # --- hold-aware combos (gamepad button held = modifiers held) ---

    _MODS = {
        Key.cmd, Key.cmd_l, Key.cmd_r, Key.ctrl, Key.ctrl_l, Key.ctrl_r,
        Key.alt, Key.alt_l, Key.alt_r, Key.shift, Key.shift_l, Key.shift_r,
    }

    @classmethod
    def _is_pure_modifier(cls, keys: tuple) -> bool:
        """A lone modifier binding (e.g. key:ctrl_r) — held, never tapped."""
        return len(keys) == 1 and keys[0] in cls._MODS

    def combo_down(self, keys: tuple):
        """Press modifiers, tap final key; modifiers stay down until combo_up.

        While held, the final key repeats at the d-pad repeat rate — so
        holding a Cmd+Tab binding keeps the app switcher open and cycles.
        A lone modifier just stays pressed (button acts as that modifier).
        """
        if self._is_pure_modifier(keys):
            self.kb.press(keys[0])
        else:
            for k in keys[:-1]:
                self.kb.press(k)
            self.tap(keys[-1])
        now = time.monotonic()
        self._held_combos[keys] = (now, now)

    def combo_up(self, keys: tuple):
        if self._held_combos.pop(keys, None) is None:
            return
        if self._is_pure_modifier(keys):
            self.kb.release(keys[0])
        else:
            for k in reversed(keys[:-1]):
                self.kb.release(k)

    def release_all_combos(self):
        for keys in list(self._held_combos):
            self.combo_up(keys)

    def combo_repeat_tick(self):
        d = self.cfg["dpad"]
        rate = d.get("combo_repeat_per_second", 5.0)
        now = time.monotonic()
        for keys, (since, last) in list(self._held_combos.items()):
            if self._is_pure_modifier(keys):
                continue  # held, not repeated
            if now - since < d["initial_delay"]:
                continue
            if now - last >= 1.0 / rate:
                self._held_combos[keys] = (since, now)
                self.tap(keys[-1])

    # --- arrow keys with key-repeat ---

    ARROWS = {"up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right}

    def arrow_down(self, name: str):
        now = time.monotonic()
        self._held[name] = (now, now)
        self.tap(self.ARROWS[name])

    def arrow_up(self, name: str):
        self._held.pop(name, None)

    def release_all_arrows(self):
        self._held.clear()

    def arrow_repeat_tick(self):
        """Call every frame; fires repeats for held arrows like a real keyboard."""
        d = self.cfg["dpad"]
        now = time.monotonic()
        for name, (since, last) in list(self._held.items()):
            if now - since < d["initial_delay"]:
                continue
            if now - last >= 1.0 / d["repeat_per_second"]:
                self._held[name] = (since, now)
                self.tap(self.ARROWS[name])

    # --- text ---

    def type_text(self, text: str):
        delay = self.cfg["typing"]["text_speed"]
        for ch in text:
            self.kb.type(ch)
            if delay:
                time.sleep(delay)
