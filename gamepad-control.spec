# PyInstaller spec — builds standalone GamepadControl.app
# Build: uv run pyinstaller gamepad-control.spec --noconfirm

a = Analysis(
    ["scripts/app_entry.py"],
    pathex=["src"],
    datas=[("config.toml", ".")],
    hiddenimports=[
        "gamepad_control",
        "gamepad_control.hid_backend",
        "hid",
        "pygame._sdl2.controller",
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
    ],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    name="GamepadControl",
    console=False,
    exclude_binaries=True,
)

coll = COLLECT(exe, a.binaries, a.datas, name="GamepadControl")

app = BUNDLE(
    coll,
    name="GamepadControl.app",
    bundle_identifier="com.wadjakorn.gamepad-control",
    info_plist={
        "LSUIElement": True,  # menu bar only, no Dock icon
        "NSHighResolutionCapable": True,
    },
)
