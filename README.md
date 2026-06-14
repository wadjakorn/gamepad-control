# Gamepad Control

Control your Mac with a gamepad (Xbox layout): mouse cursor, scrolling, clicks,
keyboard shortcuts, media keys, app launcher — from a menu bar app.

Works with any Xbox-layout controller recognized by SDL's GameControllerDB
(HyperX Clutch, 8BitDo, Logitech, GameSir, …) over USB, 2.4GHz dongle, or Bluetooth.

## Quick start (from source)

```bash
uv sync
uv run python -m gamepad_control          # menu bar app
uv run python -m gamepad_control --debug  # headless, prints controller events
```

### Accessibility permission (required, one-time)

macOS blocks synthetic mouse/keyboard input until you grant Accessibility:

1. Open **System Settings → Privacy & Security → Accessibility**
2. Add your terminal app (Terminal / iTerm) — or **GamepadControl.app** if using the packaged build
3. Toggle it on, then restart the app

Without this, sticks/buttons are read fine but nothing moves on screen.

## Default mapping

| Input | MOUSE mode 🖱 | MEDIA mode 🎵 | TYPING mode ⌨️ |
|---|---|---|---|
| Left stick | Move cursor | Move cursor (slow) | — |
| Right stick | Scroll | — | — |
| A | Left click / hold-drag | Play/pause | Enter |
| B | Right click | Mute | Backspace |
| X | Cmd+Tab | — | Space |
| Y | Mission Control | — | Esc |
| LB / RB | Cursor slow / fast | Launch app (config) | — |
| LT / RT | Zoom out / in (Cmd+−/+) | Volume down / up | — |
| D-pad | Arrow keys (repeats) | Prev/next, vol ±  | Arrow keys |
| Start | Play/pause | — | — |
| **Back** | **Cycle mode** | **Cycle mode** | **Cycle mode** |
| LB+RB+Start | Quit | Quit | Quit |

### Remapping buttons

Every button in every mode is remappable via `[bindings.<mode>]` in `config.toml`
(user overrides: `~/.config/gamepad-control/config.toml`, partial OK).
Menu bar → **Edit Config…** opens the right file for your install (project
config when running from source; the user override — created on first use —
for the packaged .app) in VS Code, falling back to Cursor / Zed / Sublime /
TextMate / the default text editor:

```toml
[bindings.mouse]
x = "key:cmd+space"        # Spotlight instead of Cmd+Tab
y = "app:Visual Studio Code"
rs = "media:mute"
```

After editing, menu bar → **Reload Config** applies changes live — no app
restart needed (re-reads `config.toml`, rebuilds bindings/chords/speeds, and
drops anything held). A bad edit falls back to the bundled defaults and logs a
warning to `~/Library/Logs/gamepad-control.log` rather than crashing.

Binding types: `key:cmd+shift+t` (combo; hold = modifiers stay held, final key
repeats — e.g. hold a Cmd+Tab binding to cycle the app switcher) ·
`arrow:up` (hold-repeats) ·
`media:play_pause/next/prev/volume_up/volume_down/mute` ·
`mouse:left_click/right_click` (hold = drag) ·
`mouse:double_click/triple_click` (select word / line) · `app:<Name>` ·
`mode:cycle/mouse/media/typing` · `speed:slow/fast` (hold) · `none`.

Key names: `cmd ctrl alt shift` (+ right-side variants `cmd_r ctrl_r alt_r
shift_r`) `tab space enter esc backspace delete home end pageup pagedown
up down left right f1–f12` + any single character. A lone modifier binding
(e.g. `key:ctrl_r`) is held while the button is held.
Extra buttons: `guide` (= `home`, the brand-logo button) and `clear` are
bindable too. HyperX Clutch quirks (verified by HID capture): `home` sends
only over USB/2.4GHz, `clear` sends only over Bluetooth, and Turbo never
reaches the OS at all (hardware rapid-fire modifier — not bindable).
Invalid bindings print a warning at startup and are skipped.
Triggers are bindable as `lt` / `rt` — they act as buttons once pressed past
`[triggers] threshold`; `media:volume_*` bindings ramp while held.
LB+RB+Start always quits (hardcoded). Sticks are per-mode behavior
(cursor / scroll), not bindable.

