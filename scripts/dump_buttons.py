"""Dump button bytes of HID reports — press buttons to identify their bits.

Prints bytes 0-3 (report id, button bytes, hat) whenever they change.
Stick/trigger bytes ignored so noise doesn't flood output.
"""

import sys
import time

import hid

VID, PID = 0x03F0, 0x048D


def main():
    dev_info = None
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] == 1:
            dev_info = d
            break
    if not dev_info:
        print("device not found", flush=True)
        sys.exit(1)

    dev = hid.device()
    dev.open_path(dev_info["path"])
    dev.set_nonblocking(True)
    print(f"opened {dev_info['product_string']!r} — press buttons now", flush=True)

    last = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        data = dev.read(64)
        if data:
            head = bytes(data[:4])
            if head != last:
                last = head
                print(f"{time.strftime('%H:%M:%S')}  bytes0-3: {head.hex(' ')}  full: {bytes(data).hex()}", flush=True)
        time.sleep(0.002)
    dev.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
