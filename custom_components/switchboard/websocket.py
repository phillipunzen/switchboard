"""WebSocket-API für das Panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.script import async_validate_actions_config

from .api import SourceContext, threadsafe_emit
from .const import DOMAIN, SIGNAL_DEBUG, VERSION
from .engine import SwitchManager, match_buttons
from .models import build_buttons


def _manager(hass: HomeAssistant) -> SwitchManager:
    return hass.data[DOMAIN]["manager"]


@callback
def async_register(hass: HomeAssistant) -> None:
    for handler in (
        ws_info,
        ws_list,
        ws_get,
        ws_save,
        ws_delete,
        ws_set_enabled,
        ws_discover,
        ws_validate_sequence,
        ws_subscribe,
        ws_listen,
        ws_reload,
        ws_import,
    ):
        websocket_api.async_register_command(hass, handler)


def _invalid(connection: websocket_api.ActiveConnection, msg_id: int, err: Exception) -> None:
    connection.send_error(msg_id, "invalid", str(err))


@websocket_api.websocket_command({vol.Required("type"): "switchboard/info"})
@websocket_api.require_admin
@callback
def ws_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    registry = _manager(hass).registry
    connection.send_result(
        msg["id"],
        {**registry.as_dict(), "version": VERSION, "user_dir": str(registry.user_dir)},
    )


@websocket_api.websocket_command({vol.Required("type"): "switchboard/switches/list"})
@websocket_api.require_admin
@callback
def ws_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    manager = _manager(hass)
    connection.send_result(msg["id"], [r.as_dict() for r in manager.runtimes.values()])


@websocket_api.websocket_command(
    {vol.Required("type"): "switchboard/switches/get", vol.Required("switch_id"): str}
)
@websocket_api.require_admin
@callback
def ws_get(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    runtime = _manager(hass).runtimes.get(msg["switch_id"])
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Schalter nicht gefunden")
        return
    connection.send_result(msg["id"], runtime.as_dict())


@websocket_api.websocket_command(
    {vol.Required("type"): "switchboard/switches/save", vol.Required("config"): dict}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    try:
        runtime = await _manager(hass).async_save(msg["config"])
    except (vol.Invalid, HomeAssistantError, ValueError) as err:
        _invalid(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], runtime.as_dict())


@websocket_api.websocket_command(
    {vol.Required("type"): "switchboard/switches/delete", vol.Required("switch_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    try:
        await _manager(hass).async_delete(msg["switch_id"])
    except vol.Invalid as err:
        _invalid(connection, msg["id"], err)
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "switchboard/switches/set_enabled",
        vol.Required("switch_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_enabled(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    try:
        await _manager(hass).async_set_enabled(msg["switch_id"], msg["enabled"])
    except vol.Invalid as err:
        _invalid(connection, msg["id"], err)
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "switchboard/discover",
        vol.Required("definition"): str,
        vol.Optional("inputs", default=dict): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_discover(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    manager = _manager(hass)
    definition = manager.registry.definitions.get(msg["definition"])
    if definition is None:
        connection.send_error(msg["id"], "not_found", "Definition nicht gefunden")
        return
    try:
        buttons = await manager.async_discover(definition, msg["inputs"])
    except (vol.Invalid, HomeAssistantError, ValueError) as err:
        _invalid(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], buttons)


@websocket_api.websocket_command(
    {vol.Required("type"): "switchboard/validate_sequence", vol.Required("sequence"): vol.Any(list, dict)}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_validate_sequence(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    seq = msg["sequence"]
    try:
        await async_validate_actions_config(hass, cv.SCRIPT_SCHEMA(seq if isinstance(seq, list) else [seq]))
    except (vol.Invalid, HomeAssistantError) as err:
        connection.send_result(msg["id"], {"valid": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"valid": True})


@websocket_api.websocket_command(
    {vol.Required("type"): "switchboard/subscribe", vol.Required("switch_id"): str}
)
@websocket_api.require_admin
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Live-Ansicht der Rohnachrichten eines gespeicherten Schalters."""

    @callback
    def _forward(payload: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_DEBUG.format(msg["switch_id"]), _forward
    )
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "switchboard/listen",
        vol.Required("definition"): str,
        vol.Optional("inputs", default=dict): dict,
        vol.Optional("buttons"): vol.Any(None, list),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_listen(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Lernmodus: Quelle temporär anhängen, ohne zu speichern."""
    manager = _manager(hass)
    definition = manager.registry.definitions.get(msg["definition"])
    if definition is None:
        connection.send_error(msg["id"], "not_found", "Definition nicht gefunden")
        return
    plugin = manager.registry.plugins.get(definition.source)
    if plugin is None:
        connection.send_error(msg["id"], "not_found", "Quelle nicht geladen")
        return
    try:
        buttons = build_buttons(msg["buttons"]) if msg.get("buttons") else definition.buttons
    except vol.Invalid as err:
        _invalid(connection, msg["id"], err)
        return

    @callback
    def _emit(message: dict[str, Any]) -> None:
        hits = match_buttons(definition, buttons, message)
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {"message": message, "matches": [{"button": b.id, "action": a.id} for b, a in hits]},
            )
        )

    try:
        ctx = SourceContext(
            switch_id=f"listen_{msg['id']}",
            switch_name="Lernmodus",
            definition=definition,
            source_config=plugin.config_schema(definition.source_config),
            inputs=msg["inputs"],
            emit=threadsafe_emit(hass, _emit),
        )
        unsub = await plugin.async_attach(ctx)
    except Exception as err:  # noqa: BLE001
        _invalid(connection, msg["id"], err)
        return
    connection.subscriptions[msg["id"]] = unsub
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "switchboard/reload"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_reload(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    manager = _manager(hass)
    await manager.registry.async_load()
    await manager.async_restart_all()
    connection.send_result(msg["id"], manager.registry.as_dict())


@websocket_api.websocket_command({vol.Required("type"): "switchboard/import_switch_manager"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_import(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    from .importer import async_import_switch_manager  # noqa: PLC0415

    try:
        result = await async_import_switch_manager(hass)
    except (vol.Invalid, HomeAssistantError, OSError, ValueError) as err:
        _invalid(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)
