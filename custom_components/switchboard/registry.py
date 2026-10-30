"""Registry für Plugins (Ereignisquellen) und Schalter-Definitionen."""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
import logging
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.core import HomeAssistant, callback

from .api import SourcePlugin
from .const import DOMAIN, STATIC_BASE, USER_DEFINITIONS_DIR, USER_DIR, USER_PLUGINS_DIR
from .models import Definition, build_definition
from .plugins import BUILTIN_PLUGINS

_LOGGER = logging.getLogger(__name__)

BUILTIN_DEFINITIONS = Path(__file__).parent / "definitions"
PENDING_KEY = f"{DOMAIN}_pending"


class Pending:
    """Sammelt Registrierungen anderer Integrationen (auch vor unserem Setup)."""

    def __init__(self) -> None:
        self.plugins: list[type[SourcePlugin]] = []
        self.definitions: list[tuple[dict[str, Any], str]] = []
        self.listener: Callable[[], None] | None = None

    def _changed(self) -> None:
        if self.listener:
            self.listener()

    def add_plugin(self, plugin_cls: type[SourcePlugin]) -> Callable[[], None]:
        self.plugins.append(plugin_cls)
        self._changed()

        def remove() -> None:
            if plugin_cls in self.plugins:
                self.plugins.remove(plugin_cls)
                self._changed()

        return remove

    def add_definition(self, raw: dict[str, Any], origin: str) -> Callable[[], None]:
        item = (raw, origin)
        self.definitions.append(item)
        self._changed()

        def remove() -> None:
            if item in self.definitions:
                self.definitions.remove(item)
                self._changed()

        return remove


def get_pending(hass: HomeAssistant) -> Pending:
    return hass.data.setdefault(PENDING_KEY, Pending())