### Text selection & clipboard

Selecting and copying text works through ordinary bindings — drop these into
any `[bindings.<mode>]` section:

| Goal | Binding | How to use |
|---|---|---|
| Copy / paste / cut / select-all | `key:cmd+c` / `cmd+v` / `cmd+x` / `cmd+a` | press |
| Select by char / line | `key:shift` | **hold** it, then D-pad arrows = Shift+Arrow; hold + `A` = shift-click / shift-drag |
| Select a word | `mouse:double_click` | move cursor onto the word, press |
| Select a line / paragraph | `mouse:triple_click` | move cursor onto it, press |
| Select word-by-word (keyboard) | `key:alt+shift+left` / `right` | press / hold-repeat |

The shipped defaults already wire some of this up: in **MOUSE** mode `ls`
(left-stick click) selects the word under the cursor and `rs` is a hold-to-
select Shift; **TYPING** mode is a full editor — D-pad navigates, `rs` selects,
`lb/rb/lt/rt` = copy/paste/cut/select-all. Key bindings are layout-independent,
so copy/paste hit the right keys even with a non-Latin input source active.

### Chord bindings (hold-modifier layers)

Hold one button as a modifier and other buttons fire different actions —
multiplying the bindings available per mode without adding a new mode. Define
`[chords.<mode>.<modifier>]` tables in `config.toml`:

```toml
# Section name = [chords.<mode>.<modifier>]
#   <mode>     : mouse | media | typing
#   <modifier> : the button you hold (any button name)
#   keys below : the buttons that remap while the modifier is held

[chords.mouse.lt]   # hold LT in MOUSE mode, then:
a = "key:cmd+c"     #   LT+A = copy
b = "key:cmd+v"     #   LT+B = paste
x = "key:cmd+-"     #   LT+X = zoom out
y = "key:cmd+="     #   LT+Y = zoom in

[chords.mouse.rt]   # a second modifier (window/desktop shortcuts):
dpad_left  = "key:ctrl+left"    #   RT + D-pad ← = prev desktop
dpad_right = "key:ctrl+right"   #   RT + D-pad → = next desktop
y = "key:cmd+w"                 #   RT + Y = close window
a = "app:Spotify"               #   RT + A = launch Spotify

[chords.typing.rb]  # works in any mode — here, an editor layer:
a = "key:cmd+z"     #   RB + A = undo
b = "key:cmd+shift+z"  # RB + B = redo
x = "key:cmd+s"     #   RB + X = save
```

`[chords]` itself can hold one optional key, `tap_timeout`:

```toml
[chords]
tap_timeout = 0.3   # seconds; longer hold = no tap
```

- **Any button** can be a modifier (`lt`, `rt`, `lb`, `back`, …); inner buttons
  use the same binding strings as `[bindings.<mode>]`.
- **Tap fires, hold modifies**: a quick tap of the modifier still runs its own
  `[bindings.<mode>]` action; holding it + pressing a mapped button runs the
  chord. The tap window is `[chords] tap_timeout` (default 0.3s).
- A button used as a modifier should have a **momentary** base binding (a key
  combo or click) — not a hold-style one (`speed:` / `key:shift`), since holding
  it now enters the chord layer instead of holding the base action.
- Holding a modifier longer than `tap_timeout` with no mapped button pressed
  fires nothing on release.

### Cursor speed

`[mouse]` in `config.toml`: `base_speed` (px/s), `slow_multiplier` /
`fast_multiplier` (held via `speed:` bindings), `accel_exponent`
(1.0 = linear, higher = finer control near center), `deadzone`.
Scroll speed: `[scroll] speed`. Menu bar → **Reload Config** applies changes
without a restart.

### Keystroke overlay

