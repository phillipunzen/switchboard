"""Switch-Entität pro Schalter: aktiviert/deaktiviert die Verarbeitung."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .engine import SwitchManager
from .entity import SwitchboardEntity, setup_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, SwitchboardEnabledSwitch)


class SwitchboardEnabledSwitch(SwitchboardEntity, SwitchEntity):
    _attr_translation_key = "enabled"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: SwitchManager, switch_id: str) -> None:
        super().__init__(manager, switch_id)
        self._attr_unique_id = f"{switch_id}_enabled"

    @property
    def is_on(self) -> bool:
        runtime = self.runtime
        return bool(runtime and runtime.enabled)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        runtime = self.runtime
        if runtime is None:
            return {}
        return {
            "definition": runtime.config["definition"],
            "listening": runtime.running,
            "error": runtime.error,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_set_enabled(self.switch_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_set_enabled(self.switch_id, False)
