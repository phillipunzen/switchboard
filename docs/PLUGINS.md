# Plugins (Ereignisquellen)

Ein Plugin hört auf *irgendetwas* – Event-Bus, MQTT, Webhooks, eine eigene Bibliothek – und reicht
jeden Tastendruck als einfaches Dict an Switchboard weiter. Welche Taste/Aktion das ist, entscheidet
die Definition per `match`. Das Plugin muss die Tasten also nicht kennen.

Stabile API: `custom_components.switchboard.api` (`API_VERSION = 1`).

## Minimal-Plugin

`/config/switchboard/plugins/mein_plugin.py`:

```python
from custom_components.switchboard.api import SourceContext, SourcePlugin


class MeinPlugin(SourcePlugin):
    key = "mein_plugin"           # wird in Definitionen als `source:` benutzt
    name = "Mein Plugin"
    description = "Kurzbeschreibung fürs Panel"
    default_inputs = [             # Eingaben, falls die Definition keine eigenen hat
        {"key": "identifier", "name": "Kennung", "required": True,
         "selector": {"text": {}}, "multiple": False},
    ]

    async def async_attach(self, ctx: SourceContext):
        def _handler(event):
            if event.data.get("id") == ctx.inputs["identifier"]:
                ctx.emit(dict(event.data))       # Nachricht an Switchboard

        remove = self.hass.bus.async_listen("mein_event", _handler)
        return remove                             # Funktion zum Abmelden


PLUGINS = [MeinPlugin]
DEFINITIONS = []   # optional: Definitionen als Dicts (Format wie YAML)
```

Danach *Plugins & Definitionen → Neu laden*.

## Die Basisklasse

| Mitglied | Zweck |
|---|---|
| `key`, `name`, `description` | Identität / Anzeige |
| `config_schema` | voluptuous-Schema für `source_config` der Definition |
| `default_inputs` | Eingabefelder (HA-Selector-Syntax) |
| `supports_discovery` + `async_discover()` | Tasten selbst ermitteln (`dynamic: true`) |
| `async_setup()` | einmalig beim Laden, `False` = nicht verfügbar |
| `available()` | Status fürs Panel (z. B. „MQTT fehlt“) |
| `async_attach(ctx)` | **Pflicht.** Lauschen starten, Abmelde-Funktion zurückgeben |

`SourceContext` enthält `switch_id`, `switch_name`, `definition`, `source_config` (validiert),
`inputs` (Nutzerwerte) und `emit(dict)`.

`ctx.emit()` ist thread-sicher – es darf aus `@callback`-Handlern, normalen Handlern
(die HA im Thread-Pool ausführt) und eigenen Threads aufgerufen werden.

## Automatische Erkennung

```python
supports_discovery = True

async def async_discover(self, definition, source_config, inputs):
    return [
        {"id": "taste_1", "name": "Taste 1", "match": {"button": 1},
         "actions": [{"id": "single", "name": "Kurz", "match": {"type": "single"}}]},
    ]
```

## Paket-Plugins

Größere Plugins als Ordner mit `__init__.py`; ein Unterordner `definitions/` wird automatisch
mitgeladen:

```
/config/switchboard/plugins/mein_plugin/
├── __init__.py          # PLUGINS = [...]
├── client.py            # relative Imports funktionieren
└── definitions/
    └── geraet_x.yaml
```

## Aus einer anderen Integration registrieren

```python
from custom_components.switchboard.api import async_register_plugin, async_register_definition

async def async_setup_entry(hass, entry):
    entry.async_on_unload(async_register_plugin(hass, MeinPlugin))
    entry.async_on_unload(async_register_definition(hass, {...}))
```

Funktioniert unabhängig davon, ob Switchboard schon geladen ist.

## Fehlerverhalten

Ein fehlerhaftes Plugin oder eine kaputte Definition bricht Switchboard nicht ab: Der Fehler steht
unter *Plugins & Definitionen → Ladefehler* und im Log, alles andere läuft weiter. Wirft
`async_attach` eine Ausnahme, zeigt der betroffene Schalter den Fehler an.
