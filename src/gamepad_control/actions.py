"""Binding strings → executable actions.

Formats (config.toml [bindings.<mode>] values):
  key:cmd+tab          keyboard combo, fires on press
  arrow:up             arrow key with hold-to-repeat
  media:play_pause     play_pause | next | prev | volume_up | volume_down | mute
  mouse:left_click     left_click | right_click — held while button held (drag works)
  app:Spotify          open -a <name>
  mode:cycle           cycle | mouse | media | typing
  speed:slow           cursor speed modifier while held (slow | fast)
  none                 unbound
"""

import time

from pynput.keyboard import Key, KeyCode

_KEY_NAMES = {
    "cmd": Key.cmd, "command": Key.cmd, "ctrl": Key.ctrl, "control": Key.ctrl,
    "alt": Key.alt, "option": Key.alt, "shift": Key.shift,
    "cmd_r": Key.cmd_r, "ctrl_r": Key.ctrl_r, "alt_r": Key.alt_r,
    "shift_r": Key.shift_r,
    "tab": Key.tab, "space": Key.space, "enter": Key.enter, "return": Key.enter,
    "esc": Key.esc, "escape": Key.esc, "backspace": Key.backspace,
    "delete": Key.delete, "home": Key.home, "end": Key.end,
    "pageup": Key.page_up, "pagedown": Key.page_down,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
}


# macOS ANSI hardware keycodes (kVK_ANSI_*) — layout-independent. pynput's
# KeyCode.from_char resolves via the ACTIVE keyboard layout, so with a Thai
# input source chars like '=' land on the wrong key (broken Cmd+= zoom etc.).
# Shortcuts are positional; pin them to physical keys instead.
_CHAR_VK = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16,
    "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24,
    "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32,
    "[": 33, "i": 34, "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41,
    "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
}


def _parse_key(name: str):
    name = name.strip().lower()
    if name in _KEY_NAMES:
        return _KEY_NAMES[name]
    if len(name) == 1:
        if name in _CHAR_VK:
            return KeyCode.from_vk(_CHAR_VK[name])
        return KeyCode.from_char(name)
    raise ValueError(f"unknown key name: {name!r}")


def parse(binding: str):
    """Return (kind, payload). Raises ValueError on bad binding strings."""
    binding = binding.strip()
    if binding in ("", "none"):
        return ("none", None)
    if ":" not in binding:
        raise ValueError(f"binding needs 'type:value' format: {binding!r}")
    kind, _, value = binding.partition(":")
    kind, value = kind.strip().lower(), value.strip()

    if kind == "key":
        keys = tuple(_parse_key(p) for p in value.split("+"))
        if not keys:
            raise ValueError(f"empty key combo: {binding!r}")
        return ("key", keys)
    if kind == "arrow":
        if value not in ("up", "down", "left", "right"):
            raise ValueError(f"arrow must be up/down/left/right: {binding!r}")
        return ("arrow", value)
    if kind == "media":
        if value not in ("play_pause", "next", "prev", "volume_up", "volume_down", "mute"):
            raise ValueError(f"unknown media action: {binding!r}")
        return ("media", value)
    if kind == "mouse":
        if value not in ("left_click", "right_click", "double_click", "triple_click"):
            raise ValueError(
                f"mouse must be left_click/right_click/double_click/triple_click: {binding!r}"
            )
        return ("mouse", value)
    if kind == "app":
        return ("app", value)
    if kind == "mode":
        if value not in ("cycle", "mouse", "media", "typing"):
            raise ValueError(f"mode must be cycle/mouse/media/typing: {binding!r}")
        return ("mode", value)
    if kind == "speed":
        if value not in ("slow", "fast"):
            raise ValueError(f"speed must be slow/fast: {binding!r}")
        return ("speed", value)
    raise ValueError(f"unknown binding type: {binding!r}")


class ActionRunner:
    """Executes parsed actions against the output layers."""

    # media actions that repeat while held (a held play_pause must NOT repeat)
    _MEDIA_REPEATING = ("volume_up", "volume_down")

    def __init__(self, keys, mouse, media, open_app, set_mode, cycle_mode,
                 media_repeat_per_second: float = 10.0):
        self.keys = keys
        self.mouse = mouse
        self.media = media
        self.open_app = open_app
        self.set_mode = set_mode
        self.cycle_mode = cycle_mode
        self.media_repeat_per_second = media_repeat_per_second
        # 'speed' bindings currently held: {"slow", "fast"}
        self.speed_held: set[str] = set()
        # held repeating media actions: payload -> last_fire
        self._media_held: dict[str, float] = {}

    def run(self, action, down: bool):
        kind, payload = action
        if kind == "none":
            return
        if kind == "mouse":
            if payload in ("double_click", "triple_click"):
                if down:  # fire once on press; nothing to hold/release
                    self.mouse.click_multi(2 if payload == "double_click" else 3)
                return
            right = payload == "right_click"
            self.mouse.press(right=right) if down else self.mouse.release(right=right)
            return
        if kind == "arrow":
            self.keys.arrow_down(payload) if down else self.keys.arrow_up(payload)
            return
        if kind == "speed":
            self.speed_held.add(payload) if down else self.speed_held.discard(payload)
            return
        if kind == "key":
            # hold-aware: modifiers held + final key repeats while button held
            self.keys.combo_down(payload) if down else self.keys.combo_up(payload)
            return
        if kind == "media":
            if down:
                self._fire_media(payload)
                if payload in self._MEDIA_REPEATING:
                    self._media_held[payload] = time.monotonic()
            else:
                self._media_held.pop(payload, None)
            return
        if not down:
            return  # remaining kinds fire on press only
        if kind == "app":
            self.open_app(payload)
        elif kind == "mode":
            self.cycle_mode() if payload == "cycle" else self.set_mode(payload)

    def _fire_media(self, payload: str):
        getattr(self.media, {"next": "next_track", "prev": "prev_track"}.get(payload, payload))()

    def media_repeat_tick(self):
        """Call every frame; ramps held volume bindings (e.g. triggers)."""
        now = time.monotonic()
        for payload, last in list(self._media_held.items()):
            if now - last >= 1.0 / self.media_repeat_per_second:
                self._media_held[payload] = now
                self._fire_media(payload)

    def release_media_held(self):
        self._media_held.clear()
