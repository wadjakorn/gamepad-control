"""Dump raw joystick axis idle values + live changes (for BT axis-order diagnosis)."""

import os
import sys
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

pygame.init()
pygame.joystick.init()
if pygame.joystick.get_count() == 0:
    sys.exit("no joystick")

js = pygame.joystick.Joystick(0)
print(f"name={js.get_name()!r} guid={js.get_guid()} axes={js.get_numaxes()} "
      f"buttons={js.get_numbuttons()} hats={js.get_numhats()}")

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
deadline = time.monotonic() + seconds
last_print = 0.0
prev_buttons = set()
while time.monotonic() < deadline:
    pygame.event.pump()
    now = time.monotonic()
    if now - last_print >= 0.5:
        last_print = now
        vals = [js.get_axis(i) for i in range(js.get_numaxes())]
        hats = [js.get_hat(i) for i in range(js.get_numhats())]
        print("axes: " + "  ".join(f"a{i}={v:+.2f}" for i, v in enumerate(vals)) + f"  hat={hats}")
    held = {i for i in range(js.get_numbuttons()) if js.get_button(i)}
    for b in held - prev_buttons:
        print(f"button down: b{b}")
    prev_buttons = held
    time.sleep(0.02)