Menu bar → **Keystroke Overlay** toggles an on-screen display (off by default) of
what each press triggers — KeyCastr-style pills like `X → key:cmd+tab` and
`LT+A → key:cmd+c`, fading after ~1.5s. Handy for demos, screen recordings, or
debugging a mapping. The overlay is click-through (never steals focus) and follows
whichever screen the cursor is on. Tune the look under `[overlay]` in `config.toml`
(all keys optional; **Reload Config** applies changes live):

```toml
[overlay]
fade_seconds = 1.5          # how long each pill lingers
max_lines = 6               # most pills shown at once
font_size = 15
margin = 40                 # px inset from the anchored corner
corner = "bottom_left"      # bottom_left | bottom_right | top_left | top_right
pill_color = "#000000"      # pill background (hex)
pill_opacity = 0.72         # pill background alpha, 0-1
text_color = "#FFFFFF"      # label text (hex)
```

The stack anchors to the chosen `corner` and right-aligns on the right-hand corners;
top corners stack downward, bottom corners upward.

## Connection modes (USB / 2.4GHz / Bluetooth)

macOS exposes the pad identically over all three transports — no app config needed.

- **USB**: plug in, works immediately
- **2.4GHz**: plug dongle in, switch pad to wireless mode
- **Bluetooth**: pair via System Settings → Bluetooth (hold pad's pairing button)

Note: over Bluetooth on macOS, SDL enumerates the pad but receives no (or
garbled) input reports. The app therefore always uses a direct hidapi backend
for Bluetooth pads, parsing the Xbox-BT HID report format — see
`src/gamepad_control/hid_backend.py`. The menu bar shows "(BT)" when this
backend is active. SDL handles USB and 2.4GHz, where it works fine.

Hot-swap is supported: unplug/reconnect mid-session and the app picks the pad back up.

## Build a distributable .app

```bash
./scripts/build-app.sh   # → dist/GamepadControl.app
```

Give the `.app` to anyone — no Python needed on their machine. They must:

1. Drag to /Applications
2. First launch: **right-click → Open** (app is unsigned, Gatekeeper warns once)
3. Grant Accessibility permission (see above) — mandatory; the app reads the
   pad but can't move the cursor or press keys without it

Note for rebuilds: the app is ad-hoc signed, so every rebuild invalidates the
previous Accessibility grant — **remove** GamepadControl from the Accessibility
list and re-add it (toggling off/on may not be enough).

## Auto-start at login

```bash
./scripts/install-launchagent.sh    # uses /Applications/GamepadControl.app
./scripts/uninstall-launchagent.sh
```

Logs: `~/Library/Logs/gamepad-control.log`. Quit from the menu bar stays quit
(launchd only restarts on crash).

## Troubleshooting

**Sticks/buttons read fine but nothing happens on screen** — Accessibility
permission missing or stale. Remove the app (or your terminal, when running
from source) from System Settings → Privacy & Security → Accessibility and
re-add it, then restart the app. Required again after every rebuild of the
.app (unsigned — the grant is tied to the signature).

**Cursor drifts or pad won't reconnect (Bluetooth)** — check
`~/Library/Logs/gamepad-control.log`. Every (re)connect logs which backend was
chosen and why, e.g.:

```
[22:49:21] sdl probe 'HyperX Clutch' axes=[-32768, -32768, -32768, -32768] -> dead
[22:49:21] connected hid: HyperX Clutch
```

A Bluetooth pad should always say `connected hid`; `connected sdl` with
garbage axis values means SDL grabbed a dead BT connection (file a bug with
the log lines). The app drops a pad whose axes pin at -32768 and reacquires
automatically.

**Cursor stutters when auto-started at login** — make sure the LaunchAgent
was installed by `scripts/install-launchagent.sh` (it sets
`ProcessType=Interactive`; without it launchd throttles the input loop to
background QoS).

## Adding other controllers

Unrecognized pad? Find its GUID with `--debug`, add an SDL mapping line to
`SDL_GAMECONTROLLERCONFIG` in `src/gamepad_control/controller.py` (see the
HyperX Clutch entry there, and [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB)
for reference mappings).
