"""End-to-End-Tests gegen einen echten Home-Assistant-Kern."""

from datetime import timedelta
import json
from pathlib import Path

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.util import dt as dt_util

from custom_components.switchboard.const import EVENT_ACTION
from custom_components.switchboard.models import matches

IEEE = "84:fd:27:ff:fe:00:00:01"


def test_matches():
    data = {"command": "on", "args": [1, 2], "params": {"x": 5}, "flag": True}
    assert matches(data, {"command": "on"})
    assert matches(data, {"command": ["off", "on"]})
    assert matches(data, {"args.1": 2, "params.x": "5"})
    assert matches(data, {"flag": "true"})
    assert matches(data, {"params": "*"})
    assert not matches(data, {"missing": "*"})
    assert not matches(data, {"command": "off"})


async def test_setup_loads_builtins(hass, setup):
    registry = setup.registry
    assert set(registry.plugins) == {"event", "event_entity", "device_trigger", "mqtt", "state"}
    assert registry.errors == []
    assert "ikea_bilresa_dual" in registry.definitions
    assert "zha_hue_dimmer" in registry.definitions
    e1743 = registry.definitions["zha_ikea_e1743"]
    assert [b.id for b in e1743.buttons] == ["on", "off"]
    assert e1743.image_url == "/switchboard_static/builtin/ikea_e1743.svg"
    # virtuelle Aktionen erzeugt
    assert [a.id for a in e1743.buttons[0].actions][-2:] == ["press_2x", "press_3x"]


async def test_event_bus_switch(hass, setup):
    calls = async_mock_service(hass, "test", "on_pressed")
    fired = async_capture_events(hass, EVENT_ACTION)
    runtime = await setup.async_save(
        {
            "name": "Flur",
            "definition": "zha_ikea_e1743",
            "inputs": {"identifier": IEEE},
            "actions": {
                "on.press": {
                    "sequence": [
                        {"action": "test.on_pressed", "data": {"btn": "{{ button }}", "n": "{{ presses }}"}}
                    ]
                }
            },
        }
    )
    await hass.async_block_till_done()
    assert runtime.running and runtime.error is None

    # Fremdes Gerät ignorieren
    hass.bus.async_fire("zha_event", {"device_ieee": "aa", "command": "on"})
    hass.bus.async_fire("zha_event", {"device_ieee": IEEE.upper(), "command": "on"})
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data == {"btn": "on", "n": 1}
    assert fired[0].data["button"] == "on" and fired[0].data["action"] == "press"

    # Event-Entität und Enable-Switch existieren
    states = [s for s in hass.states.async_all() if s.entity_id.startswith(("event.flur", "switch.flur"))]
    ids = {s.entity_id for s in states}
    assert "event.flur_tastenaktion" in ids or any(i.startswith("event.flur") for i in ids)
    event_state = next(s for s in states if s.domain == "event")
    assert event_state.attributes["event_type"] == "on_press"
    assert "off_hold" in event_state.attributes["event_types"]

    # Über Switch deaktivieren
    switch_id = next(s.entity_id for s in states if s.domain == "switch")
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch_id}, blocking=True)
    hass.bus.async_fire("zha_event", {"device_ieee": IEEE, "command": "on"})
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert hass.states.get(switch_id).state == "off"


async def test_virtual_multi_press(hass, setup):
    single = async_mock_service(hass, "test", "single")
    double = async_mock_service(hass, "test", "double")
    await setup.async_save(
        {
            "name": "Bad",
            "definition": "zha_ikea_e1743",
            "inputs": {"identifier": IEEE},
            "press_timeout_ms": 300,
            "actions": {
                "on.press": {"sequence": [{"action": "test.single"}]},
                "on.press_2x": {"sequence": [{"action": "test.double"}]},
            },
        }
    )
    for _ in range(2):
        hass.bus.async_fire("zha_event", {"device_ieee": IEEE, "command": "on"})
    await hass.async_block_till_done()
    assert not single and not double
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert len(double) == 1 and not single

    hass.bus.async_fire("zha_event", {"device_ieee": IEEE, "command": "on"})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    assert len(single) == 1


