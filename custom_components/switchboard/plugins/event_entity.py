"""Quelle: ``event``-Entitäten (Matter, Hue v2, ESPHome, Shelly Gen2+, …).

Moderne Integrationen liefern Tastendrücke als ``event.*``-Entität mit dem
Attribut ``event_type``. Jede Eingabe der Definition ist eine solche Entität;
die Nachricht enthält ``input`` (Schlüssel der Eingabe), ``entity_id`` und
``event_type`` sowie alle weiteren Attribute.

Mit ``dynamic: true`` werden Tasten und Aktionen automatisch aus den
``event_types`` der gewählten Entitäten erzeugt.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import slugify

from ..api import SourceContext, SourcePlugin
from ..models import Definition

EVENT_TYPE_NAMES = {
    "initial_press": "Gedrückt",
    "short_release": "Kurz gedrückt",
    "long_press": "Lang gedrückt",
    "long_release": "Lang losgelassen",
    "repeat": "Gehalten (Wiederholung)",
    "multi_press_ongoing": "Mehrfachdruck läuft",
    "multi_press_complete": "Mehrfachdruck fertig",
    "press": "Gedrückt",
    "single": "1× gedrückt",
    "double": "2× gedrückt",
    "triple": "3× gedrückt",
    "long": "Lang gedrückt",
    "hold": "Gehalten",
    "release": "Losgelassen",
}


def event_type_name(event_type: str) -> str:
    if event_type in EVENT_TYPE_NAMES:
        return EVENT_TYPE_NAMES[event_type]
    if event_type.startswith("multi_press_") and event_type[12:].isdigit():
        return f"{event_type[12:]}× gedrückt"
    return event_type.replace("_", " ").capitalize()


def _iter_entities(inputs: dict[str, Any]) -> list[tuple[str, str]]:
    """(Eingabe-Schlüssel, entity_id) für alle event-Entitäten in den Eingaben."""
    result: list[tuple[str, str]] = []
    for key, value in inputs.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and item.startswith("event."):
                result.append((key, item))
    return result


class EventEntityPlugin(SourcePlugin):
    key = "event_entity"
    name = "Event-Entitäten"
    description = (
        "Tastendrücke über event.*-Entitäten – z. B. Matter (IKEA BILRESA), Hue, "
        "ESPHome oder Shelly. Unterstützt automatische Tasten-Erkennung."
    )
    supports_discovery = True
    default_inputs = [
        {
            "key": "entities",
            "name": "Tasten-Entitäten",
            "description": "Eine event-Entität pro Taste",
            "required": True,
            "selector": {"entity": {"domain": "event", "multiple": True}},
            "multiple": True,
        }
    ]

    async def async_attach(self, ctx: SourceContext) -> CALLBACK_TYPE:
        mapping = _iter_entities(ctx.inputs)
        by_entity: dict[str, str] = {entity_id: key for key, entity_id in mapping}

        @callback
        def _changed(event: Event[EventStateChangedData]) -> None:
            new = event.data["new_state"]
            old = event.data["old_state"]
            if new is None or new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return
            # Rückkehr aus "unavailable" stellt nur den alten Zeitstempel wieder her
            if old is None or old.state == STATE_UNAVAILABLE or old.state == new.state:
                return
            attrs = dict(new.attributes)
            event_type = attrs.pop("event_type", None)
            if event_type is None:
                return
            attrs.pop("event_types", None)
            ctx.emit(
                {
                    **attrs,
                    "input": by_entity.get(new.entity_id),
                    "entity_id": new.entity_id,
                    "event_type": event_type,
                }
            )

        if not by_entity:
            return lambda: None
        return async_track_state_change_event(self.hass, list(by_entity), _changed)

    async def async_discover(
        self, definition: Definition, source_config: dict[str, Any], inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        buttons: list[dict[str, Any]] = []
        used: set[str] = set()
        for index, (_key, entity_id) in enumerate(_iter_entities(inputs), start=1):
            state = self.hass.states.get(entity_id)
            event_types = list(state.attributes.get("event_types", [])) if state else []
            name = (
                state.attributes.get("friendly_name", entity_id) if state else entity_id
            )
            button_id = slugify(entity_id.split(".", 1)[1]) or f"button_{index}"
            if button_id in used:
                button_id = f"{button_id}_{index}"
            used.add(button_id)
            actions = []
            for et in event_types:
                action_id = slugify(str(et)) or "event"
                actions.append(
                    {"id": action_id, "name": event_type_name(str(et)), "match": {"event_type": et}}
                )
            button: dict[str, Any] = {
                "id": button_id,
                "name": name,
                "match": {"entity_id": entity_id},
                "actions": actions,
            }
            # Geräte, die nur Einzeldrücke kennen, bekommen virtuelle Mehrfachdrücke
            singles = [a["id"] for a in actions if a["match"]["event_type"] in ("press", "initial_press", "single", "short_release")]
            has_multi = any(
                str(a["match"]["event_type"]).startswith(("multi_press_", "double")) for a in actions
            )
            if singles and not has_multi:
                button["virtual_multi_press"] = {"action": singles[0], "max_presses": 3}
            buttons.append(button)
        return buttons
