"""Raw joystick capture — prints every button index SDL sees (mapped or not).

Uses the raw joystick API, not the GameController API, so buttons missing
from the mapping string (Turbo/Clear/...) still show up. 180s window.
"""

import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame


def main():
    pygame.init()
    pygame.joystick.init()
    deadline = time.monotonic() + 180

    js = None
    while time.monotonic() < deadline and js is None:
        pygame.event.pump()
        if pygame.joystick.get_count():
            js = pygame.joystick.Joystick(0)
            js.init()
            print(
                f"opened {js.get_name()!r}: {js.get_numbuttons()} buttons, "
                f"{js.get_numaxes()} axes, {js.get_numhats()} hats — press buttons now",
                flush=True,
            )
        else:
            time.sleep(0.2)

    if js is None:
        print("no joystick found", flush=True)
        return

    while time.monotonic() < deadline:
        for ev in pygame.event.get():
            t = time.strftime("%H:%M:%S")
            if ev.type == pygame.JOYBUTTONDOWN:
                print(f"{t}  button {ev.button} DOWN", flush=True)
            elif ev.type == pygame.JOYBUTTONUP:
                print(f"{t}  button {ev.button} UP", flush=True)
            elif ev.type == pygame.JOYHATMOTION:
                print(f"{t}  hat {ev.hat} -> {ev.value}", flush=True)
        time.sleep(0.005)

    print("done", flush=True)
    pygame.quit()


if __name__ == "__main__":
    main()
