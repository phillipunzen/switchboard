"""Konstanten für Switchboard."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "switchboard"
VERSION: Final = "1.0.1"

STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1

# Ordner unterhalb von /config, in denen Nutzer eigene Erweiterungen ablegen
USER_DIR: Final = "switchboard"
USER_DEFINITIONS_DIR: Final = "definitions"
USER_PLUGINS_DIR: Final = "plugins"

PANEL_URL: Final = "switchboard"
PANEL_TITLE: Final = "Switchboard"
PANEL_ICON: Final = "mdi:gesture-tap-button"
PANEL_ELEMENT: Final = "switchboard-panel"
STATIC_BASE: Final = "/switchboard_static"

EVENT_ACTION: Final = "switchboard_action"
SIGNAL_SWITCHES_CHANGED: Final = f"{DOMAIN}_switches_changed"
SIGNAL_SWITCH_FIRED: Final = f"{DOMAIN}_fired_{{}}"
SIGNAL_DEBUG: Final = f"{DOMAIN}_debug_{{}}"

DEFAULT_PRESS_TIMEOUT_MS: Final = 400
MAX_VIRTUAL_PRESSES: Final = 5
