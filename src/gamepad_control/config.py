"""Config loading: bundled defaults overridden by ~/.config/gamepad-control/config.toml."""

import sys
import tomllib
from pathlib import Path

USER_CONFIG = Path.home() / ".config" / "gamepad-control" / "config.toml"


def _bundled_config() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        return Path(sys._MEIPASS) / "config.toml"
    return Path(__file__).resolve().parents[2] / "config.toml"


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def editable_config_path() -> Path:
    """The config file the user should edit on this machine.

    Source checkout: the project config.toml (what load() reads).
    Packaged .app: the user override — created from the bundled defaults on
    first use so the user edits a full, commented template.
    """
    if not getattr(sys, "frozen", False):
        return _bundled_config()
    if not USER_CONFIG.exists():
        USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        USER_CONFIG.write_bytes(_bundled_config().read_bytes())
    return USER_CONFIG


def load() -> dict:
    with open(_bundled_config(), "rb") as f:
        cfg = tomllib.load(f)
    if USER_CONFIG.exists():
        with open(USER_CONFIG, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    return cfg
