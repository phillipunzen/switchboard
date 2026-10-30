"""Gemeinsame Basis für Switchboard-Entitäten (ein Gerät pro Schalter)."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_SWITCHES_CHANGED
from .engine import SwitchManager, SwitchRuntime


class SwitchboardEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: SwitchManager, switch_id: str) -> None:
        self.manager = manager
        self.switch_id = switch_id
        runtime = self.runtime
        definition = runtime.definition if runtime else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, switch_id)},
            name=runtime.name if runtime else switch_id,
            manufacturer=(definition.manufacturer if definition else None) or "Switchboard",
            model=(definition.name if definition else None),
            entry_type=DeviceEntryType.SERVICE,
            suggested_area=(runtime.config.get("area_id") if runtime else None),
        )

    @property
    def runtime(self) -> SwitchRuntime | None:
        return self.manager.runtimes.get(self.switch_id)

    @property
    def available(self) -> bool:
        return self.runtime is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_SWITCHES_CHANGED, self._refresh)
        )

    @callback
    def _refresh(self) -> None:
        if self.hass is not None:
            self.async_write_ha_state()


def setup_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[SwitchManager, str], Entity],
) -> None:
    """Legt Entitäten für bestehende und später hinzugefügte Schalter an."""
    manager: SwitchManager = hass.data[DOMAIN]["manager"]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [sid for sid in manager.runtimes if sid not in known]
        known.difference_update(sid for sid in list(known) if sid not in manager.configs)
        if new:
            known.update(new)
            async_add_entities([factory(manager, sid) for sid in new])

    _add_new()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_SWITCHES_CHANGED, _add_new))
