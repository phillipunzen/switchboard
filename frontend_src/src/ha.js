// Hilfen für das Zusammenspiel mit dem Home-Assistant-Frontend.

let loading;

/**
 * Lädt die (lazy geladenen) HA-Editor-Elemente wie ha-automation-action,
 * ha-selector und ha-yaml-editor, indem das Config-Panel vorgeladen wird.
 * Schlägt das fehl, nutzt das Panel eigene Fallback-Eingaben.
 */
export function ensureHaElements() {
  if (!loading) {
    loading = (async () => {
      try {
        if (!customElements.get("ha-automation-action")) {
          const resolver = document.createElement("partial-panel-resolver");
          const routes = resolver._getRoutes?.([{ component_name: "config", url_path: "a" }]);
          await routes?.routes?.a?.load?.();
          const config = document.createElement("ha-panel-config");
          await config?.routerOptions?.routes?.automation?.load?.();
          await config?.routerOptions?.routes?.script?.load?.();
        }
      } catch (err) {
        // eslint-disable-next-line no-console
        console.info("Switchboard: HA-Editor-Elemente nicht verfügbar, nutze YAML", err);
      }
      await Promise.race([
        customElements.whenDefined("ha-automation-action"),
        new Promise((r) => setTimeout(r, 4000)),
      ]);
      return {
        actionEditor: !!customElements.get("ha-automation-action"),
        selector: !!customElements.get("ha-selector"),
      };
    })();
  }
  return loading;
}

export const ws = {
  info: (hass) => hass.callWS({ type: "switchboard/info" }),
  list: (hass) => hass.callWS({ type: "switchboard/switches/list" }),
  save: (hass, config) => hass.callWS({ type: "switchboard/switches/save", config }),
  remove: (hass, switch_id) => hass.callWS({ type: "switchboard/switches/delete", switch_id }),
  setEnabled: (hass, switch_id, enabled) =>
    hass.callWS({ type: "switchboard/switches/set_enabled", switch_id, enabled }),
  discover: (hass, definition, inputs) =>
    hass.callWS({ type: "switchboard/discover", definition, inputs }),
  validate: (hass, sequence) => hass.callWS({ type: "switchboard/validate_sequence", sequence }),
  reload: (hass) => hass.callWS({ type: "switchboard/reload" }),
  importSM: (hass) => hass.callWS({ type: "switchboard/import_switch_manager" }),
  listen: (hass, definition, inputs, buttons, cb) =>
    hass.connection.subscribeMessage(cb, {
      type: "switchboard/listen",
      definition,
      inputs,
      ...(buttons ? { buttons } : {}),
    }),
};

export function fireEvent(node, type, detail) {
  node.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
}
