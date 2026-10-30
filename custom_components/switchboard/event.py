"""Event-Entität pro Schalter: normalisierte Tastendrücke für eigene Automationen."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SIGNAL_SWITCH_FIRED
from .engine import SwitchManager
from .entity import SwitchboardEntity, setup_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, SwitchboardEventEntity)


class SwitchboardEventEntity(SwitchboardEntity, EventEntity):
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_translation_key = "action"

    def __init__(self, manager: SwitchManager, switch_id: str) -> None:
        super().__init__(manager, switch_id)
        self._attr_unique_id = f"{switch_id}_action"

    @property
    def event_types(self) -> list[str]:  # type: ignore[override]
        runtime = self.runtime
        return runtime.event_types() if runtime else []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SWITCH_FIRED.format(self.switch_id), self._fired
            )
        )

    @callback
    def _fired(self, data: dict[str, Any]) -> None:
        event_type = f"{data['button']}_{data['action']}"
        if event_type not in self.event_types:
            return
        self._trigger_event(
            event_type,
            {
                "button": data["button"],
                "action": data["action"],
                "presses": data["presses"],
            },
        )
        self.async_write_ha_state()
