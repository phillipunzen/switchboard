"""Quelle: Geräte-Trigger von Home Assistant.

Nutzt dieselben Trigger, die der Automations-Editor unter „Gerät“ anbietet
(ZHA, Z-Wave, Shelly, deCONZ, Hue, Tasmota, …). Die Nachricht enthält die
Trigger-Felder ``type``, ``subtype``, ``domain`` usw.

Mit ``dynamic: true`` werden Tasten nach ``subtype`` gruppiert und Aktionen nach
``type`` angelegt – für fast jedes Gerät ohne eigene Definition nutzbar.

``source_config``:
    device_input:            Eingabe mit dem Gerät (Standard ``device``)
    include_entity_triggers: auch entitätsbasierte Trigger (Standard: nein)
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import CALLBACK_TYPE, Context, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import slugify

from ..api import SourceContext, SourcePlugin
from ..models import Definition

_LOGGER = logging.getLogger(__name__)

TRIGGER_NAMES = {
    "remote_button_short_press": "Kurz gedrückt",
    "remote_button_short_release": "Kurz losgelassen",
    "remote_button_long_press": "Lang gedrückt",
    "remote_button_long_release": "Lang losgelassen",
    "remote_button_double_press": "2× gedrückt",
    "remote_button_triple_press": "3× gedrückt",
    "remote_button_quadruple_press": "4× gedrückt",
    "remote_button_quintuple_press": "5× gedrückt",
    "remote_button_alt_short_press": "Kurz gedrückt (alt.)",
    "single": "1× gedrückt",
    "double": "2× gedrückt",
    "triple": "3× gedrückt",
    "long": "Lang gedrückt",
    "single_long": "Kurz + lang",
    "long_single": "Lang + kurz",
    "btn_down": "Gedrückt",
    "btn_up": "Losgelassen",
    "short_press": "Kurz gedrückt",
    "long_press": "Lang gedrückt",
    "short_release": "Kurz losgelassen",
    "long_release": "Lang losgelassen",
}

IGNORED_KEYS = {"platform", "device_id", "metadata"}


def _human(value: Any) -> str:
    text = str(value)
    return TRIGGER_NAMES.get(text, text.replace("_", " ").capitalize())


class DeviceTriggerPlugin(SourcePlugin):
    key = "device_trigger"
    name = "Geräte-Trigger"
    description = (
        "Nutzt die Geräte-Trigger von Home Assistant (ZHA, Z-Wave, Shelly, deCONZ, …). "
        "Unterstützt automatische Tasten-Erkennung."
    )
    supports_discovery = True
    config_schema = vol.Schema(
        {
            vol.Optional("device_input", default="device"): cv.string,
            vol.Optional("include_entity_triggers", default=False): cv.boolean,
        }
    )
    default_inputs = [
        {
            "key": "device",
            "name": "Gerät",
            "required": True,
            "selector": {"device": {}},
            "multiple": False,
        }
    ]

    async def _triggers(self, source_config: dict[str, Any], inputs: dict[str, Any]) -> list[dict[str, Any]]:
        from homeassistant.components.device_automation import (  # noqa: PLC0415
            DeviceAutomationType,
            async_get_device_automations,
        )

        device_id = inputs.get(source_config["device_input"])
        if not device_id:
            raise vol.Invalid(f"Eingabe '{source_config['device_input']}' fehlt")
        result = await async_get_device_automations(
            self.hass, DeviceAutomationType.TRIGGER, [device_id]
        )
        triggers = result.get(device_id, [])
        if not source_config["include_entity_triggers"]:
            triggers = [t for t in triggers if "entity_id" not in t]
        return triggers

    async def async_attach(self, ctx: SourceContext) -> CALLBACK_TYPE:
        from homeassistant.helpers.trigger import (  # noqa: PLC0415
            async_initialize_triggers,
            async_validate_trigger_config,
        )

        triggers = await self._triggers(ctx.source_config, ctx.inputs)
        removers: list[CALLBACK_TYPE] = []

        for trigger in triggers:
            info = {k: v for k, v in trigger.items() if k not in IGNORED_KEYS}

            def _make_action(info: dict[str, Any]):
                async def _action(run_variables: dict[str, Any], context: Context | None = None) -> None:
                    payload = dict(info)
                    trig = run_variables.get("trigger", {})
                    event = trig.get("event") if isinstance(trig, dict) else None
                    if event is not None and hasattr(event, "data"):
                        payload["event_data"] = dict(event.data)
                    ctx.emit(payload)

                return _action

            try:
                validated = await async_validate_trigger_config(self.hass, [dict(trigger)])
                remove = await async_initialize_triggers(
                    self.hass,
                    validated,
                    _make_action(info),
                    "switchboard",
                    f"switchboard {ctx.switch_name}",
                    _LOGGER.log,
                )
            except (vol.Invalid, Exception) as err:  # noqa: BLE001
                _LOGGER.debug("Trigger %s nicht nutzbar: %s", info, err)
                continue
            if remove:
                removers.append(remove)

        @callback
        def _remove_all() -> None:
            for remove in removers:
                remove()

        return _remove_all

    async def async_discover(
        self, definition: Definition, source_config: dict[str, Any], inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        triggers = await self._triggers(source_config, inputs)
        groups: dict[str, dict[str, Any]] = {}
        for trigger in triggers:
            subtype = trigger.get("subtype")
            entity_id = trigger.get("entity_id")
            if subtype is not None:
                group_key, name, match = str(subtype), _human(subtype), {"subtype": subtype}
            elif entity_id:
                state = self.hass.states.get(str(entity_id))
                name = state.name if state else str(entity_id)
                group_key, match = str(entity_id).split(".", 1)[-1], {"entity_id": entity_id}
            else:
                group_key, name, match = "button", "Taste", {}
            button_id = slugify(group_key) or "button"
            button = groups.setdefault(
                button_id, {"id": button_id, "name": name, "match": match, "actions": []}
            )
            ttype = trigger.get("type")
            action_id = slugify(str(ttype)) or "trigger"
            existing = {a["id"] for a in button["actions"]}
            if action_id in existing:
                continue
            button["actions"].append(
                {"id": action_id, "name": _human(ttype), "match": {"type": ttype}}
            )
        return list(groups.values())
