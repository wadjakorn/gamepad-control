"""macOS media keys via NSSystemDefined events (pynput cannot send these)."""

import time

from AppKit import NSEvent
from Quartz import CGEventPost, kCGHIDEventTap

NX_KEYTYPE_SOUND_UP = 0
NX_KEYTYPE_SOUND_DOWN = 1
NX_KEYTYPE_MUTE = 7
NX_KEYTYPE_PLAY = 16
NX_KEYTYPE_NEXT = 17
NX_KEYTYPE_PREVIOUS = 18

_NS_SYSTEM_DEFINED = 14
_SUBTYPE_AUX_CONTROL = 8


def _post(key: int, down: bool):
    flags = 0xA00 if down else 0xB00
    ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        _NS_SYSTEM_DEFINED,
        (0, 0),
        flags,
        0,
        0,
        None,
        _SUBTYPE_AUX_CONTROL,
        (key << 16) | ((0xA if down else 0xB) << 8),
        -1,
    )
    CGEventPost(kCGHIDEventTap, ev.CGEvent())


def _tap(key: int):
    _post(key, True)
    _post(key, False)


class MediaOutput:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        # trigger repeat state: name -> last fire time
        self._last_fire: dict[str, float] = {}

    def play_pause(self):
        _tap(NX_KEYTYPE_PLAY)

    def next_track(self):
        _tap(NX_KEYTYPE_NEXT)

    def prev_track(self):
        _tap(NX_KEYTYPE_PREVIOUS)

    def volume_up(self):
        _tap(NX_KEYTYPE_SOUND_UP)

    def volume_down(self):
        _tap(NX_KEYTYPE_SOUND_DOWN)

    def mute(self):
        _tap(NX_KEYTYPE_MUTE)

    def trigger_tick(self, trigger_l: float, trigger_r: float):
        """Analog triggers ramp volume: threshold + rate-limited repeat on hold."""
        t = self.cfg["triggers"]
        interval = 1.0 / t["repeat_per_second"]
        now = time.monotonic()
        for name, value, action in (
            ("l", trigger_l, self.volume_down),
            ("r", trigger_r, self.volume_up),
        ):
            if value >= t["threshold"]:
                if now - self._last_fire.get(name, 0.0) >= interval:
                    self._last_fire[name] = now
                    action()
            else:
                self._last_fire.pop(name, None)
