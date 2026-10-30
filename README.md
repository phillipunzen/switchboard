# Switchboard

Zentrale Verwaltung für Funkschalter und Taster in Home Assistant – als Nachfolger-Idee zum
nicht mehr gepflegten [Switch Manager](https://github.com/Sian-Lee-SA/Home-Assistant-Switch-Manager).

Statt für jede Taste eine eigene Automation zu bauen, legst du im Panel **einen Schalter** an,
klickst auf dem Gerätebild eine Taste an und hinterlegst pro Aktion (kurz, doppelt, lang, …) eine
Sequenz. Die Automationsliste bleibt sauber.

## Was es kann

| | Switch Manager | Switchboard |
|---|---|---|
| Event-Bus (`zha_event`, `deconz_event`, `hue_event`, …) | ✅ | ✅ |
| MQTT / Zigbee2MQTT | ✅ | ✅ |
| **`event`-Entitäten** (Matter, Hue v2, ESPHome, Shelly Gen2+) | – | ✅ |
| **Geräte-Trigger** (ZHA, Z-Wave, Shelly, deCONZ, …) | – | ✅ |
| **Automatische Tasten-Erkennung** (keine Definition nötig) | – | ✅ |
| Zustand/Attribut einer Entität (z. B. Z2M-`sensor.*_action`) | – | ✅ |
| Virtueller Mehrfachdruck (2×/3× bei Geräten, die nur 1× kennen) | ✅ | ✅ |
| Visueller Sequenz-Editor + YAML | ✅ | ✅ (Fallback YAML) |
| Live-/Lernmodus: eingehende Ereignisse sehen, Treffer hervorheben | eingeschränkt | ✅ |
| **Eigene Plugins** (Python) für neue Ereignisquellen | – | ✅ |
| Eigene Schalter-Definitionen als YAML, Gerätebild mit Klickflächen | ✅ (Blueprints) | ✅ |
| `event`-Entität + Event `switchboard_action` pro Schalter | – | ✅ |
| Aktiv/Inaktiv als `switch`-Entität | – | ✅ |
| Import aus Switch Manager | – | ✅ |

## Installation

**HACS (benutzerdefiniertes Repository)**
1. HACS → ⋮ → *Benutzerdefinierte Repositories* → URL dieses Repos, Typ *Integration*.
2. „Switchboard“ installieren, Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Switchboard*.

**Manuell:** Ordner `custom_components/switchboard` nach `/config/custom_components/` kopieren,
neu starten, Integration hinzufügen.

Danach gibt es in der Seitenleiste den Eintrag **Switchboard** (nur für Admins).

## Erste Schritte

1. **＋ Schalter hinzufügen** → Definition wählen. Für Matter-Taster wie den IKEA BILRESA gibt es
   eine fertige Definition; für alles andere funktionieren meist
   *„Beliebige Event-Entitäten (automatisch)“* oder *„Beliebiges Gerät über Geräte-Trigger (automatisch)“*.
2. Eingaben ausfüllen (z. B. die beiden `event.*`-Entitäten des BILRESA).
   Bei automatischen Definitionen anschließend **Tasten erkennen**.
3. **● Zuhören** einschalten und am Gerät drücken: Das Panel zeigt jedes Rohereignis und welche
   Taste/Aktion getroffen wurde – so siehst du sofort, ob alles stimmt.
4. Taste anklicken, Aktion wählen, Sequenz hinterlegen, **Speichern**.

In Sequenzen stehen diese Variablen zur Verfügung:
`{{ button }}`, `{{ action }}`, `{{ presses }}`, `{{ switch_id }}`, `{{ switch_name }}` und
`{{ data }}` (komplettes Rohereignis, z. B. `{{ data.args }}`).

### Virtueller Mehrfachdruck
Tasten mit `virtual_multi_press` bekommen zusätzliche Aktionen wie „Drücken (2×)“. Switchboard
zählt die Drücke innerhalb des einstellbaren Fensters (Standard 400 ms). Solange für eine
Mehrfach-Aktion nichts hinterlegt ist, reagiert der Einfachdruck **ohne Verzögerung**.

### Normale Automationen weiter nutzen
Jeder Schalter erzeugt ein Gerät mit
- `event.<name>_tastenaktion` – Ereignistypen `<taste>_<aktion>`, z. B. `button_1_hold`
- `switch.<name>_aktiv` – Verarbeitung an/aus

Zusätzlich wird bei jedem Treffer das Event `switchboard_action` gefeuert
(`switch_id`, `button`, `action`, `presses`, `data`).

## Umstieg vom Switch Manager

*Plugins & Definitionen → Aus Switch Manager importieren* (oder Dienst `switchboard.import_switch_manager`).

- Blueprints werden zu Definitionen unter `/config/switchboard/definitions/imported/`.
- Schalter samt Sequenzen werden übernommen – **deaktiviert**, damit nichts doppelt auslöst.
- Vorgehen: importieren → prüfen → in Switchboard aktivieren → Switch Manager entfernen.

Der Import liest die Daten des Switch Managers nur, er verändert dort nichts.

## Erweitern

Alles Eigene liegt unter `/config/switchboard/` und überlebt Updates:

```
/config/switchboard/
├── definitions/          # eigene Schalter (YAML + optional Bild)
│   └── mein_taster.yaml
└── plugins/              # eigene Ereignisquellen (Python)
    ├── webhook_button.py
    └── mein_plugin/
        ├── __init__.py
        └── definitions/  # Definitionen, die das Plugin mitbringt
```

Nach Änderungen: *Plugins & Definitionen → Neu laden* (oder `switchboard.reload`) – kein Neustart nötig.

- **Neuer Schalter-Typ** → [docs/DEFINITIONS.md](docs/DEFINITIONS.md)
- **Neue Ereignisquelle** → [docs/PLUGINS.md](docs/PLUGINS.md), Beispiel:
  [examples/plugins/webhook_button.py](examples/plugins/webhook_button.py)

Eine Definition mit gleicher `id` wie eine mitgelieferte ersetzt diese – so lassen sich eingebaute
Definitionen anpassen, ohne die Integration anzufassen.

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component home-assistant-frontend
pytest                      # Backend-Tests gegen einen echten HA-Kern

cd frontend_src && npm install && npm run build   # Panel bauen
```

Das gebaute Panel (`custom_components/switchboard/frontend/switchboard-panel.js`) ist eingecheckt,
damit HACS-Installationen ohne Build-Schritt funktionieren.

## Lizenz
MIT
