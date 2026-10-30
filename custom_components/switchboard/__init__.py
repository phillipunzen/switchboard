"""Switchboard – zentrale Verwaltung von Funkschaltern und Tastern.

Nachfolger-Idee zum Switch Manager: Schalter-Definitionen (YAML) beschreiben
Tasten und Aktionen, Plugins liefern die Ereignisse, im Panel wird pro
Taste/Aktion eine Sequenz hinterlegt.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL,
    STATIC_BASE,
    USER_DIR,
    VERSION,
)
from .engine import SwitchManager
from .registry import Registry
from . import websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.EVENT, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
STATIC_FLAG = f"{DOMAIN}_static_registered"
HERE = Path(__file__).parent


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    registry = Registry(hass)
    await registry.async_load()
    manager = SwitchManager(hass, registry)
    hass.data[DOMAIN] = {"registry": registry, "manager": manager}

    await _async_register_frontend(hass, registry)
    websocket.async_register(hass)
    _register_services(hass)

    await manager.async_load()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data.pop(DOMAIN)
        await data["manager"].async_shutdown()
        frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)
        for service in ("reload", "import_switch_manager"):
            hass.services.async_remove(DOMAIN, service)
    return unloaded


async def _async_register_frontend(hass: HomeAssistant, registry: Registry) -> None:
    if not hass.data.get(STATIC_FLAG):
        user_dir = Path(hass.config.path(USER_DIR))
        await hass.async_add_executor_job(lambda: user_dir.mkdir(parents=True, exist_ok=True))
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(f"{STATIC_BASE}/frontend", str(HERE / "frontend"), False),
                StaticPathConfig(f"{STATIC_BASE}/builtin", str(HERE / "definitions"), True),
                StaticPathConfig(f"{STATIC_BASE}/user", str(user_dir), False),
            ]
        )
        hass.data[STATIC_FLAG] = True

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_BASE}/frontend/switchboard-panel.js?v={VERSION}",
        embed_iframe=False,
        require_admin=True,
        config={"version": VERSION},
    )


def _register_services(hass: HomeAssistant) -> None:
    async def _reload(call: ServiceCall) -> None:
        manager: SwitchManager = hass.data[DOMAIN]["manager"]
        await manager.registry.async_load()
        await manager.async_restart_all()

    async def _import(call: ServiceCall) -> dict:
        from .importer import async_import_switch_manager  # noqa: PLC0415

        return await async_import_switch_manager(hass)

    hass.services.async_register(DOMAIN, "reload", _reload)
    hass.services.async_register(
        DOMAIN, "import_switch_manager", _import, supports_response=SupportsResponse.OPTIONAL
    )
