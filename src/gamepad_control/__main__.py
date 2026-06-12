"""Entry point: rumps menu bar app (main thread) + gamepad reader (background)."""

import sys
import time


def _disable_app_nap():
    """Keep the input loop at full rate when running as a packaged .app.

    macOS App Nap / timer coalescing throttles background menu-bar apps —
    the reader thread gets uneven frame pacing and the cursor stutters.
    (Running from a terminal isn't affected; only the .app bundle is.)
    """
    from Foundation import (
        NSActivityLatencyCritical,
        NSActivityUserInitiated,
        NSProcessInfo,
    )

    return NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
        NSActivityUserInitiated | NSActivityLatencyCritical,
        "real-time gamepad input",
    )


def main():
    debug = "--debug" in sys.argv

    _activity = _disable_app_nap()  # held for process lifetime  # noqa: F841

    from .log import log

    log("gamepad-control starting")

    from . import config
    from .controller import ControllerReader
    from .modes import ModeManager

    cfg = config.load()

    quit_flag = {"quit": False}

    def request_quit():
        quit_flag["quit"] = True

    manager = ModeManager(cfg, on_quit=request_quit)

    def on_button(btn: int, down: bool):
        manager.handle_button(btn, down, reader.state.buttons)

    reader = ControllerReader(
        on_button=on_button,
        on_frame=manager.handle_frame,
        debug=debug,
    )

    if debug:
        # headless: no menu bar, Ctrl+C to stop
        reader.on_connect = lambda name: print(f"connected: {name}")
        reader.on_disconnect = lambda: print("disconnected")
        reader.start()
        print("debug mode — press buttons / move sticks; Ctrl+C to quit")
        try:
            while not quit_flag["quit"]:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        reader.stop()
        return

    import rumps

    from .tray import TrayApp

    app = TrayApp(manager, reader)
    manager.on_mode_change = lambda mode: None  # tray polls via timer
    reader.on_connect = app.set_controller_name
    reader.on_disconnect = lambda: app.set_controller_name(None)

    # quit combo is detected on the reader thread; rumps must quit from the
    # main thread, so the tray timer watches the flag
    original_refresh = app._refresh

    def refresh_with_quit(timer):
        if quit_flag["quit"]:
            app._quit()
            return
        original_refresh(timer)

    app._timer.stop()
    app._timer = rumps.Timer(refresh_with_quit, 0.2)
    app._timer.start()

    reader.start()
    app.run()


if __name__ == "__main__":
    main()
