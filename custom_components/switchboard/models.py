"""Datenmodell: Schalter-Definitionen, Tasten, Aktionen und Match-Logik."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .const import MAX_VIRTUAL_PRESSES

SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def _slug(value: Any) -> str:
    value = str(value)
    if not SLUG_RE.match(value):
        raise vol.Invalid(f"'{value}' ist keine gültige ID (nur a-z, 0-9, _)")
    return value


MATCH_SCHEMA = vol.Schema({cv.string: vol.Any(None, str, int, float, bool, list)})

SHAPE_SCHEMA = vol.Schema(
    {
        vol.Optional("type", default="rect"): vol.In(["rect", "circle", "path"]),
        vol.Optional("x"): vol.Coerce(float),
        vol.Optional("y"): vol.Coerce(float),
        vol.Optional("width"): vol.Coerce(float),
        vol.Optional("height"): vol.Coerce(float),
        vol.Optional("r"): vol.Coerce(float),
        vol.Optional("rx"): vol.Coerce(float),
        vol.Optional("d"): cv.string,
    }
)

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("id"): _slug,
        vol.Optional("name"): cv.string,
        vol.Optional("match", default=dict): MATCH_SCHEMA,
    }
)

VIRTUAL_MULTI_PRESS_SCHEMA = vol.Schema(
    {
        vol.Required("action"): _slug,
        vol.Optional("max_presses", default=3): vol.All(
            vol.Coerce(int), vol.Range(min=2, max=MAX_VIRTUAL_PRESSES)
        ),
    }
)

BUTTON_SCHEMA = vol.Schema(
    {
        vol.Required("id"): _slug,
        vol.Optional("name"): cv.string,
        vol.Optional("shape"): SHAPE_SCHEMA,
        vol.Optional("match", default=dict): MATCH_SCHEMA,
        vol.Optional("actions", default=list): [ACTION_SCHEMA],
        vol.Optional("virtual_multi_press"): VIRTUAL_MULTI_PRESS_SCHEMA,
    }
)

INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("key"): _slug,
        vol.Optional("name"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
        # HA-Selector-Definition, wird 1:1 an das Frontend gegeben
        vol.Optional("selector", default={"text": {}}): dict,
        vol.Optional("multiple", default=False): cv.boolean,
    }
)

DEFINITION_SCHEMA = vol.Schema(
    {
        vol.Required("id"): _slug,
        vol.Required("name"): cv.string,
        vol.Optional("manufacturer", default=""): cv.string,
        vol.Optional("model", default=""): cv.string,
        vol.Optional("integration", default=""): cv.string,
        vol.Optional("description", default=""): cv.string,
        vol.Required("source"): cv.string,
        vol.Optional("source_config", default=dict): dict,
        vol.Optional("inputs", default=list): [INPUT_SCHEMA],
        vol.Optional("match", default=dict): MATCH_SCHEMA,
        vol.Optional("image"): cv.string,
        vol.Optional("image_size"): vol.All([vol.Coerce(float)], vol.Length(2, 2)),
        vol.Optional("dynamic", default=False): cv.boolean,
        vol.Optional("buttons", default=list): [BUTTON_SCHEMA],
    },
    extra=vol.REMOVE_EXTRA,
)


# --------------------------------------------------------------------------
# Match-Logik
# --------------------------------------------------------------------------

_MISSING = object()


def get_path(data: Any, path: str) -> Any:
    """Liest einen Wert per Punkt-Pfad (``args.button``, ``params.0``)."""
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.isdigit():
            idx = int(part)
            if idx >= len(current):
                return _MISSING
            current = current[idx]
        else:
            return _MISSING
    return current


def _equal(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return str(actual).lower() == str(expected).lower()
    return str(actual) == str(expected)


def matches(data: dict[str, Any], match: dict[str, Any]) -> bool:
    """Prüft, ob ``data`` alle Bedingungen erfüllt.

    * Skalar: Gleichheit (typ-tolerant, ``1`` == ``"1"``)
    * Liste: einer der Werte
    * ``"*"``: Schlüssel muss existieren
    """
    for path, expected in match.items():
        actual = get_path(data, path)
        if expected == "*":
            if actual is _MISSING:
                return False
            continue
        if actual is _MISSING:
            return False
        if isinstance(expected, list):
            if not any(_equal(actual, e) for e in expected):
                return False
        elif not _equal(actual, expected):
            return False
    return True


# --------------------------------------------------------------------------
# Laufzeit-Objekte
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Action:
    id: str
    name: str
    match: dict[str, Any]
    virtual: bool = False
    presses: int = 1


@dataclass(slots=True)
class Button:
    id: str
    name: str
    match: dict[str, Any]
    actions: list[Action]
    shape: dict[str, Any] | None = None
    virtual_multi_press: dict[str, Any] | None = None

    def action(self, action_id: str) -> Action | None:
        return next((a for a in self.actions if a.id == action_id), None)


@dataclass(slots=True)
class Definition:
    id: str
    name: str
    source: str
    manufacturer: str = ""
    model: str = ""
    integration: str = ""
    description: str = ""
    source_config: dict[str, Any] = field(default_factory=dict)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    match: dict[str, Any] = field(default_factory=dict)
    image: str | None = None
    image_size: list[float] | None = None
    dynamic: bool = False
    buttons: list[Button] = field(default_factory=list)
    origin: str = "builtin"  # builtin | user | plugin:<key> | import
    path: str | None = None
    image_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "integration": self.integration,
            "description": self.description,
            "source": self.source,
            "source_config": self.source_config,
            "inputs": self.inputs,
            "dynamic": self.dynamic,
            "image_url": self.image_url,
            "image_size": self.image_size,
            "origin": self.origin,
            "buttons": [button_as_dict(b) for b in self.buttons],
        }


def button_as_dict(button: Button) -> dict[str, Any]:
    return {
        "id": button.id,
        "name": button.name,
        "shape": button.shape,
        "match": button.match,
        "virtual_multi_press": button.virtual_multi_press,
        "actions": [
            {
                "id": a.id,
                "name": a.name,
                "match": a.match,
                "virtual": a.virtual,
                "presses": a.presses,
            }
            for a in button.actions
        ],
    }


def build_buttons(raw_buttons: list[dict[str, Any]]) -> list[Button]:
    """Validiert Tasten-Rohdaten und ergänzt virtuelle Mehrfach-Aktionen."""
    buttons: list[Button] = []
    for raw in raw_buttons:
        raw = BUTTON_SCHEMA(raw)
        actions = [
            Action(id=a["id"], name=a.get("name") or a["id"], match=a["match"])
            for a in raw["actions"]
        ]
        vmp = raw.get("virtual_multi_press")
        if vmp:
            base = next((a for a in actions if a.id == vmp["action"]), None)
            if base is None:
                raise vol.Invalid(
                    f"virtual_multi_press verweist auf unbekannte Aktion '{vmp['action']}'"
                )
            for count in range(2, vmp["max_presses"] + 1):
                actions.append(
                    Action(
                        id=f"{base.id}_{count}x",
                        name=f"{base.name} ({count}×)",
                        match=base.match,
                        virtual=True,
                        presses=count,
                    )
                )
        buttons.append(
            Button(
                id=raw["id"],
                name=raw.get("name") or raw["id"],
                match=raw["match"],
                actions=actions,
                shape=raw.get("shape"),
                virtual_multi_press=vmp,
            )
        )
    ids = [b.id for b in buttons]
    if len(ids) != len(set(ids)):
        raise vol.Invalid("Tasten-IDs müssen eindeutig sein")
    return buttons


def build_definition(raw: dict[str, Any], *, origin: str, path: str | None = None) -> Definition:
    data = DEFINITION_SCHEMA(raw)
    if not data["dynamic"] and not data["buttons"]:
        raise vol.Invalid("Definition braucht 'buttons' oder 'dynamic: true'")
    return Definition(
        id=data["id"],
        name=data["name"],
        source=data["source"],
        manufacturer=data["manufacturer"],
        model=data["model"],
        integration=data["integration"],
        description=data["description"],
        source_config=data["source_config"],
        inputs=data["inputs"],
        match=data["match"],
        image=data.get("image"),
        image_size=data.get("image_size"),
        dynamic=data["dynamic"],
        buttons=build_buttons(data["buttons"]) if data["buttons"] else [],
        origin=origin,
        path=path,
    )
