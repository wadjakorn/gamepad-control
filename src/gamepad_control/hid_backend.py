"""Direct hidapi backend for controllers SDL can't read on macOS.

Over Bluetooth the HyperX Clutch (and other Xbox-BT-protocol pads) presents a
HID layout SDL's IOKit driver enumerates but never receives reports from.
hidapi reads the same device fine, using the standard Xbox-BT report format
(verified by calibration capture on real hardware):

  byte0     report ID 0x01
  byte1     A=0x01 B=0x02 X=0x08 Y=0x10 LB=0x40 RB=0x80
  byte2     LT_dig=0x01 RT_dig=0x02 Back=0x04 Start=0x08 Clear=0x10
            LS=0x20 RS=0x40 (bit7 flickers at idle — ignore)
            Home/guide button sends nothing over BT (consumed by firmware/OS).
  byte3     hat: 0=N 2=E 4=S 6=W, odd=diagonals, 0x0f=released
  bytes4-11 LX, LY, RX, RY — uint16 LE, center 0x8000
  bytes12-15 LT, RT analog — 10-bit (0..0x3ff)
"""

import time

import hid

from . import controller as c
from .log import log

KNOWN_PADS = [(0x03F0, 0x048D)]  # HyperX Clutch

_BUS_BLUETOOTH = 2  # hidapi bus_type

_BYTE1_BITS = {
    0x01: c.BTN_A,
    0x02: c.BTN_B,
    0x08: c.BTN_X,
    0x10: c.BTN_Y,
    0x40: c.BTN_LB,
    0x80: c.BTN_RB,
}
_BYTE2_BITS = {
    0x04: c.BTN_BACK,
    0x08: c.BTN_START,
    0x10: c.BTN_MISC1,  # "Clear" button on HyperX Clutch
    0x20: c.BTN_LEFTSTICK,
    0x40: c.BTN_RIGHTSTICK,
}
_HAT_DIRS = {  # hat value -> set of dpad buttons (diagonals = two)
    0: {c.BTN_DPAD_UP},
    1: {c.BTN_DPAD_UP, c.BTN_DPAD_RIGHT},
    2: {c.BTN_DPAD_RIGHT},
    3: {c.BTN_DPAD_DOWN, c.BTN_DPAD_RIGHT},
    4: {c.BTN_DPAD_DOWN},
    5: {c.BTN_DPAD_DOWN, c.BTN_DPAD_LEFT},
    6: {c.BTN_DPAD_LEFT},
    7: {c.BTN_DPAD_UP, c.BTN_DPAD_LEFT},
}


def find_device():
    """Return (path, name) of the first known pad hidapi can see, else None.

    Bluetooth only: the USB report layout differs from the BT format this
    backend parses — opening a USB pad here reads garbage axes (drift,
    swapped sticks). USB pads are always handled by SDL.
    """
    match = None
    for info in hid.enumerate():
        if (info["vendor_id"], info["product_id"]) in KNOWN_PADS:
            log(
                f"hid enum: path={info['path']!r} usage_page={info['usage_page']} "
                f"bus_type={info['bus_type']}"
            )
            # the pad exposes a consumer-control interface too; want GamePad
            if (
                match is None
                and info["usage_page"] == 1
                and info["bus_type"] == _BUS_BLUETOOTH
            ):
                match = (info["path"], info["product_string"])
    return match


class HidPad:
    """Same read surface as the SDL path: held-buttons set + normalized axes."""

    # the pad streams reports continuously while connected (byte2 bit7
    # flickers even at idle), so prolonged silence means the device is gone —
    # e.g. a BT re-pair gives a new device path while reads on the stale
    # handle return empty forever instead of erroring (cursor keeps moving
    # with the last stick values: "drift").
    STALE_AFTER = 2.0  # seconds without any report -> treat as disconnect

    def __init__(self, path: bytes):
        self.dev = hid.device()
        self.dev.open_path(path)
        self.dev.set_nonblocking(True)
        self.held: set[int] = set()
        self._last_report = time.monotonic()
        self._log_reports = 3  # dump first raw reports to verify live format
        log(f"hid opened: {path!r}")

    def close(self):
        self.dev.close()

    def poll(self, state: c.State) -> list[tuple[int, bool]] | None:
        """Drain reports into state; return button (btn, down) edges.

        Returns None on device error (treat as disconnect).
        """
        edges: list[tuple[int, bool]] = []
        got = False
        try:
            while True:
                r = self.dev.read(64)
                if not r:
                    break
                got = True
                if self._log_reports > 0:
                    self._log_reports -= 1
                    log(f"hid report: {bytes(r[:16]).hex(' ')}")
                if r[0] != 0x01 or len(r) < 16:
                    continue
                self._apply(bytes(r), state, edges)
        except OSError as e:
            log(f"hid read error: {e}")
            return None
        now = time.monotonic()
        if got:
            self._last_report = now
        elif now - self._last_report > self.STALE_AFTER:
            # silent too long — stale handle (BT re-pair etc.)
            log(f"hid silent {now - self._last_report:.1f}s -> stale, closing")
            return None
        return edges

    def _apply(self, b: bytes, state: c.State, edges: list):
        now: set[int] = set()
        for bit, btn in _BYTE1_BITS.items():
            if b[1] & bit:
                now.add(btn)
        for bit, btn in _BYTE2_BITS.items():
            if b[2] & bit:
                now.add(btn)
        now |= _HAT_DIRS.get(b[3] & 0x0F, set())

        for btn in now - self.held:
            edges.append((btn, True))
        for btn in self.held - now:
            edges.append((btn, False))
        self.held = now
        state.buttons = set(now)

        def stick(off):
            return (int.from_bytes(b[off : off + 2], "little") - 0x8000) / 32768.0

        state.left_x = stick(4)
        state.left_y = stick(6)
        state.right_x = stick(8)
        state.right_y = stick(10)
        state.trigger_l = int.from_bytes(b[12:14], "little") / 1023.0
        state.trigger_r = int.from_bytes(b[14:16], "little") / 1023.0
