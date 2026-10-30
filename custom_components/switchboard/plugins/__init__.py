"""Mitgelieferte Ereignisquellen."""

from __future__ import annotations

from .device_trigger import DeviceTriggerPlugin
from .event_bus import EventBusPlugin
from .event_entity import EventEntityPlugin
from .mqtt import MqttPlugin
from .state import StatePlugin

BUILTIN_PLUGINS = [
    EventBusPlugin,
    EventEntityPlugin,
    DeviceTriggerPlugin,
    MqttPlugin,
    StatePlugin,
]
