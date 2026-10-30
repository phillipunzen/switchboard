"""Quelle: MQTT (z. B. Zigbee2MQTT, Tasmota, eigene Firmware).

``source_config``:
    topic:   Topic mit Platzhaltern aus den Eingaben, z. B. ``zigbee2mqtt/{identifier}``
    payload: ``json`` (Standard) oder ``raw``

Die Nachricht enthält ``topic``, ``payload`` (Rohtext) und – bei JSON-Objekten –
alle Felder des Payloads auf oberster Ebene (für Z2M also ``action``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers import config_validation as cv

from ..api import SourceContext, SourcePlugin

_LOGGER = logging.getLogger(__name__)


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        raise vol.Invalid(f"Eingabe '{key}' für das MQTT-Topic fehlt")


class MqttPlugin(SourcePlugin):
    key = "mqtt"
    name = "MQTT"
    description = "Hört auf ein MQTT-Topic, z. B. Zigbee2MQTT (zigbee2mqtt/<Gerätename>)."
    config_schema = vol.Schema(
        {
            vol.Optional("topic", default="zigbee2mqtt/{identifier}"): cv.string,
            vol.Optional("payload", default="json"): vol.In(["json", "raw"]),
        }
    )
    default_inputs = [
        {
            "key": "identifier",
            "name": "Gerätename / Topic-Teil",
            "description": "Wird im Topic für {identifier} eingesetzt",
            "required": True,
            "selector": {"text": {}},
            "multiple": False,
        }
    ]

    def available(self) -> bool:
        return "mqtt" in self.hass.config.components

    async def async_attach(self, ctx: SourceContext) -> CALLBACK_TYPE:
        from homeassistant.components import mqtt  # noqa: PLC0415 - optional

        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            raise vol.Invalid("MQTT ist nicht verfügbar")

        cfg = ctx.source_config
        topic = cfg["topic"].format_map(_SafeDict({k: v for k, v in ctx.inputs.items()}))
        as_json = cfg["payload"] == "json"

        @callback
        def _message(msg: Any) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            data: dict[str, Any] = {"topic": msg.topic, "payload": payload}
            if as_json and payload:
                try:
                    decoded = json.loads(payload)
                except ValueError:
                    decoded = None
                if isinstance(decoded, dict):
                    data = {**decoded, **data}
            ctx.emit(data)

        return await mqtt.async_subscribe(self.hass, topic, _message)
