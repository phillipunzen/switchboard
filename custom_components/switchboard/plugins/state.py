"""Quelle: Zustandsänderungen einer Entität (z. B. Z2M-``sensor.*_action``).

``source_config``:
    attribute:     statt des Zustands ein Attribut beobachten
    entity_input:  Eingabe mit der Entität (Standard ``entity``)

Die Nachricht enthält ``entity_id``, ``state`` (bzw. Attributwert), ``old_state``
und ``attributes``.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event

from ..api import SourceContext, SourcePlugin

IGNORED = (None, "", STATE_UNAVAILABLE, STATE_UNKNOWN, "None")


class StatePlugin(SourcePlugin):
    key = "state"
    name = "Entitäts-Zustand"
    description = "Reagiert auf Zustands- oder Attributänderungen einer Entität."
    config_schema = vol.Schema(
        {
            vol.Optional("attribute"): cv.string,
            vol.Optional("entity_input", default="entity"): cv.string,
        }
    )
    default_inputs = [
        {
            "key": "entity",
            "name": "Entität",
            "required": True,
            "selector": {"entity": {}},
            "multiple": False,
        }
    ]

    async def async_attach(self, ctx: SourceContext) -> CALLBACK_TYPE:
        cfg = ctx.source_config
        entity_id = ctx.inputs.get(cfg["entity_input"])
        if not entity_id:
            raise vol.Invalid(f"Eingabe '{cfg['entity_input']}' fehlt")
        attribute = cfg.get("attribute")

        @callback
        def _changed(event: Event[EventStateChangedData]) -> None:
            new = event.data["new_state"]
            old = event.data["old_state"]
            if new is None:
                return
            value = new.attributes.get(attribute) if attribute else new.state
            old_value = None
            if old is not None:
                old_value = old.attributes.get(attribute) if attribute else old.state
            if value in IGNORED or (attribute and value == old_value):
                return
            if old is not None and old.state == STATE_UNAVAILABLE:
                return
            ctx.emit(
                {
                    "entity_id": new.entity_id,
                    "state": value,
                    "old_state": old_value,
                    "attributes": dict(new.attributes),
                }
            )

        return async_track_state_change_event(self.hass, [entity_id], _changed)
