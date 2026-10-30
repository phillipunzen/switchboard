"""Laufzeit: verbindet konfigurierte Schalter mit Quellen und führt Sequenzen aus."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.script import (
    SCRIPT_MODE_CHOICES,
    SCRIPT_MODE_SINGLE,
    Script,
    async_validate_actions_config,
)
from homeassistant.helpers.storage import Store

from .api import SourceContext, threadsafe_emit
from .const import (
    DEFAULT_PRESS_TIMEOUT_MS,
    DOMAIN,
    EVENT_ACTION,
    SIGNAL_DEBUG,
    SIGNAL_SWITCH_FIRED,
    SIGNAL_SWITCHES_CHANGED,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .models import Action, Button, Definition, build_buttons, matches
from .registry import Registry

_LOGGER = logging.getLogger(__name__)

ACTION_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional("mode", default=SCRIPT_MODE_SINGLE): vol.In(SCRIPT_MODE_CHOICES),
        vol.Optional("max", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional("sequence", default=list): vol.Any(list, dict),
        vol.Optional("enabled", default=True): cv.boolean,
    },
    extra=vol.REMOVE_EXTRA,
)

SWITCH_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1)),
        vol.Required("definition"): cv.string,
        vol.Optional("enabled", default=True): cv.boolean,
        vol.Optional("inputs", default=dict): dict,
        vol.Optional("press_timeout_ms", default=DEFAULT_PRESS_TIMEOUT_MS): vol.All(
            vol.Coerce(int), vol.Range(min=100, max=3000)
        ),
        vol.Optional("buttons"): vol.Any(None, list),
        vol.Optional("actions", default=dict): {cv.string: ACTION_CONFIG_SCHEMA},
        vol.Optional("variables", default=dict): dict,
        vol.Optional("icon"): vol.Any(None, cv.string),
        vol.Optional("area_id"): vol.Any(None, cv.string),
    },
    extra=vol.REMOVE_EXTRA,
)


def action_key(button_id: str, action_id: str) -> str:
    return f"{button_id}.{action_id}"


@dataclass
class _PressState:
    count: int = 0
    cancel: CALLBACK_TYPE | None = None
    message: dict[str, Any] = field(default_factory=dict)


class SwitchRuntime:
    """Ein konfigurierter Schalter zur Laufzeit."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: SwitchManager,
        config: dict[str, Any],
        definition: Definition | None,
    ) -> None:
        self.hass = hass
        self.manager = manager
        self.config = config
        self.definition = definition
        self.buttons: list[Button] = []
        self.scripts: dict[str, Script] = {}
        self.error: str | None = None
        self.last_event: dict[str, Any] | None = None
        self._unsub: CALLBACK_TYPE | None = None
        self._presses: dict[str, _PressState] = {}

    @property
    def id(self) -> str:
        return self.config["id"]

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    @property
    def running(self) -> bool:
        return self._unsub is not None

    def event_types(self) -> list[str]:
        return [f"{b.id}_{a.id}" for b in self.buttons for a in b.actions]

    # ------------------------------------------------------------------
    async def async_start(self) -> None:
        self.error = None
        if self.definition is None:
            self.error = f"Definition '{self.config['definition']}' nicht gefunden"
            return
        try:
            if self.definition.dynamic:
                self.buttons = build_buttons(self.config.get("buttons") or [])
            else:
                self.buttons = self.definition.buttons
            await self._build_scripts()
        except (vol.Invalid, HomeAssistantError) as err:
            self.error = f"Konfiguration ungültig: {err}"
            _LOGGER.error("Schalter '%s': %s", self.name, self.error)
            return
        if not self.enabled:
            return

        plugin = self.manager.registry.plugins.get(self.definition.source)
        if plugin is None:
            self.error = f"Quelle '{self.definition.source}' nicht geladen"
            return
        try:
            source_config = plugin.config_schema(self.definition.source_config)
            ctx = SourceContext(
                switch_id=self.id,
                switch_name=self.name,
                definition=self.definition,
                source_config=source_config,
                inputs=self.config.get("inputs", {}),
                emit=threadsafe_emit(self.hass, self.async_handle_message),
            )
            self._unsub = await plugin.async_attach(ctx)
        except Exception as err:  # noqa: BLE001 - Plugin-Fehler isolieren
            self.error = f"Quelle konnte nicht starten: {err}"
            _LOGGER.exception("Schalter '%s': Quelle %s fehlgeschlagen", self.name, plugin.key)

    async def _build_scripts(self) -> None:
        self.scripts = {}
        actions_cfg: dict[str, Any] = self.config.get("actions", {})
        for button in self.buttons:
            for action in button.actions:
                key = action_key(button.id, action.id)
                cfg = actions_cfg.get(key)
                if not cfg or not cfg.get("enabled", True):
                    continue
                sequence = cfg.get("sequence") or []
                if isinstance(sequence, dict):
                    sequence = [sequence]
                if not sequence:
                    continue
                validated = await async_validate_actions_config(
                    self.hass, cv.SCRIPT_SCHEMA(sequence)
                )
                self.scripts[key] = Script(
                    self.hass,
                    validated,
                    f"{self.name}: {button.name} – {action.name}",
                    DOMAIN,
                    running_description="Switchboard-Aktion",
                    script_mode=cfg.get("mode", SCRIPT_MODE_SINGLE),
                    max_runs=cfg.get("max", 10),
                    logger=_LOGGER,
                )

    @callback
    def async_stop(self) -> None:
        if self._unsub is not None:
            try:
                self._unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Fehler beim Abmelden von '%s'", self.name)
            self._unsub = None
        for state in self._presses.values():
            if state.cancel:
                state.cancel()
        self._presses.clear()

    async def async_shutdown(self) -> None:
        self.async_stop()
        for script in self.scripts.values():
            await script.async_stop()

    # ------------------------------------------------------------------
    @callback
    def match_message(self, message: dict[str, Any]) -> list[tuple[Button, Action]]:
        return match_buttons(self.definition, self.buttons, message)

    @callback
    def async_handle_message(self, message: dict[str, Any]) -> None:
        """Wird vom Plugin für jede Rohnachricht aufgerufen."""
        hits = self.match_message(message)
        async_dispatcher_send(
            self.hass,
            SIGNAL_DEBUG.format(self.id),
            {
                "message": message,
                "matches": [{"button": b.id, "action": a.id} for b, a in hits],
            },
        )
        for button, action in hits:
            self._dispatch(button, action, message)

    def _has_virtual_scripts(self, button: Button) -> bool:
        return any(
            action_key(button.id, a.id) in self.scripts for a in button.actions if a.virtual
        )

    @callback
    def _dispatch(self, button: Button, action: Action, message: dict[str, Any]) -> None:
        vmp = button.virtual_multi_press
        if not vmp or vmp["action"] != action.id or not self._has_virtual_scripts(button):
            self._fire(button, action, 1, message)
            return

        state = self._presses.setdefault(button.id, _PressState())
        state.count += 1
        state.message = message
        if state.cancel:
            state.cancel()
            state.cancel = None

        if state.count >= vmp["max_presses"]:
            self._flush(button, action)
            return

        timeout = self.config.get("press_timeout_ms", DEFAULT_PRESS_TIMEOUT_MS) / 1000

        @callback
        def _timeout(_now: Any) -> None:
            state.cancel = None
            self._flush(button, action)

        state.cancel = async_call_later(self.hass, timeout, _timeout)

    @callback
    def _flush(self, button: Button, base: Action) -> None:
        state = self._presses.pop(button.id, None)
        if state is None or state.count == 0:
            return
        if state.cancel:
            state.cancel()
        target = base if state.count == 1 else button.action(f"{base.id}_{state.count}x")
        if target is None:
            target = base
        self._fire(button, target, state.count, state.message)

    @callback
    def _fire(self, button: Button, action: Action, presses: int, message: dict[str, Any]) -> None:
        data = {
            "switch_id": self.id,
            "switch_name": self.name,
            "button": button.id,
            "button_name": button.name,
            "action": action.id,
            "action_name": action.name,
            "presses": presses,
        }
        self.last_event = data
        context = Context()
        self.hass.bus.async_fire(EVENT_ACTION, {**data, "data": message}, context=context)
        async_dispatcher_send(self.hass, SIGNAL_SWITCH_FIRED.format(self.id), data)

        script = self.scripts.get(action_key(button.id, action.id))
        if script is None:
            return
        variables = {
            **self.config.get("variables", {}),
            **data,
            "data": message,
        }
        self.hass.async_create_task(
            self._run(script, variables, context),
            f"switchboard {self.name} {button.id}.{action.id}",
            eager_start=True,
        )

    async def _run(self, script: Script, variables: dict[str, Any], context: Context) -> None:
        try:
            await script.async_run(variables, context=context)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Fehler in Sequenz %s", script.name)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.config,
            "definition_name": self.definition.name if self.definition else None,
            "running": self.running,
            "error": self.error,
            "last_event": self.last_event,
            "resolved_buttons": [
                {
                    "id": b.id,
                    "name": b.name,
                    "shape": b.shape,
                    "virtual_multi_press": b.virtual_multi_press,
                    "actions": [
                        {"id": a.id, "name": a.name, "virtual": a.virtual, "presses": a.presses}
                        for a in b.actions
                    ],
                }
                for b in self.buttons
            ],
        }


