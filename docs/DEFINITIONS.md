# Schalter-Definitionen

Eine Definition beschreibt einen Gerätetyp: woher die Ereignisse kommen (`source`), was der Nutzer
pro Schalter angeben muss (`inputs`) und welche Tasten und Aktionen es gibt (`buttons`).
Ablage: `/config/switchboard/definitions/*.yaml` (Unterordner erlaubt).

## Vollständiges Beispiel

```yaml
id: ikea_bilresa_dual          # optional, Standard = Dateiname; nur a-z 0-9 _
name: BILRESA Dual Button
manufacturer: IKEA
model: BILRESA (2 Tasten)
integration: Matter
description: Zwei Tasten, jeweils 1×/2× drücken sowie lang drücken/loslassen.

source: event_entity           # Schlüssel eines Plugins
source_config: {}              # plugin-spezifisch, siehe unten

inputs:                        # Eingaben pro Schalter (HA-Selector-Syntax)
  - key: button_1
    name: Taste 1 (oben)
    selector: {entity: {domain: event}}
  - key: button_2
    name: Taste 2 (unten)
    selector: {entity: {domain: event}}

match: {}                      # gilt für alle Tasten

image: ikea_bilresa_dual.svg   # relativ zur YAML-Datei, oder absolute URL
image_size: [200, 320]         # Koordinatensystem für die Klickflächen

buttons:
  - id: button_1
    name: Taste 1 (oben)
    shape: {type: rect, x: 40, y: 40, width: 120, height: 110, rx: 18}
    match: {input: button_1}
    actions:
      - {id: press,  name: 1× drücken,       match: {event_type: multi_press_1}}
      - {id: double, name: 2× drücken,       match: {event_type: multi_press_2}}
      - {id: hold,   name: Lang drücken,     match: {event_type: long_press}}
      - {id: release, name: Lang losgelassen, match: {event_type: long_release}}
```

## Matching

Jedes Ereignis kommt als Dict vom Plugin. Eine Aktion trifft, wenn **Definition-, Tasten- und
Aktions-`match`** alle zutreffen. Pro Taste gewinnt die erste passende Aktion.

| Schreibweise | Bedeutung |
|---|---|
| `command: "on"` | Gleichheit, typtolerant (`1` == `"1"`, `true` == `"True"`) |
| `command: [stop, stop_with_on_off]` | einer der Werte |
| `args.0: 254` / `params.button: 2` | Punkt-Pfad in verschachtelte Daten / Listen |
| `cluster_id: "*"` | Schlüssel muss nur vorhanden sein |

Tipp: Im Panel **● Zuhören** einschalten – dort steht das Rohereignis, aus dem du die Werte abliest.

> YAML-Falle: `on`, `off`, `yes`, `no` ohne Anführungszeichen werden zu `true`/`false`.
> Deshalb `id: "on"` und `command: "off"` immer quoten.

## Klickflächen (`shape`)

Koordinaten beziehen sich auf `image_size`. Typen: `rect` (`x`, `y`, `width`, `height`, `rx`),
`circle` (`x`, `y` = Mittelpunkt, `r`), `path` (`d` wie in SVG).
Ohne Bild/Shapes zeigt das Panel die Tasten als Liste.

## Virtueller Mehrfachdruck

```yaml
buttons:
  - id: "on"
    virtual_multi_press: {action: press, max_presses: 3}
    actions:
      - {id: press, match: {command: "on"}}
```

Erzeugt zusätzlich `press_2x` und `press_3x`.

## Automatische Definitionen

```yaml
id: meine_matter_taster
name: Matter-Taster
source: event_entity        # oder device_trigger
dynamic: true
```

Die Tasten werden beim Anlegen im Panel über **Tasten erkennen** ermittelt und mit dem Schalter
gespeichert. Funktioniert mit Plugins, die `supports_discovery` haben.

## `source_config` der mitgelieferten Plugins

| Plugin | Optionen | Standard-Eingabe |
|---|---|---|
| `event` | `event_type` (Pflicht), `identifier_key` (Pfad im Event), `identifier_input` (Standard `identifier`) | `identifier` (Text) |
| `event_entity` | – (Nachricht: `input`, `entity_id`, `event_type`, weitere Attribute) | `entities` (mehrere `event.*`) |
| `device_trigger` | `device_input` (Standard `device`), `include_entity_triggers` | `device` |
| `mqtt` | `topic` (Standard `zigbee2mqtt/{identifier}`, Platzhalter = Eingaben), `payload: json\|raw` | `identifier` |
| `state` | `attribute`, `entity_input` (Standard `entity`) | `entity` |

Hat eine Definition keine eigenen `inputs`, gelten die Standard-Eingaben des Plugins.