class Registry:
    """Hält alle geladenen Plugins und Definitionen."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.plugins: dict[str, SourcePlugin] = {}
        self.definitions: dict[str, Definition] = {}
        self.errors: list[dict[str, str]] = []
        self.user_dir = Path(hass.config.path(USER_DIR))
        self._listeners: list[Callable[[], None]] = []

    # -- Listener ---------------------------------------------------------
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # -- Laden --------------------------------------------------------------
    async def async_load(self) -> None:
        """(Neu-)Lädt alle Plugins und Definitionen."""
        self.errors = []
        plugins: dict[str, SourcePlugin] = {}
        user_modules = await self.hass.async_add_executor_job(self._import_user_plugins)

        candidates: list[tuple[type[SourcePlugin], str]] = [
            (cls, "builtin") for cls in BUILTIN_PLUGINS
        ]
        extra_defs: list[tuple[dict[str, Any], str]] = []
        for module, origin in user_modules:
            for cls in getattr(module, "PLUGINS", []):
                candidates.append((cls, origin))
            for raw in getattr(module, "DEFINITIONS", []):
                extra_defs.append((raw, origin))

        pending = get_pending(self.hass)
        candidates.extend((cls, "external") for cls in pending.plugins)
        extra_defs.extend(pending.definitions)

        for cls, origin in candidates:
            try:
                if not (isinstance(cls, type) and issubclass(cls, SourcePlugin)):
                    raise TypeError(f"{cls!r} ist keine SourcePlugin-Klasse")
                if not cls.key:
                    raise ValueError(f"{cls.__name__} hat keinen 'key'")
                plugin = cls(self.hass)
                plugin._switchboard_origin = origin  # type: ignore[attr-defined]
                if not await plugin.async_setup():
                    _LOGGER.debug("Plugin %s nicht verfügbar", cls.key)
                if cls.key in plugins:
                    _LOGGER.warning(
                        "Plugin '%s' aus %s überschreibt vorhandenes Plugin", cls.key, origin
                    )
                plugins[cls.key] = plugin
            except Exception as err:  # noqa: BLE001 - fremder Code
                _LOGGER.exception("Plugin %r aus %s konnte nicht geladen werden", cls, origin)
                self.errors.append({"source": origin, "error": f"Plugin: {err}"})
        self.plugins = plugins

        definitions: dict[str, Definition] = {}
        raw_files = await self.hass.async_add_executor_job(self._read_definition_files)
        for raw, origin, path in raw_files:
            self._add_definition(definitions, raw, origin, path)
        for raw, origin in extra_defs:
            self._add_definition(definitions, raw, origin, None)
        self.definitions = definitions

        pending.listener = lambda: self.hass.async_create_task(self.async_load())
        _LOGGER.info(
            "Switchboard: %d Plugins, %d Definitionen geladen (%d Fehler)",
            len(self.plugins),
            len(self.definitions),
            len(self.errors),
        )
        self._notify()

    def _add_definition(
        self,
        target: dict[str, Definition],
        raw: Any,
        origin: str,
        path: Path | None,
    ) -> None:
        label = str(path) if path else origin
        try:
            if not isinstance(raw, dict):
                raise vol.Invalid("Definition muss ein Mapping sein")
            if "id" not in raw and path is not None:
                raw = {**raw, "id": path.stem.replace("-", "_").lower()}
            definition = build_definition(raw, origin=origin, path=str(path) if path else None)
            if definition.source not in self.plugins:
                raise vol.Invalid(f"Unbekannte Quelle '{definition.source}'")
            definition.image_url = self._image_url(definition, path, origin)
            if definition.id in target:
                _LOGGER.info(
                    "Definition '%s' aus %s überschreibt %s",
                    definition.id,
                    label,
                    target[definition.id].origin,
                )
            target[definition.id] = definition
        except (vol.Invalid, ValueError, TypeError) as err:
            _LOGGER.error("Ungültige Definition %s: %s", label, err)
            self.errors.append({"source": label, "error": str(err)})

    def _image_url(self, definition: Definition, path: Path | None, origin: str) -> str | None:
        if not definition.image:
            return None
        if definition.image.startswith(("http://", "https://", "/")):
            return definition.image
        if path is None:
            return None
        if origin == "builtin":
            return f"{STATIC_BASE}/builtin/{definition.image}"
        try:
            rel = path.parent.relative_to(self.user_dir)
        except ValueError:
            return None
        rel_str = "" if str(rel) == "." else f"{rel.as_posix()}/"
        return f"{STATIC_BASE}/user/{rel_str}{definition.image}"

    # -- Executor-Jobs ------------------------------------------------------
    def _read_definition_files(self) -> list[tuple[Any, str, Path]]:
        result: list[tuple[Any, str, Path]] = []
        sources = [(BUILTIN_DEFINITIONS, "builtin")]
        user_defs = self.user_dir / USER_DEFINITIONS_DIR
        user_defs.mkdir(parents=True, exist_ok=True)
        (self.user_dir / USER_PLUGINS_DIR).mkdir(parents=True, exist_ok=True)
        sources.append((user_defs, "user"))
        # Plugins dürfen Definitionen in einem eigenen Unterordner mitbringen
        plugin_root = self.user_dir / USER_PLUGINS_DIR
        for sub in sorted(plugin_root.glob("*/definitions")):
            sources.append((sub, f"plugin:{sub.parent.name}"))

        for folder, origin in sources:
            for file in sorted(folder.rglob("*.y*ml")):
                try:
                    with file.open(encoding="utf-8") as fh:
                        raw = yaml.safe_load(fh)
                    result.append((raw, origin, file))
                except (OSError, yaml.YAMLError) as err:
                    _LOGGER.error("Definition %s nicht lesbar: %s", file, err)
                    self.errors.append({"source": str(file), "error": str(err)})
        return result

    def _import_user_plugins(self) -> list[tuple[ModuleType, str]]:
        """Importiert /config/switchboard/plugins/*.py und */__init__.py."""
        plugin_dir = self.user_dir / USER_PLUGINS_DIR
        plugin_dir.mkdir(parents=True, exist_ok=True)
        modules: list[tuple[ModuleType, str]] = []
        targets = [p for p in sorted(plugin_dir.glob("*.py")) if not p.name.startswith("_")]
        targets += [p / "__init__.py" for p in sorted(plugin_dir.iterdir()) if (p / "__init__.py").is_file()]
        for file in targets:
            name = file.stem if file.name != "__init__.py" else file.parent.name
            mod_name = f"switchboard_user_plugins.{name}"
            try:
                spec = importlib.util.spec_from_file_location(
                    mod_name,
                    file,
                    submodule_search_locations=[str(file.parent)]
                    if file.name == "__init__.py"
                    else None,
                )
                if spec is None or spec.loader is None:
                    raise ImportError("kein Loader")
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module  # neu laden = ersetzen
                spec.loader.exec_module(module)
                modules.append((module, f"plugin:{name}"))
            except Exception as err:  # noqa: BLE001 - fremder Code
                _LOGGER.exception("Plugin-Datei %s konnte nicht geladen werden", file)
                self.errors.append({"source": str(file), "error": f"{type(err).__name__}: {err}"})
        return modules

    # -- Zugriff ------------------------------------------------------------
    def plugin_for(self, definition: Definition) -> SourcePlugin:
        return self.plugins[definition.source]

    def inputs_for(self, definition: Definition) -> list[dict[str, Any]]:
        if definition.inputs:
            return definition.inputs
        plugin = self.plugins.get(definition.source)
        return list(plugin.default_inputs) if plugin else []

    def as_dict(self) -> dict[str, Any]:
        defs = []
        for d in self.definitions.values():
            item = d.as_dict()
            item["inputs"] = self.inputs_for(d)
            defs.append(item)
        defs.sort(key=lambda d: (d["manufacturer"].lower(), d["name"].lower()))
        return {
            "plugins": [p.as_dict() for p in self.plugins.values()],
            "definitions": defs,
            "errors": self.errors,
        }