def match_buttons(
    definition: Definition | None, buttons: list[Button], message: dict[str, Any]
) -> list[tuple[Button, Action]]:
    """Ermittelt (Taste, Aktion) für eine Nachricht – je Taste die erste passende Aktion."""
    if definition is not None and definition.match and not matches(message, definition.match):
        return []
    hits: list[tuple[Button, Action]] = []
    for button in buttons:
        if not matches(message, button.match):
            continue
        for action in button.actions:
            if action.virtual:
                continue
            if matches(message, action.match):
                hits.append((button, action))
                break
    return hits


class SwitchManager:
    """Verwaltet alle konfigurierten Schalter samt Speicherung."""

    def __init__(self, hass: HomeAssistant, registry: Registry) -> None:
        self.hass = hass
        self.registry = registry
        self.store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.configs: dict[str, dict[str, Any]] = {}
        self.runtimes: dict[str, SwitchRuntime] = {}
        self._remove_listener: Callable[[], None] | None = None

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.configs = data.get("switches", {})
        for config in self.configs.values():
            await self._start(config)
        self._remove_listener = self.registry.async_add_listener(
            lambda: self.hass.async_create_task(self.async_restart_all())
        )

    async def async_shutdown(self) -> None:
        if self._remove_listener:
            self._remove_listener()
        for runtime in list(self.runtimes.values()):
            await runtime.async_shutdown()
        self.runtimes.clear()

    async def async_restart_all(self) -> None:
        for runtime in list(self.runtimes.values()):
            await runtime.async_shutdown()
        self.runtimes.clear()
        for config in self.configs.values():
            await self._start(config)
        async_dispatcher_send(self.hass, SIGNAL_SWITCHES_CHANGED)

    async def _start(self, config: dict[str, Any]) -> SwitchRuntime:
        definition = self.registry.definitions.get(config["definition"])
        runtime = SwitchRuntime(self.hass, self, config, definition)
        await runtime.async_start()
        self.runtimes[config["id"]] = runtime
        return runtime

    async def _async_save(self) -> None:
        await self.store.async_save({"switches": self.configs})

    # ------------------------------------------------------------------
    async def async_validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validiert eine Schalter-Konfiguration vollständig (inkl. Sequenzen)."""
        config = SWITCH_CONFIG_SCHEMA(raw)
        definition = self.registry.definitions.get(config["definition"])
        if definition is None:
            raise vol.Invalid(f"Unbekannte Definition '{config['definition']}'")
        for spec in self.registry.inputs_for(definition):
            if spec.get("required", True) and config["inputs"].get(spec["key"]) in (None, "", []):
                raise vol.Invalid(f"Eingabe '{spec.get('name', spec['key'])}' fehlt")
        if definition.dynamic:
            if not config.get("buttons"):
                config["buttons"] = await self.async_discover(definition, config["inputs"])
            buttons = build_buttons(config["buttons"])
        else:
            config["buttons"] = None
            buttons = definition.buttons
        valid_keys = {action_key(b.id, a.id) for b in buttons for a in b.actions}
        for key, cfg in config["actions"].items():
            if key not in valid_keys:
                raise vol.Invalid(f"Unbekannte Aktion '{key}'")
            seq = cfg.get("sequence") or []
            if isinstance(seq, dict):
                seq = [seq]
            try:
                await async_validate_actions_config(self.hass, cv.SCRIPT_SCHEMA(seq))
            except (vol.Invalid, HomeAssistantError) as err:
                raise vol.Invalid(f"Sequenz für '{key}' ungültig: {err}") from err
        return config

    async def async_discover(
        self, definition: Definition, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        plugin = self.registry.plugins.get(definition.source)
        if plugin is None or not plugin.supports_discovery:
            raise vol.Invalid(f"Quelle '{definition.source}' unterstützt keine Erkennung")
        source_config = plugin.config_schema(definition.source_config)
        buttons = await plugin.async_discover(definition, source_config, inputs)
        if not buttons:
            raise vol.Invalid("Keine Tasten gefunden – stimmen die Eingaben?")
        build_buttons(buttons)  # validieren
        return buttons

    async def async_save(self, raw: dict[str, Any]) -> SwitchRuntime:
        config = await self.async_validate(raw)
        switch_id = config.get("id") or uuid.uuid4().hex[:12]
        config["id"] = switch_id
        if (old := self.runtimes.pop(switch_id, None)) is not None:
            await old.async_shutdown()
        self.configs[switch_id] = config
        await self._async_save()
        runtime = await self._start(config)
        async_dispatcher_send(self.hass, SIGNAL_SWITCHES_CHANGED)
        return runtime

    async def async_delete(self, switch_id: str) -> None:
        if switch_id not in self.configs:
            raise vol.Invalid("Schalter nicht gefunden")
        if (runtime := self.runtimes.pop(switch_id, None)) is not None:
            await runtime.async_shutdown()
        del self.configs[switch_id]
        await self._async_save()
        dev_reg = dr.async_get(self.hass)
        if device := dev_reg.async_get_device(identifiers={(DOMAIN, switch_id)}):
            dev_reg.async_remove_device(device.id)
        async_dispatcher_send(self.hass, SIGNAL_SWITCHES_CHANGED)

    async def async_set_enabled(self, switch_id: str, enabled: bool) -> None:
        if switch_id not in self.configs:
            raise vol.Invalid("Schalter nicht gefunden")
        self.configs[switch_id]["enabled"] = enabled
        await self._async_save()
        if (runtime := self.runtimes.pop(switch_id, None)) is not None:
            await runtime.async_shutdown()
        await self._start(self.configs[switch_id])
        async_dispatcher_send(self.hass, SIGNAL_SWITCHES_CHANGED)

    async def async_import(self, configs: list[dict[str, Any]]) -> list[str]:
        """Übernimmt bereits validierte Konfigurationen (Importer)."""
        ids = []
        for config in configs:
            runtime = await self.async_save(config)
            ids.append(runtime.id)
        return ids
