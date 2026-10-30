"""Import aus dem Switch Manager (Sian-Lee-SA/Home-Assistant-Switch-Manager).

Liest – nur lesend – die Switch-Manager-Blueprints und dessen Speicherdatei,
erzeugt daraus Switchboard-Definitionen (YAML unter
``/config/switchboard/definitions/imported``) und legt die Schalter an.
Importierte Schalter sind **deaktiviert**, damit nichts doppelt auslöst, solange
Switch Manager noch läuft.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
from typing import Any

import yaml

from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import DOMAIN, USER_DEFINITIONS_DIR, USER_DIR

_LOGGER = logging.getLogger(__name__)


def _conditions(raw: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cond in raw or []:
        if isinstance(cond, dict) and "key" in cond:
            result[str(cond["key"])] = cond.get("value")
    return result


def _shape(button: dict[str, Any]) -> dict[str, Any] | None:
    if "d" in button:
        return {"type": "path", "d": button["d"]}
    if {"x", "y", "width", "height"} <= button.keys():
        shape = {
            "type": "circle" if button.get("shape") == "circle" else "rect",
            "x": button["x"],
            "y": button["y"],
            "width": button["width"],
            "height": button["height"],
        }
        if shape["type"] == "circle":
            shape["r"] = min(button["width"], button["height"]) / 2
            shape["x"] = button["x"] + button["width"] / 2
            shape["y"] = button["y"] + button["height"] / 2
        return shape
    return None


def convert_blueprint(bp_id: str, bp: dict[str, Any]) -> tuple[dict[str, Any], list[list[str]]]:
    """Switch-Manager-Blueprint -> Switchboard-Definition.

    Gibt zusätzlich die Aktions-IDs je Tasten-Index zurück (für das Mapping).
    """
    def_id = "sm_" + (slugify(bp_id) or "blueprint")
    topic_fmt = bp.get("mqtt_topic_format")
    event_type = str(bp.get("event_type", ""))
    if topic_fmt or event_type == "mqtt":
        source = "mqtt"
        topic = str(topic_fmt or "{}").replace("{}", "{identifier}")
        source_config = {"topic": topic, "payload": "json"}
    else:
        source = "event"
        source_config = {"event_type": event_type}
        if bp.get("identifier_key"):
            source_config["identifier_key"] = bp["identifier_key"]

    buttons = []
    action_ids: list[list[str]] = []
    for b_index, button in enumerate(bp.get("buttons") or [], start=1):
        actions = []
        ids: list[str] = []
        for a_index, action in enumerate(button.get("actions") or [], start=1):
            title = str(action.get("title") or f"aktion {a_index}")
            action_id = slugify(title) or f"action_{a_index}"
            if action_id in ids:
                action_id = f"{action_id}_{a_index}"
            ids.append(action_id)
            actions.append({"id": action_id, "name": title, "match": _conditions(action.get("conditions"))})
        entry: dict[str, Any] = {
            "id": f"b{b_index}",
            "name": f"Taste {b_index}",
            "match": _conditions(button.get("conditions")),
            "actions": actions,
        }
        if shape := _shape(button):
            entry["shape"] = shape
        buttons.append(entry)
        action_ids.append(ids)

    definition = {
        "id": def_id,
        "name": f"{bp.get('name', bp_id)} (Switch Manager)",
        "manufacturer": str(bp.get("service", "")),
        "integration": str(bp.get("service", "")),
        "description": f"Importiert aus Switch-Manager-Blueprint '{bp_id}'",
        "source": source,
        "source_config": source_config,
        "match": _conditions(bp.get("conditions")),
        "buttons": buttons,
    }
    return definition, action_ids


def _collect(config_dir: Path) -> dict[str, Any]:
    blueprints: dict[str, tuple[dict[str, Any], Path]] = {}
    folders = [
        config_dir / "custom_components" / "switch_manager" / "blueprints",
        config_dir / "blueprints" / "switch_manager",
    ]
    for folder in folders:
        if not folder.is_dir():
            continue
        for file in sorted(folder.glob("*.y*ml")):
            try:
                with file.open(encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
            except (OSError, yaml.YAMLError) as err:
                _LOGGER.warning("Blueprint %s nicht lesbar: %s", file, err)
                continue
            if isinstance(data, dict):
                blueprints[file.stem] = (data, file)

    store_file = config_dir / ".storage" / "switch_manager"
    switches: dict[str, Any] = {}
    if store_file.is_file():
        with store_file.open(encoding="utf-8") as fh:
            stored = json.load(fh)
        data = stored.get("data", {})
        switches = data.get("managed_switches") or data.get("switches") or {}
        if isinstance(switches, list):
            switches = {str(i): s for i, s in enumerate(switches)}
    return {"blueprints": blueprints, "switches": switches}


def _write_definitions(target: Path, items: list[tuple[dict[str, Any], Path]]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for definition, source_file in items:
        for ext in (".png", ".jpg", ".svg", ".webp"):
            img = source_file.with_suffix(ext)
            if img.is_file():
                dest = target / f"{definition['id']}{ext}"
                shutil.copyfile(img, dest)
                definition["image"] = dest.name
                break
        with (target / f"{definition['id']}.yaml").open("w", encoding="utf-8") as fh:
            yaml.safe_dump(definition, fh, allow_unicode=True, sort_keys=False)


async def async_import_switch_manager(hass: HomeAssistant) -> dict[str, Any]:
    manager = hass.data[DOMAIN]["manager"]
    config_dir = Path(hass.config.config_dir)
    collected = await hass.async_add_executor_job(_collect, config_dir)
    blueprints: dict[str, tuple[dict[str, Any], Path]] = collected["blueprints"]
    switches: dict[str, Any] = collected["switches"]

    used_bps = {str(s.get("blueprint")) for s in switches.values() if isinstance(s, dict)}
    to_write: list[tuple[dict[str, Any], Path]] = []
    action_map: dict[str, list[list[str]]] = {}
    def_ids: dict[str, str] = {}
    for bp_id in used_bps:
        if bp_id not in blueprints:
            continue
        bp, path = blueprints[bp_id]
        definition, ids = convert_blueprint(bp_id, bp)
        to_write.append((definition, path))
        action_map[bp_id] = ids
        def_ids[bp_id] = definition["id"]

    target = config_dir / USER_DIR / USER_DEFINITIONS_DIR / "imported"
    await hass.async_add_executor_job(_write_definitions, target, to_write)
    await manager.registry.async_load()

    imported: list[str] = []
    skipped: list[dict[str, str]] = []
    for sm_id, sm in switches.items():
        if not isinstance(sm, dict):
            continue
        name = str(sm.get("name") or f"Schalter {sm_id}")
        bp_id = str(sm.get("blueprint"))
        if bp_id not in def_ids:
            skipped.append({"name": name, "reason": f"Blueprint '{bp_id}' nicht gefunden"})
            continue
        ids = action_map[bp_id]
        definition = manager.registry.definitions.get(def_ids[bp_id])
        if definition is None:
            skipped.append({"name": name, "reason": "Definition ließ sich nicht laden"})
            continue
        actions: dict[str, Any] = {}
        for b_index, button in enumerate(sm.get("buttons") or []):
            for a_index, action in enumerate((button or {}).get("actions") or []):
                if b_index >= len(ids) or a_index >= len(ids[b_index]):
                    continue
                sequence = (action or {}).get("sequence") or []
                if not sequence:
                    continue
                actions[f"b{b_index + 1}.{ids[b_index][a_index]}"] = {
                    "mode": (action or {}).get("mode", "single"),
                    "sequence": sequence,
                }
        inputs: dict[str, Any] = {"identifier": sm.get("identifier", "")}
        config = {
            "id": "sm_" + (slugify(str(sm_id)) or "x"),
            "name": name,
            "definition": definition.id,
            "enabled": False,
            "inputs": inputs,
            "actions": actions,
            "variables": sm.get("variables") or {},
        }
        try:
            runtime = await manager.async_save(config)
            imported.append(runtime.name)
        except Exception as err:  # noqa: BLE001
            skipped.append({"name": name, "reason": str(err)})

    return {
        "definitions": [d["id"] for d, _ in to_write],
        "imported": imported,
        "skipped": skipped,
        "found_switches": len(switches),
    }
