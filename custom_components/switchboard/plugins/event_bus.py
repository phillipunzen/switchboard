"""Quelle: Home-Assistant-Event-Bus (zha_event, deconz_event, hue_event, …).

Entspricht dem, was Switch Manager konnte.

``source_config``:
    event_type:      Event-Typ, auf den gehört wird (Pflicht)
    identifier_key:  Punkt-Pfad im Event, der das Gerät kennzeichnet
                     (z. B. ``device_ieee``, ``device_id``, ``unique_id``)
    identifier_input: Name der Eingabe mit dem Vergleichswert (Standard ``identifier``)
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import CALLBACK_TYPE, Event, callback
from homeassistant.helpers import config_validation as cv

from ..api import SourceContext, SourcePlugin
from ..models import get_path


class EventBusPlugin(SourcePlugin):
    key = "event"
    name = "Event-Bus"
    description = (
        "Hört auf Home-Assistant-Events wie zha_event, deconz_event oder hue_event "
        "und filtert per Kennung auf das Gerät."
    )
    config_schema = vol.Schema(
        {
            vol.Required("event_type"): cv.string,
            vol.Optional("identifier_key"): cv.string,
            vol.Optional("identifier_input", default="identifier"): cv.string,
        }
    )
    default_inputs = [
        {
            "key": "identifier",
            "name": "Geräte-Kennung",
            "description": "Wert, der im Event unter identifier_key steht (z. B. IEEE-Adresse)",
            "required": True,
            "selector": {"text": {}},
            "multiple": False,
        }
    ]

    async def async_attach(self, ctx: SourceContext) -> CALLBACK_TYPE:
        cfg = ctx.source_config
        key: str | None = cfg.get("identifier_key")
        expected = ctx.inputs.get(cfg["identifier_input"]) if key else None
        if key and expected in (None, ""):
            raise vol.Invalid(f"Eingabe '{cfg['identifier_input']}' fehlt")

        @callback
        def _filter(event_data: dict[str, Any]) -> bool:
            if not key:
                return True
            return str(get_path(event_data, key)).lower() == str(expected).lower()

        @callback
        def _handle(event: Event) -> None:
            ctx.emit({**event.data, "event_type": event.event_type})

        return self.hass.bus.async_listen(cfg["event_type"], _handle, event_filter=_filter)
