"""Öffentliche Plugin-Schnittstelle von Switchboard.

Alles, was ein Plugin braucht, wird von hier importiert::

    from custom_components.switchboard.api import SourcePlugin, SourceContext

Diese Datei ist die stabile API. Interne Module können sich ändern, diese hier
wird nur mit einer neuen ``API_VERSION`` inkompatibel geändert.

Ein Plugin ist eine **Ereignisquelle**: Es hört auf irgendetwas (Event-Bus,
MQTT, Entitäten, Webhooks, …) und reicht jede Tastenbetätigung als einfaches
Dict an ``ctx.emit()`` weiter. Welche Taste/Aktion das ist, entscheidet danach
die Schalter-Definition über ``match``-Regeln – das Plugin muss die Tasten nicht
kennen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.core import CALLBACK_TYPE, HomeAssistant

from .models import Definition

API_VERSION = 1

__all__ = [
    "threadsafe_emit",
    "API_VERSION",
    "SourceContext",
    "SourcePlugin",
    "async_register_definition",
    "async_register_plugin",
]


@dataclass(slots=True)
class SourceContext:
    """Was ein Plugin beim Anhängen an einen konfigurierten Schalter bekommt."""

    switch_id: str
    switch_name: str
    definition: Definition
    #: Validierte ``source_config`` aus der Definition
    source_config: dict[str, Any]
    #: Vom Nutzer pro Schalter eingegebene Werte (``inputs`` der Definition)
    inputs: dict[str, Any]
    #: Rohnachricht an die Engine weiterreichen
    emit: Callable[[dict[str, Any]], None]


class SourcePlugin(ABC):
    """Basisklasse für Ereignisquellen."""

    #: Eindeutiger Schlüssel, wird in Definitionen als ``source:`` verwendet
    key: str = ""
    name: str = ""
    description: str = ""
    #: Schema für ``source_config`` in Definitionen
    config_schema: vol.Schema = vol.Schema({}, extra=vol.ALLOW_EXTRA)
    #: Standard-Eingaben, falls eine Definition keine eigenen ``inputs`` hat
    default_inputs: list[dict[str, Any]] = []
    #: Kann dieses Plugin Tasten selbst ermitteln (``dynamic: true``)?
    supports_discovery: bool = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_setup(self) -> bool:
        """Einmalig beim Laden. ``False`` = Plugin nicht verfügbar (z. B. MQTT fehlt)."""
        return True

    def available(self) -> bool:
        """Ob das Plugin aktuell nutzbar ist (z. B. nach MQTT-Setup)."""
        return True

    @abstractmethod
    async def async_attach(self, ctx: SourceContext) -> CALLBACK_TYPE:
        """Beginnt zu lauschen und gibt eine Funktion zum Abmelden zurück."""

    async def async_discover(
        self, definition: Definition, source_config: dict[str, Any], inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Liefert Tasten-Rohdaten für ``dynamic: true``-Definitionen."""
        raise NotImplementedError

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name or self.key,
            "description": self.description,
            "available": self.available(),
            "supports_discovery": self.supports_discovery,
            "default_inputs": self.default_inputs,
            "origin": getattr(self, "_switchboard_origin", "builtin"),
        }


# ---------------------------------------------------------------------------
# Registrierung aus anderen Integrationen heraus
# ---------------------------------------------------------------------------


def async_register_plugin(
    hass: HomeAssistant, plugin_cls: type[SourcePlugin]
) -> Callable[[], None]:
    """Registriert ein Plugin aus einer anderen Integration.

    Kann vor oder nach dem Laden von Switchboard aufgerufen werden.
    Gibt eine Funktion zum Abmelden zurück.
    """
    from .registry import get_pending  # noqa: PLC0415 - Zirkelimport vermeiden

    return get_pending(hass).add_plugin(plugin_cls)


def async_register_definition(
    hass: HomeAssistant, raw: dict[str, Any], *, origin: str = "external"
) -> Callable[[], None]:
    """Registriert eine Schalter-Definition (Dict im YAML-Format) aus Code."""
    from .registry import get_pending  # noqa: PLC0415

    return get_pending(hass).add_definition(raw, origin)


def threadsafe_emit(
    hass: HomeAssistant, emit: Callable[[dict[str, Any]], None]
) -> Callable[[dict[str, Any]], None]:
    """Macht ``emit`` aus jedem Thread aufrufbar.

    Plugins dürfen ``ctx.emit`` auch aus Nicht-``@callback``-Handlern (die HA im
    Thread-Pool ausführt) oder eigenen Threads aufrufen.
    """
    import threading  # noqa: PLC0415

    def _emit(message: dict[str, Any]) -> None:
        if threading.get_ident() == hass.loop_thread_id:
            emit(message)
        else:
            hass.loop.call_soon_threadsafe(emit, message)

    return _emit