async def test_event_entity_bilresa(hass, setup):
    calls = async_mock_service(hass, "test", "hit")
    attrs = {"event_types": ["multi_press_1", "multi_press_2", "long_press", "long_release"]}
    hass.states.async_set("event.bilresa_1", "unknown", attrs)
    hass.states.async_set("event.bilresa_2", "unknown", attrs)
    await setup.async_save(
        {
            "name": "Wohnzimmer Mobil",
            "definition": "ikea_bilresa_dual",
            "inputs": {"button_1": "event.bilresa_1", "button_2": "event.bilresa_2"},
            "actions": {
                "button_2.hold": {"sequence": [{"action": "test.hit", "data": {"a": "{{ action }}"}}]}
            },
        }
    )
    hass.states.async_set("event.bilresa_2", "2026-10-30T10:00:00", {**attrs, "event_type": "long_press"})
    await hass.async_block_till_done()
    assert len(calls) == 1 and calls[0].data["a"] == "hold"

    # Rückkehr aus unavailable darf nicht auslösen
    hass.states.async_set("event.bilresa_2", "unavailable", attrs)
    hass.states.async_set("event.bilresa_2", "2026-10-30T10:00:00", {**attrs, "event_type": "long_press"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_dynamic_event_entities(hass, setup):
    hass.states.async_set(
        "event.taster_eins", "unknown", {"event_types": ["press", "long_press"], "friendly_name": "Taster Eins"}
    )
    definition = setup.registry.definitions["generic_event_entities"]
    buttons = await setup.async_discover(definition, {"entities": ["event.taster_eins"]})
    assert buttons[0]["id"] == "taster_eins"
    assert [a["id"] for a in buttons[0]["actions"]] == ["press", "long_press"]
    assert buttons[0]["virtual_multi_press"]["action"] == "press"

    calls = async_mock_service(hass, "test", "x")
    runtime = await setup.async_save(
        {
            "name": "Dyn",
            "definition": "generic_event_entities",
            "inputs": {"entities": ["event.taster_eins"]},
            "actions": {"taster_eins.long_press": {"sequence": [{"action": "test.x"}]}},
        }
    )
    assert runtime.config["buttons"]
    hass.states.async_set("event.taster_eins", "t1", {"event_types": ["press", "long_press"], "event_type": "long_press"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_validation_errors(hass, setup):
    with pytest.raises(vol.Invalid, match="fehlt"):
        await setup.async_save({"name": "x", "definition": "zha_ikea_e1743"})
    with pytest.raises(vol.Invalid, match="Unbekannte Aktion"):
        await setup.async_save(
            {"name": "x", "definition": "zha_ikea_e1743", "inputs": {"identifier": IEEE},
             "actions": {"on.nope": {"sequence": []}}}
        )
    with pytest.raises(vol.Invalid, match="ungültig"):
        await setup.async_save(
            {"name": "x", "definition": "zha_ikea_e1743", "inputs": {"identifier": IEEE},
             "actions": {"on.press": {"sequence": [{"not_an_action": 1}]}}}
        )


async def test_user_plugin_and_definition(hass, setup):
    """Eigenes Plugin + Definition aus /config/switchboard/ laden."""
    base = Path(hass.config.path("switchboard"))
    (base / "plugins").mkdir(parents=True, exist_ok=True)
    (base / "plugins" / "webhook_demo.py").write_text(
        '''
from custom_components.switchboard.api import SourcePlugin

class Demo(SourcePlugin):
    key = "demo"
    name = "Demo"
    async def async_attach(self, ctx):
        def _h(event):
            ctx.emit(dict(event.data))
        return self.hass.bus.async_listen("demo_press", _h)

PLUGINS = [Demo]
DEFINITIONS = [{
    "id": "demo_switch", "name": "Demo", "source": "demo",
    "buttons": [{"id": "a", "actions": [{"id": "press", "match": {"k": 1}}]}],
}]
''',
        encoding="utf-8",
    )
    (base / "definitions").mkdir(parents=True, exist_ok=True)
    (base / "definitions" / "kaputt.yaml").write_text("name: ohne quelle\n", encoding="utf-8")

    await setup.registry.async_load()
    await hass.async_block_till_done()
    assert "demo" in setup.registry.plugins
    assert setup.registry.plugins["demo"].as_dict()["origin"] == "plugin:webhook_demo"
    assert "demo_switch" in setup.registry.definitions
    assert any("kaputt.yaml" in e["source"] for e in setup.registry.errors)

    calls = async_mock_service(hass, "test", "demo")
    await setup.async_save(
        {"name": "Demo", "definition": "demo_switch",
         "actions": {"a.press": {"sequence": [{"action": "test.demo"}]}}}
    )
    hass.bus.async_fire("demo_press", {"k": "1"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_api_register_from_integration(hass, setup):
    from custom_components.switchboard.api import async_register_definition

    remove = async_register_definition(
        hass,
        {"id": "ext_def", "name": "Ext", "source": "event", "source_config": {"event_type": "x"},
         "buttons": [{"id": "b", "actions": [{"id": "p"}]}]},
    )
    await hass.async_block_till_done()
    assert "ext_def" in setup.registry.definitions
    remove()
    await hass.async_block_till_done()
    assert "ext_def" not in setup.registry.definitions


async def test_websocket(hass, setup, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "switchboard/info"})
    res = await client.receive_json()
    assert res["success"] and len(res["result"]["definitions"]) >= 7

    await client.send_json(
        {"id": 2, "type": "switchboard/switches/save",
         "config": {"name": "WS", "definition": "zha_ikea_e1743", "inputs": {"identifier": IEEE}}}
    )
    res = await client.receive_json()
    assert res["success"], res
    sid = res["result"]["id"]

    await client.send_json({"id": 3, "type": "switchboard/subscribe", "switch_id": sid})
    assert (await client.receive_json())["success"]
    hass.bus.async_fire("zha_event", {"device_ieee": IEEE, "command": "off"})
    msg = await client.receive_json()
    assert msg["event"]["matches"] == [{"button": "off", "action": "press"}]

    await client.send_json({"id": 4, "type": "switchboard/validate_sequence", "sequence": [{"delay": "x"}]})
    assert (await client.receive_json())["result"]["valid"] is False

    await client.send_json(
        {"id": 5, "type": "switchboard/listen", "definition": "zha_hue_dimmer", "inputs": {"identifier": "ab"}}
    )
    assert (await client.receive_json())["success"]
    hass.bus.async_fire("zha_event", {"device_ieee": "ab", "command": "up_hold"})
    msg = await client.receive_json()
    assert msg["id"] == 5 and msg["event"]["matches"] == [{"button": "up", "action": "hold"}]

    await client.send_json({"id": 6, "type": "switchboard/switches/delete", "switch_id": sid})
    assert (await client.receive_json())["success"]
    assert sid not in setup.configs


async def test_persistence(hass, setup):
    await setup.async_save({"name": "P", "definition": "zha_ikea_e1743", "inputs": {"identifier": IEEE}})
    await hass.async_block_till_done()
    data = await setup.store.async_load()
    assert len(data["switches"]) == 1


async def test_import_switch_manager(hass, setup):
    cfg = Path(hass.config.config_dir)
    (cfg / "blueprints" / "switch_manager").mkdir(parents=True, exist_ok=True)
    (cfg / "blueprints" / "switch_manager" / "zha-ikea-e1743.yaml").write_text(
        """
name: IKEA E1743
service: ZHA
event_type: zha_event
identifier_key: device_ieee
buttons:
  - x: 10
    y: 10
    width: 50
    height: 40
    actions:
      - title: press
        conditions: [{key: command, value: "on"}]
      - title: hold
        conditions: [{key: command, value: move_with_on_off}]
  - x: 10
    y: 60
    width: 50
    height: 40
    actions:
      - title: press
        conditions: [{key: command, value: "off"}]
""",
        encoding="utf-8",
    )
    (cfg / ".storage").mkdir(exist_ok=True)
    (cfg / ".storage" / "switch_manager").write_text(
        json.dumps(
            {"version": 1, "key": "switch_manager", "data": {"managed_switches": {
                "1": {"name": "Alt", "blueprint": "zha-ikea-e1743", "identifier": IEEE, "enabled": True,
                      "buttons": [{"actions": [{"mode": "single", "sequence": [{"action": "test.imp"}]}, {}]},
                                  {"actions": [{}]}]}}}}
        ),
        encoding="utf-8",
    )
    from custom_components.switchboard.importer import async_import_switch_manager

    result = await async_import_switch_manager(hass)
    assert result["imported"] == ["Alt"], result
    runtime = setup.runtimes["sm_1"]
    assert runtime.enabled is False
    assert runtime.config["actions"] == {"b1.press": {"mode": "single", "max": 10, "enabled": True,
                                                       "sequence": [{"action": "test.imp"}]}}

    calls = async_mock_service(hass, "test", "imp")
    await setup.async_set_enabled("sm_1", True)
    hass.bus.async_fire("zha_event", {"device_ieee": IEEE, "command": "on"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_unload(hass, setup):
    entry = hass.config_entries.async_entries("switchboard")[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_mqtt_z2m(hass, mqtt_mock, setup):
    from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

    calls = async_mock_service(hass, "test", "z2m")
    runtime = await setup.async_save(
        {
            "name": "Z2M Dimmer",
            "definition": "z2m_hue_dimmer",
            "inputs": {"identifier": "Flur Dimmer"},
            "actions": {"up.hold": {"sequence": [{"action": "test.z2m"}]}},
        }
    )
    assert runtime.running, runtime.error
    async_fire_mqtt_message(hass, "zigbee2mqtt/Flur Dimmer", '{"action": "up_hold", "battery": 90}')
    async_fire_mqtt_message(hass, "zigbee2mqtt/Flur Dimmer", '{"action": "", "battery": 90}')
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_mqtt_z2m_sonoff_snzb_01m(hass, mqtt_mock, setup):
    from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

    definition = setup.registry.definitions["z2m_sonoff_snzb_01m"]
    assert [b.id for b in definition.buttons] == ["button_1", "button_2", "button_3", "button_4"]

    calls = async_mock_service(hass, "test", "snzb")
    runtime = await setup.async_save(
        {
            "name": "SONOFF 4-fach",
            "definition": "z2m_sonoff_snzb_01m",
            "inputs": {"identifier": "Taster Flur"},
            "actions": {"button_3.double": {"sequence": [{"action": "test.snzb"}]}},
        }
    )
    assert runtime.running, runtime.error
    async_fire_mqtt_message(hass, "zigbee2mqtt/Taster Flur", '{"action": "single_button_3"}')
    async_fire_mqtt_message(hass, "zigbee2mqtt/Taster Flur", '{"action": "double_button_3"}')
    async_fire_mqtt_message(hass, "zigbee2mqtt/Taster Flur", '{"action": "double_button_4"}')
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_device_trigger_source(hass, setup):
    """Geräte-Trigger-Pfad mit entitätsbasierten Triggern einer Lampe testen."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    from homeassistant.setup import async_setup_component
    from custom_components.switchboard.api import async_register_definition

    assert await async_setup_component(hass, "light", {})
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, "12:34:56:ab:cd:ef")}
    )
    er.async_get(hass).async_get_or_create("light", "test", "5678", device_id=device.id)
    hass.states.async_set("light.test_5678", "off")

    async_register_definition(
        hass,
        {"id": "dt_test", "name": "DT", "source": "device_trigger", "dynamic": True,
         "source_config": {"include_entity_triggers": True}},
    )
    await hass.async_block_till_done()
    definition = setup.registry.definitions["dt_test"]
    buttons = await setup.async_discover(definition, {"device": device.id})
    action_ids = {a["id"] for b in buttons for a in b["actions"]}
    assert "turned_on" in action_ids, buttons

    button_id = next(b["id"] for b in buttons if any(a["id"] == "turned_on" for a in b["actions"]))
    calls = async_mock_service(hass, "test", "dt")
    runtime = await setup.async_save(
        {"name": "DT", "definition": "dt_test", "inputs": {"device": device.id},
         "actions": {f"{button_id}.turned_on": {"sequence": [{"action": "test.dt"}]}}}
    )
    assert runtime.running, runtime.error
    hass.states.async_set("light.test_5678", "on")
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_example_webhook_plugin(hass, setup, hass_client_no_auth):
    """Das mitgelieferte Beispiel-Plugin muss so funktionieren wie dokumentiert."""
    import shutil

    target = Path(hass.config.path("switchboard", "plugins"))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).parent.parent / "examples" / "plugins" / "webhook_button.py", target)
    await setup.registry.async_load()
    await hass.async_block_till_done()
    assert "webhook" in setup.registry.plugins, setup.registry.errors

    calls = async_mock_service(hass, "test", "wh")
    await setup.async_save(
        {"name": "Wand", "definition": "webhook_3_buttons", "inputs": {"webhook_id": "geheim123"},
         "actions": {"button_2.long": {"sequence": [{"action": "test.wh"}]}}}
    )
    client = await hass_client_no_auth()
    resp = await client.post("/api/webhook/geheim123?button=2&action=long")
    assert resp.status == 200
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_import_switch_manager_mqtt_wildcard(hass, mqtt_mock, setup):
    """Nachbau der echten Konfiguration: Z2M-Blueprint mit Wildcard-Topic.

    Ein Druck auf Phillips Schalter darf nicht Marlenes Sequenz auslösen.
    """
    from pytest_homeassistant_custom_component.common import async_fire_mqtt_message
    from custom_components.switchboard.importer import async_import_switch_manager, mqtt_identifier

    assert mqtt_identifier("Bett", "zigbee2mqtt/+/action") == "zigbee2mqtt/Bett/action"
    assert mqtt_identifier("zigbee2mqtt/Bett/action", "zigbee2mqtt/+/action") == "zigbee2mqtt/Bett/action"

    cfg = Path(hass.config.config_dir)
    bp_dir = cfg / "blueprints" / "switch_manager"
    bp_dir.mkdir(parents=True, exist_ok=True)
    (bp_dir / "zigbee2mqtt-aqara-wireless-mini-switch.yaml").write_text(
        """
name: Aqara Wireless Mini Switch
service: Zigbee2MQTT
event_type: mqtt
mqtt_topic_format: zigbee2mqtt/+/action
buttons:
  - actions:
      - title: press
        conditions: [{key: payload, value: single}]
      - title: press 2x
        conditions: [{key: payload, value: double}]
""",
        encoding="utf-8",
    )
    # 1x1-PNG daneben, um die Bildgröße zu prüfen
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000040000000200806000000"
        "0000000000"
    )
    (bp_dir / "zigbee2mqtt-aqara-wireless-mini-switch.png").write_bytes(png)
    (cfg / ".storage").mkdir(exist_ok=True)
    (cfg / ".storage" / "switch_manager").write_text(
        json.dumps({"version": 1, "key": "switch_manager", "data": {"managed_switches": {
            "3": {"name": "Phillip", "blueprint": "zigbee2mqtt-aqara-wireless-mini-switch",
                  "identifier": "zigbee2mqtt/Bett Schalter Phillip/action",
                  "buttons": [{"actions": [{"mode": "single", "sequence": [{"action": "test.phillip"}]}]}]},
            "8": {"name": "Marlene", "blueprint": "zigbee2mqtt-aqara-wireless-mini-switch",
                  "identifier": "Bett Schalter Marlene",
                  "buttons": [{"actions": [{"mode": "single", "sequence": [{"action": "test.marlene"}]}]}]},
        }}}),
        encoding="utf-8",
    )
    result = await async_import_switch_manager(hass)
    assert sorted(result["imported"]) == ["Marlene", "Phillip"]
    definition = setup.registry.definitions["sm_zigbee2mqtt_aqara_wireless_mini_switch"]
    assert definition.source_config["topic"] == "{identifier}"
    assert definition.image_size == [64.0, 32.0]
    assert setup.configs["sm_8"]["inputs"]["identifier"] == "zigbee2mqtt/Bett Schalter Marlene/action"

    phillip = async_mock_service(hass, "test", "phillip")
    marlene = async_mock_service(hass, "test", "marlene")
    await setup.async_set_enabled("sm_3", True)
    await setup.async_set_enabled("sm_8", True)
    async_fire_mqtt_message(hass, "zigbee2mqtt/Bett Schalter Phillip/action", "single")
    await hass.async_block_till_done()
    assert len(phillip) == 1 and len(marlene) == 0
    async_fire_mqtt_message(hass, "zigbee2mqtt/Bett Schalter Marlene/action", "single")
    async_fire_mqtt_message(hass, "zigbee2mqtt/Bett Schalter Marlene/action", "double")
    await hass.async_block_till_done()
    assert len(phillip) == 1 and len(marlene) == 1
