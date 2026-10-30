import { LitElement, html, svg, css, nothing } from "lit";
import yaml from "js-yaml";
import { ensureHaElements, ws } from "./ha.js";

const MODES = [
  ["single", "Einzeln (single)"],
  ["restart", "Neu starten (restart)"],
  ["queued", "Warteschlange (queued)"],
  ["parallel", "Parallel (parallel)"],
];

const clone = (o) => JSON.parse(JSON.stringify(o ?? null));
const actionKey = (b, a) => `${b}.${a}`;

class SwitchboardPanel extends LitElement {
  static properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    panel: { attribute: false },
    _info: { state: true },
    _switches: { state: true },
    _view: { state: true },
    _edit: { state: true },
    _picker: { state: true },
    _filter: { state: true },
    _caps: { state: true },
    _toast: { state: true },
    _busy: { state: true },
  };

  constructor() {
    super();
    this._view = "list";
    this._switches = [];
    this._caps = { actionEditor: false, selector: false };
    this._filter = "";
  }

  connectedCallback() {
    super.connectedCallback();
    ensureHaElements().then((caps) => (this._caps = caps));
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._stopListen();
  }

  updated(changed) {
    if (changed.has("hass") && this.hass && !this._info) this._load();
  }

  async _load() {
    try {
      const [info, switches] = await Promise.all([ws.info(this.hass), ws.list(this.hass)]);
      this._info = info;
      this._switches = switches;
    } catch (err) {
      this._notify(`Laden fehlgeschlagen: ${err.message || err}`);
    }
  }

  _notify(text) {
    this._toast = text;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => (this._toast = undefined), 4500);
  }

  _definition(id) {
    return this._info?.definitions.find((d) => d.id === id);
  }

  // ------------------------------------------------------------------ Render
  render() {
    if (!this.hass) return nothing;
    return html`
      <div class="toolbar">
        <ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>
        ${this._view === "edit"
          ? html`<button class="icon" title="Zurück" @click=${this._closeEditor}>←</button>`
          : nothing}
        <div class="title">${this._title()}</div>
        <nav>
          <button class=${this._view !== "info" ? "tab on" : "tab"} @click=${() => this._go("list")}>Schalter</button>
          <button class=${this._view === "info" ? "tab on" : "tab"} @click=${() => this._go("info")}>Plugins &amp; Definitionen</button>
        </nav>
      </div>
      <div class="content">
        ${!this._info
          ? html`<div class="empty">Lade …</div>`
          : this._view === "info"
            ? this._renderInfo()
            : this._view === "edit"
              ? this._renderEditor()
              : this._renderList()}
      </div>
      ${this._picker ? this._renderPicker() : nothing}
      ${this._toast ? html`<div class="toast">${this._toast}</div>` : nothing}
    `;
  }

  _title() {
    if (this._view === "edit" && this._edit)
      return this._edit.config.name || "Neuer Schalter";
    return "Switchboard";
  }

  async _go(view) {
    if (this._view === "edit" && !(await this._confirmDiscard())) return;
    this._stopListen();
    this._edit = undefined;
    this._view = view;
  }

  async _confirmDiscard() {
    if (!this._edit?.dirty) return true;
    return confirm("Ungespeicherte Änderungen verwerfen?");
  }

  // ------------------------------------------------------------------ Liste
  _renderList() {
    const errors = this._info.errors?.length;
    return html`
      ${errors
        ? html`<div class="banner warn" @click=${() => this._go("info")}>
            ${errors} Plugin/Definition(en) konnten nicht geladen werden – Details unter „Plugins &amp; Definitionen“.
          </div>`
        : nothing}
      <div class="list">
        ${this._switches.length === 0
          ? html`<div class="empty card">
              <h2>Noch keine Schalter</h2>
              <p>Lege einen Schalter an, wähle die passende Definition und hinterlege pro Taste eine Aktion.</p>
              <p class="muted">Kommst du vom Switch Manager? Unter „Plugins &amp; Definitionen“ gibt es einen Import.</p>
            </div>`
          : this._switches.map((s) => this._renderSwitchRow(s))}
      </div>
      <button class="fab" @click=${() => (this._picker = true)}>＋ Schalter hinzufügen</button>
    `;
  }

  _renderSwitchRow(s) {
    const configured = Object.values(s.actions || {}).filter((a) => (a.sequence || []).length).length;
    const status = s.error ? "error" : !s.enabled ? "off" : s.running ? "on" : "off";
    const label = s.error ? "Fehler" : !s.enabled ? "Deaktiviert" : "Aktiv";
    return html`
      <div class="card row" @click=${() => this._openEditor(s)}>
        <div class="dot ${status}"></div>
        <div class="grow">
          <div class="name">${s.name}</div>
          <div class="muted">${s.definition_name || s.definition} · ${configured} Aktion(en)</div>
          ${s.error ? html`<div class="err">${s.error}</div>` : nothing}
        </div>
        <span class="chip ${status}">${label}</span>
        <label class="switch" @click=${(e) => e.stopPropagation()}>
          <input type="checkbox" .checked=${s.enabled} @change=${(e) => this._toggle(s, e.target.checked)} />
          <span></span>
        </label>
      </div>
    `;
  }

  async _toggle(s, enabled) {
    try {
      await ws.setEnabled(this.hass, s.id, enabled);
      this._switches = await ws.list(this.hass);
    } catch (err) {
      this._notify(err.message || String(err));
    }
  }

  // ------------------------------------------------------------------ Definition wählen
  _renderPicker() {
    const f = this._filter.toLowerCase();
    const defs = this._info.definitions.filter((d) =>
      [d.name, d.manufacturer, d.model, d.integration].join(" ").toLowerCase().includes(f)
    );
    const groups = {};
    for (const d of defs) (groups[d.manufacturer || "Sonstige"] ||= []).push(d);
    return html`
      <div class="backdrop" @click=${() => (this._picker = false)}>
        <div class="dialog" @click=${(e) => e.stopPropagation()}>
          <h2>Definition wählen</h2>
          <input class="search" placeholder="Suchen (Hersteller, Modell, Integration) …" .value=${this._filter}
            @input=${(e) => (this._filter = e.target.value)} autofocus />
          <div class="picklist">
            ${Object.entries(groups).map(
              ([m, list]) => html`
                <div class="group">${m}</div>
                ${list.map(
                  (d) => html`
                    <button class="pick" @click=${() => this._newSwitch(d)}>
                      ${d.image_url ? html`<img src=${d.image_url} alt="" />` : html`<div class="noimg">⌘</div>`}
                      <div>
                        <div class="name">${d.name}</div>
                        <div class="muted">${[d.model, d.integration].filter(Boolean).join(" · ")}
                          ${d.dynamic ? html`<span class="chip">automatisch</span>` : nothing}</div>
                      </div>
                    </button>
                  `
                )}
              `
            )}
            ${defs.length === 0 ? html`<div class="empty">Keine Treffer</div>` : nothing}
          </div>
          <div class="actions"><button @click=${() => (this._picker = false)}>Abbrechen</button></div>
        </div>
      </div>
    `;
  }

  _newSwitch(def) {
    this._picker = false;
    this._filter = "";
    const config = {
      name: def.name,
      definition: def.id,
      enabled: true,
      inputs: {},
      press_timeout_ms: 400,
      actions: {},
      buttons: null,
    };
    this._startEdit(config, true);
  }

  _openEditor(s) {
    const config = {
      id: s.id,
      name: s.name,
      definition: s.definition,
      enabled: s.enabled,
      inputs: clone(s.inputs) || {},
      press_timeout_ms: s.press_timeout_ms ?? 400,
      actions: clone(s.actions) || {},
      buttons: clone(s.buttons),
      variables: clone(s.variables) || {},
    };
    this._startEdit(config, false, s);
  }

  _startEdit(config, isNew, saved) {
    const def = this._definition(config.definition);
    this._edit = {
      config,
      isNew,
      error: saved?.error,
      dirty: isNew,
      selButton: undefined,
      selAction: undefined,
      yaml: {},
      yamlMode: !this._caps.actionEditor,
      log: [],
      flash: undefined,
      listening: false,
    };
    this._view = "edit";
    const buttons = this._buttons();
    if (buttons.length) this._select(buttons[0].id);
    if (def?.dynamic && !config.buttons) this._edit = { ...this._edit, needsDiscover: true };
  }

  async _closeEditor() {
    if (!(await this._confirmDiscard())) return;
    this._stopListen();
    this._edit = undefined;
    this._view = "list";
    this._load();
  }

  _buttons() {
    const e = this._edit;
    if (!e) return [];
    const def = this._definition(e.config.definition);
    if (!def) return [];
    if (!def.dynamic) return def.buttons;
    return (e.config.buttons || []).map((b) => withVirtual(b));
  }

  _patch(patch, dirty = true) {
    this._edit = { ...this._edit, ...patch, dirty: dirty || this._edit.dirty };
  }

  _patchConfig(patch) {
    this._patch({ config: { ...this._edit.config, ...patch } });
  }

  _select(buttonId, actionId) {
    const button = this._buttons().find((b) => b.id === buttonId);
    if (!button) return;
    const action = actionId || this._edit.selAction;
    const valid = button.actions.find((a) => a.id === action) ? action : button.actions[0]?.id;
    this._patch({ selButton: buttonId, selAction: valid }, false);
  }

  // ------------------------------------------------------------------ Editor
  _renderEditor() {
    const e = this._edit;
    const def = this._definition(e.config.definition);
    if (!def)
      return html`<div class="card err">Definition „${e.config.definition}“ ist nicht (mehr) geladen.</div>`;
    const buttons = this._buttons();
    return html`
      <div class="editor ${this.narrow ? "narrow" : ""}">
        <div class="side">
          <div class="card">
            <label class="field"><span>Name</span>
              <input .value=${e.config.name} @input=${(ev) => this._patchConfig({ name: ev.target.value })} />
            </label>
            <div class="muted small">${def.manufacturer} ${def.name}${def.model ? ` · ${def.model}` : ""}
              · Quelle: <code>${def.source}</code></div>
            ${def.description ? html`<p class="muted small">${def.description}</p>` : nothing}
            ${def.inputs.map((spec) => this._renderInput(spec))}
            ${def.dynamic
              ? html`<button class="secondary" ?disabled=${this._busy} @click=${this._discover}>
                  ${e.config.buttons ? "Tasten neu erkennen" : "Tasten erkennen"}</button>`
              : nothing}
            ${buttons.some((b) => b.virtual_multi_press)
              ? html`<label class="field"><span>Mehrfachdruck-Fenster (ms)</span>
                  <input type="number" min="100" max="3000" step="50" .value=${String(e.config.press_timeout_ms)}
                    @input=${(ev) => this._patchConfig({ press_timeout_ms: Number(ev.target.value) })} />
                </label>`
              : nothing}
            ${e.error ? html`<div class="err">${e.error}</div>` : nothing}
          </div>
          ${buttons.length ? this._renderDevice(def, buttons) : nothing}
          ${this._renderLive()}
        </div>
        <div class="main">
          ${e.needsDiscover && !buttons.length
            ? html`<div class="card empty">Diese Definition ermittelt die Tasten automatisch.<br />
                Eingaben ausfüllen und „Tasten erkennen“ klicken.</div>`
            : this._renderActionEditor(buttons)}
        </div>
      </div>
      <div class="savebar">
        ${!e.isNew ? html`<button class="danger" @click=${this._delete}>Löschen</button>` : nothing}
        <div class="grow"></div>
        <button @click=${this._closeEditor}>Abbrechen</button>
        <button class="primary" ?disabled=${this._busy || !e.dirty} @click=${this._save}>Speichern</button>
      </div>
    `;
  }

  _renderInput(spec) {
    const value = this._edit.config.inputs[spec.key];
    const set = (v) => this._patchConfig({ inputs: { ...this._edit.config.inputs, [spec.key]: v } });
    const label = `${spec.name || spec.key}${spec.required ? " *" : ""}`;
    if (this._caps.selector) {
      return html`<div class="field">
        <ha-selector .hass=${this.hass} .selector=${spec.selector} .value=${value} .label=${label}
          .required=${spec.required} @value-changed=${(ev) => set(ev.detail.value)}></ha-selector>
        ${spec.description ? html`<div class="muted small">${spec.description}</div>` : nothing}
      </div>`;
    }
    // Fallback ohne HA-Selector
    const sel = spec.selector || {};
    const multiple = spec.multiple || sel.entity?.multiple;
    let options = [];
    if (sel.entity) {
      const domain = sel.entity.domain;
      options = Object.keys(this.hass.states)
        .filter((id) => !domain || id.startsWith(`${domain}.`))
        .map((id) => [id, this.hass.states[id].attributes.friendly_name || id]);
    } else if (sel.device) {
      options = Object.values(this.hass.devices || {}).map((d) => [d.id, d.name_by_user || d.name || d.id]);
    }
    const listId = `opts-${spec.key}`;
    const display = Array.isArray(value) ? value.join(", ") : value ?? "";
    return html`<label class="field"><span>${label}</span>
      <input list=${listId} .value=${display}
        @change=${(ev) => {
          const raw = ev.target.value.trim();
          set(multiple ? raw.split(",").map((s) => s.trim()).filter(Boolean) : raw);
        }} />
      <datalist id=${listId}>${options.map(([v, n]) => html`<option value=${v}>${n}</option>`)}</datalist>
      ${spec.description ? html`<span class="muted small">${spec.description}</span>` : nothing}
      ${multiple ? html`<span class="muted small">Mehrere Werte mit Komma trennen.</span>` : nothing}
    </label>`;
  }

  _renderDevice(def, buttons) {
    const e = this._edit;
    const hasShapes = def.image_size && buttons.some((b) => b.shape);
    const counts = (b) =>
      b.actions.filter((a) => (e.config.actions[actionKey(b.id, a.id)]?.sequence || []).length).length;
    if (!hasShapes) {
      return html`<div class="card buttons">
        ${buttons.map(
          (b) => html`<button class="btnchip ${e.selButton === b.id ? "sel" : ""} ${e.flash === b.id ? "flash" : ""}"
            @click=${() => this._select(b.id)}>${b.name}${counts(b) ? html`<span class="badge">${counts(b)}</span>` : nothing}</button>`
        )}
      </div>`;
    }
    const [w, h] = def.image_size;
    return html`<div class="card device">
      <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
        ${def.image_url ? svg`<image href=${def.image_url} x="0" y="0" width=${w} height=${h}></image>` : nothing}
        ${buttons.map((b) => this._shape(b, e, counts(b)))}
      </svg>
      <div class="muted small center">Taste anklicken zum Bearbeiten</div>
    </div>`;
  }

  _shape(b, e, count) {
    if (!b.shape) return nothing;
    const s = b.shape;
    const cls = `shape ${e.selButton === b.id ? "sel" : ""} ${e.flash === b.id ? "flash" : ""} ${count ? "has" : ""}`;
    const click = () => this._select(b.id);
    let el;
    if (s.type === "circle")
      el = svg`<circle class=${cls} cx=${s.x} cy=${s.y} r=${s.r ?? 20} @click=${click}><title>${b.name}</title></circle>`;
    else if (s.type === "path")
      el = svg`<path class=${cls} d=${s.d} @click=${click}><title>${b.name}</title></path>`;
    else
      el = svg`<rect class=${cls} x=${s.x} y=${s.y} width=${s.width} height=${s.height} rx=${s.rx ?? 8} @click=${click}><title>${b.name}</title></rect>`;
    return svg`<g>${el}</g>`;
  }

  _renderActionEditor(buttons) {
    const e = this._edit;
    const button = buttons.find((b) => b.id === e.selButton) || buttons[0];
    if (!button) return html`<div class="card empty">Keine Tasten definiert.</div>`;
    const action = button.actions.find((a) => a.id === e.selAction) || button.actions[0];
    if (!action) return html`<div class="card empty">Diese Taste hat keine Aktionen.</div>`;
    const key = actionKey(button.id, action.id);
    const cfg = e.config.actions[key] || { mode: "single", sequence: [], enabled: true };
    const setCfg = (patch) =>
      this._patchConfig({ actions: { ...e.config.actions, [key]: { ...cfg, ...patch } } });
    const seq = Array.isArray(cfg.sequence) ? cfg.sequence : cfg.sequence ? [cfg.sequence] : [];

    return html`
      <div class="card">
        <div class="btnhead">
          <h2>${button.name}</h2>
          ${buttons.length > 1
            ? html`<select @change=${(ev) => this._select(ev.target.value)} .value=${button.id}>
                ${buttons.map((b) => html`<option value=${b.id} ?selected=${b.id === button.id}>${b.name}</option>`)}
              </select>`
            : nothing}
        </div>
        <div class="tabs">
          ${button.actions.map((a) => {
            const has = (e.config.actions[actionKey(button.id, a.id)]?.sequence || []).length;
            return html`<button class="tab ${a.id === action.id ? "on" : ""} ${a.virtual ? "virtual" : ""}"
              title=${a.virtual ? "Virtueller Mehrfachdruck – von Switchboard gezählt" : ""}
              @click=${() => this._select(button.id, a.id)}>${a.name}${has ? html` <span class="badge">●</span>` : nothing}</button>`;
          })}
        </div>
        <div class="opts">
          <label class="field inline"><span>Modus</span>
            <select @change=${(ev) => setCfg({ mode: ev.target.value })}>
              ${MODES.map(([v, n]) => html`<option value=${v} ?selected=${(cfg.mode || "single") === v}>${n}</option>`)}
            </select>
          </label>
          ${["queued", "parallel"].includes(cfg.mode)
            ? html`<label class="field inline"><span>Max.</span>
                <input type="number" min="1" max="100" .value=${String(cfg.max ?? 10)}
                  @input=${(ev) => setCfg({ max: Number(ev.target.value) })} /></label>`
            : nothing}
          <label class="check"><input type="checkbox" .checked=${cfg.enabled !== false}
            @change=${(ev) => setCfg({ enabled: ev.target.checked })} /> aktiv</label>
          <div class="grow"></div>
          ${this._caps.actionEditor
            ? html`<button class="link" @click=${() => this._patch({ yamlMode: !e.yamlMode }, false)}>
                ${e.yamlMode ? "Visueller Editor" : "YAML"}</button>`
            : nothing}
        </div>
        ${action.virtual
          ? html`<div class="hint">Wird ausgelöst, wenn „${button.actions.find((a) => a.id === button.virtual_multi_press?.action)?.name || "Drücken"}“
              ${action.presses}× innerhalb des Mehrfachdruck-Fensters kommt. Solange hier etwas hinterlegt ist,
              wartet der Einfachdruck das Fenster ab.</div>`
          : nothing}
        ${e.yamlMode || !this._caps.actionEditor ? this._renderYaml(key, seq, setCfg) : html`
          <ha-automation-action .hass=${this.hass} .narrow=${this.narrow} .actions=${seq}
            @value-changed=${(ev) => { ev.stopPropagation(); setCfg({ sequence: ev.detail.value }); }}>
          </ha-automation-action>`}
        <div class="muted small vars">Variablen in Templates:
          <code>{{ button }}</code> <code>{{ action }}</code> <code>{{ presses }}</code>
          <code>{{ switch_name }}</code> <code>{{ data }}</code> (Rohdaten des Ereignisses)</div>
      </div>
    `;
  }

  _renderYaml(key, seq, setCfg) {
    const e = this._edit;
    const text = e.yaml[key]?.text ?? (seq.length ? yaml.dump(seq, { lineWidth: 120 }) : "");
    const error = e.yaml[key]?.error;
    return html`
      <textarea class="yaml" spellcheck="false" .value=${text}
        placeholder="- action: light.toggle&#10;  target:&#10;    entity_id: light.flur"
        @input=${(ev) => {
          const t = ev.target.value;
          let parsed;
          let err;
          try {
            parsed = t.trim() ? yaml.load(t) : [];
            if (parsed && !Array.isArray(parsed)) parsed = [parsed];
          } catch (ex) {
            err = ex.message;
          }
          this._patch({ yaml: { ...e.yaml, [key]: { text: t, error: err } } }, false);
          if (!err) setCfg({ sequence: parsed });
        }}></textarea>
      ${error ? html`<div class="err">${error}</div>` : nothing}
    `;
  }

  // ------------------------------------------------------------------ Live/Lernmodus
  _renderLive() {
    const e = this._edit;
    return html`<div class="card live">
      <div class="livehead">
        <strong>Live-Ereignisse</strong>
        <div class="grow"></div>
        ${e.log.length ? html`<button class="link" @click=${() => this._patch({ log: [] }, false)}>leeren</button>` : nothing}
        <button class=${e.listening ? "secondary on" : "secondary"} @click=${this._toggleListen}>
          ${e.listening ? "■ Stopp" : "● Zuhören"}</button>
      </div>
      ${e.listening && !e.log.length ? html`<div class="muted small">Jetzt eine Taste am Gerät drücken …</div>` : nothing}
      ${e.log.map(
        (l) => html`<div class="logline ${l.matches.length ? "hit" : ""}">
          <div><span class="muted">${l.time}</span>
            ${l.matches.length
              ? l.matches.map((m) => html` <span class="chip on">${this._label(m)}</span>`)
              : html` <span class="chip">kein Treffer</span>`}</div>
          <code>${JSON.stringify(l.message)}</code>
        </div>`
      )}
    </div>`;
  }

  _label(m) {
    const b = this._buttons().find((x) => x.id === m.button);
    const a = b?.actions.find((x) => x.id === m.action);
    return `${b?.name || m.button} · ${a?.name || m.action}`;
  }

  async _toggleListen() {
    if (this._edit.listening) {
      this._stopListen();
      return;
    }
    const e = this._edit;
    try {
      this._unsub = await ws.listen(this.hass, e.config.definition, e.config.inputs, e.config.buttons, (ev) => {
        if (!this._edit) return;
        const entry = { time: new Date().toLocaleTimeString(), ...ev };
        const patch = { log: [entry, ...this._edit.log].slice(0, 25) };
        if (ev.matches.length) {
          patch.flash = ev.matches[0].button;
          clearTimeout(this._flashTimer);
          this._flashTimer = setTimeout(() => this._edit && this._patch({ flash: undefined }, false), 900);
        }
        this._patch(patch, false);
      });
      this._patch({ listening: true }, false);
    } catch (err) {
      this._notify(`Zuhören nicht möglich: ${err.message || err}`);
    }
  }

  _stopListen() {
    if (this._unsub) {
      try {
        this._unsub();
      } catch (_) {
        /* bereits beendet */
      }
      this._unsub = undefined;
    }
    if (this._edit?.listening) this._patch({ listening: false }, false);
  }

  // ------------------------------------------------------------------ Aktionen
  async _discover() {
    const e = this._edit;
    this._busy = true;
    try {
      const buttons = await ws.discover(this.hass, e.config.definition, e.config.inputs);
      this._patch({ config: { ...e.config, buttons }, needsDiscover: false });
      this._select(buttons[0]?.id);
      this._notify(`${buttons.length} Taste(n) erkannt`);
    } catch (err) {
      this._notify(err.message || String(err));
    } finally {
      this._busy = false;
    }
  }

  async _save() {
    const e = this._edit;
    if (Object.values(e.yaml).some((y) => y.error)) {
      this._notify("Bitte erst die YAML-Fehler beheben.");
      return;
    }
    // leere Aktionen nicht speichern
    const actions = {};
    for (const [k, v] of Object.entries(e.config.actions)) {
      if ((Array.isArray(v.sequence) ? v.sequence : [v.sequence]).filter(Boolean).length) actions[k] = v;
    }
    this._busy = true;
    try {
      const saved = await ws.save(this.hass, { ...e.config, actions });
      this._switches = await ws.list(this.hass);
      this._edit = {
        ...e,
        config: { ...e.config, id: saved.id, actions, buttons: saved.buttons },
        isNew: false,
        dirty: false,
        error: saved.error,
      };
      this._notify(saved.error ? `Gespeichert, aber: ${saved.error}` : "Gespeichert");
    } catch (err) {
      this._notify(err.message || String(err));
    } finally {
      this._busy = false;
    }
  }

  async _delete() {
    if (!confirm(`Schalter „${this._edit.config.name}“ wirklich löschen?`)) return;
    try {
      await ws.remove(this.hass, this._edit.config.id);
      this._stopListen();
      this._edit = undefined;
      this._view = "list";
      await this._load();
    } catch (err) {
      this._notify(err.message || String(err));
    }
  }

  // ------------------------------------------------------------------ Info
  _renderInfo() {
    const i = this._info;
    return html`
      <div class="card">
        <div class="livehead">
          <h2>Erweiterungen</h2>
          <div class="grow"></div>
          <button class="secondary" ?disabled=${this._busy} @click=${this._reload}>Neu laden</button>
          <button class="secondary" ?disabled=${this._busy} @click=${this._import}>Aus Switch Manager importieren</button>
        </div>
        <p class="muted small">Eigene Definitionen (YAML) nach <code>${i.user_dir}/definitions/</code>,
          eigene Plugins (Python) nach <code>${i.user_dir}/plugins/</code> legen und „Neu laden“ klicken.
          Version ${i.version}.</p>
      </div>
      ${i.errors.length
        ? html`<div class="card"><h3>Ladefehler</h3>
            ${i.errors.map((e) => html`<div class="err"><code>${e.source}</code>: ${e.error}</div>`)}</div>`
        : nothing}
      <div class="card"><h3>Plugins (Ereignisquellen)</h3>
        <table>
          <tr><th>Schlüssel</th><th>Name</th><th>Herkunft</th><th>Status</th></tr>
          ${i.plugins.map(
            (p) => html`<tr><td><code>${p.key}</code></td>
              <td>${p.name}<div class="muted small">${p.description}</div></td>
              <td>${p.origin}</td>
              <td>${p.available ? html`<span class="chip on">bereit</span>` : html`<span class="chip off">nicht verfügbar</span>`}
                ${p.supports_discovery ? html`<span class="chip">Auto-Erkennung</span>` : nothing}</td></tr>`
          )}
        </table>
      </div>
      <div class="card"><h3>Definitionen (${i.definitions.length})</h3>
        <table>
          <tr><th>Name</th><th>Hersteller / Modell</th><th>Quelle</th><th>Herkunft</th></tr>
          ${i.definitions.map(
            (d) => html`<tr><td>${d.name}</td><td>${d.manufacturer} ${d.model}</td>
              <td><code>${d.source}</code></td><td>${d.origin}</td></tr>`
          )}
        </table>
      </div>
    `;
  }

  async _reload() {
    this._busy = true;
    try {
      this._info = { ...this._info, ...(await ws.reload(this.hass)) };
      this._switches = await ws.list(this.hass);
      this._notify("Plugins und Definitionen neu geladen");
    } catch (err) {
      this._notify(err.message || String(err));
    } finally {
      this._busy = false;
    }
  }

  async _import() {
    if (!confirm("Switch-Manager-Schalter übernehmen? Sie werden deaktiviert angelegt, damit nichts doppelt auslöst.")) return;
    this._busy = true;
    try {
      const r = await ws.importSM(this.hass);
      await this._load();
      const skipped = r.skipped.length ? `, ${r.skipped.length} übersprungen` : "";
      this._notify(`${r.imported.length} von ${r.found_switches} Schalter(n) importiert${skipped}`);
      if (r.skipped.length) console.warn("Switchboard-Import übersprungen:", r.skipped);
    } catch (err) {
      this._notify(err.message || String(err));
    } finally {
      this._busy = false;
    }
  }

  static styles = css`
    :host {
      display: block;
      min-height: 100vh;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
      --sb-accent: var(--primary-color, #03a9f4);
      --sb-card: var(--card-background-color, #fff);
      --sb-border: var(--divider-color, rgba(0, 0, 0, 0.12));
      --sb-muted: var(--secondary-text-color, #727272);
      --sb-ok: var(--success-color, #43a047);
      --sb-err: var(--error-color, #db4437);
    }
    .toolbar {
      display: flex; align-items: center; gap: 8px; height: 56px; padding: 0 12px;
      background: var(--app-header-background-color, var(--primary-color));
      color: var(--app-header-text-color, #fff);
      position: sticky; top: 0; z-index: 3;
    }
    .toolbar .title { font-size: 20px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .toolbar nav { display: flex; gap: 4px; }
    .toolbar .tab { color: inherit; opacity: 0.75; border-color: transparent; background: transparent; }
    .toolbar .tab.on { opacity: 1; border-bottom: 2px solid currentColor; border-radius: 0; }
    .toolbar .icon { background: none; border: none; color: inherit; font-size: 22px; }
    .content { padding: 16px; max-width: 1280px; margin: 0 auto; padding-bottom: 96px; }
    .card {
      background: var(--sb-card); border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--sb-border);
      padding: 16px; margin-bottom: 16px;
    }
    h2 { margin: 0 0 8px; font-size: 20px; font-weight: 500; }
    h3 { margin: 0 0 12px; font-size: 16px; font-weight: 500; }
    button {
      font: inherit; cursor: pointer; border-radius: 8px; padding: 8px 14px;
      border: 1px solid var(--sb-border); background: transparent; color: inherit;
    }
    button:disabled { opacity: 0.5; cursor: default; }
    button.primary { background: var(--sb-accent); color: var(--text-primary-color, #fff); border-color: var(--sb-accent); }
    button.secondary.on { background: var(--sb-err); color: #fff; border-color: var(--sb-err); }
    button.danger { color: var(--sb-err); border-color: var(--sb-err); }
    button.link { border: none; color: var(--sb-accent); padding: 4px 6px; }
    input, select, textarea {
      font: inherit; color: inherit; background: var(--secondary-background-color, #f5f5f5);
      border: 1px solid var(--sb-border); border-radius: 8px; padding: 8px 10px; box-sizing: border-box;
    }
    .field { display: flex; flex-direction: column; gap: 4px; margin: 12px 0; }
    .field > span { font-size: 13px; color: var(--sb-muted); }
    .field.inline { flex-direction: row; align-items: center; gap: 8px; margin: 0; }
    .check { display: flex; align-items: center; gap: 6px; }
    .muted { color: var(--sb-muted); }
    .small { font-size: 12px; }
    .center { text-align: center; }
    .grow { flex: 1; }
    .err { color: var(--sb-err); font-size: 13px; margin-top: 6px; }
    .empty { text-align: center; color: var(--sb-muted); padding: 24px; }
    .banner { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; cursor: pointer; }
    .banner.warn { background: rgba(255, 152, 0, 0.15); }
    code { font-family: var(--code-font-family, monospace); font-size: 12px; }
    .list .row { display: flex; align-items: center; gap: 14px; cursor: pointer; margin-bottom: 8px; }
    .list .row:hover { border-color: var(--sb-accent); }
    .name { font-weight: 500; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--sb-muted); flex: none; }
    .dot.on { background: var(--sb-ok); } .dot.error { background: var(--sb-err); }
    .chip { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: var(--secondary-background-color, #eee); white-space: nowrap; }
    .chip.on { background: rgba(67, 160, 71, 0.18); } .chip.error, .chip.off { background: rgba(219, 68, 55, 0.14); }
    .switch { position: relative; width: 40px; height: 22px; flex: none; }
    .switch input { opacity: 0; width: 0; height: 0; }
    .switch span { position: absolute; inset: 0; background: var(--sb-border); border-radius: 11px; transition: 0.2s; }
    .switch span::before { content: ""; position: absolute; width: 16px; height: 16px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: 0.2s; }
    .switch input:checked + span { background: var(--sb-accent); }
    .switch input:checked + span::before { transform: translateX(18px); }
    .fab {
      position: fixed; right: 24px; bottom: 24px; background: var(--sb-accent); color: var(--text-primary-color, #fff);
      border: none; border-radius: 16px; padding: 14px 20px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25); z-index: 2;
    }
    .backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45); z-index: 10; display: flex; align-items: center; justify-content: center; }
    .dialog { background: var(--sb-card); border-radius: 16px; padding: 20px; width: min(640px, 94vw); max-height: 86vh; display: flex; flex-direction: column; }
    .search { width: 100%; margin: 8px 0 12px; }
    .picklist { overflow: auto; flex: 1; }
    .group { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--sb-muted); margin: 12px 4px 6px; }
    .pick { display: flex; gap: 12px; align-items: center; width: 100%; text-align: left; margin-bottom: 6px; }
    .pick img, .noimg { width: 40px; height: 40px; object-fit: contain; flex: none; }
    .noimg { display: flex; align-items: center; justify-content: center; color: var(--sb-muted); font-size: 22px; }
    .dialog .actions { display: flex; justify-content: flex-end; margin-top: 12px; }
    .editor { display: grid; grid-template-columns: minmax(280px, 360px) 1fr; gap: 16px; align-items: start; }
    .editor.narrow { grid-template-columns: 1fr; }
    .device svg { width: 100%; max-height: 380px; display: block; }
    .shape { fill: transparent; stroke: transparent; stroke-width: 3; cursor: pointer; transition: fill 0.15s; }
    .shape:hover { fill: rgba(3, 169, 244, 0.12); }
    .shape.has { stroke: var(--sb-accent); stroke-dasharray: 4 3; }
    .shape.sel { fill: rgba(3, 169, 244, 0.22); stroke: var(--sb-accent); stroke-dasharray: none; }
    .shape.flash { fill: rgba(67, 160, 71, 0.55); }
    .buttons { display: flex; flex-wrap: wrap; gap: 8px; }
    .btnchip.sel { border-color: var(--sb-accent); background: rgba(3, 169, 244, 0.12); }
    .btnchip.flash { background: rgba(67, 160, 71, 0.4); }
    .badge { font-size: 11px; margin-left: 6px; color: var(--sb-accent); }
    .btnhead { display: flex; align-items: center; gap: 12px; justify-content: space-between; }
    .tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 12px; }
    .tabs .tab.on { background: var(--sb-accent); color: var(--text-primary-color, #fff); border-color: var(--sb-accent); }
    .tabs .tab.virtual { border-style: dashed; }
    .opts { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 12px; }
    .hint { font-size: 13px; background: rgba(3, 169, 244, 0.08); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; }
    textarea.yaml { width: 100%; min-height: 260px; font-family: var(--code-font-family, monospace); font-size: 13px; }
    .vars { margin-top: 12px; }
    .vars code { background: var(--secondary-background-color); padding: 1px 4px; border-radius: 4px; }
    .livehead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .logline { border-top: 1px solid var(--sb-border); padding: 6px 0; font-size: 12px; }
    .logline code { display: block; word-break: break-all; color: var(--sb-muted); margin-top: 2px; }
    .logline.hit code { color: inherit; }
    .savebar {
      position: sticky; bottom: 0; display: flex; gap: 8px; padding: 12px 16px; background: var(--sb-card);
      border-top: 1px solid var(--sb-border); z-index: 2;
    }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th { text-align: left; color: var(--sb-muted); font-weight: 500; font-size: 12px; }
    td, th { padding: 8px 6px; border-bottom: 1px solid var(--sb-border); vertical-align: top; }
    .toast {
      position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); background: #323232; color: #fff;
      padding: 12px 18px; border-radius: 8px; z-index: 20; max-width: 90vw;
    }
    @media (max-width: 600px) {
      .toolbar nav .tab { padding: 6px 8px; font-size: 13px; }
      .content { padding: 8px; }
    }
  `;
}

/** Ergänzt bei dynamischen Tasten die virtuellen Mehrfachdruck-Aktionen (wie im Backend). */
function withVirtual(b) {
  const actions = (b.actions || []).map((a) => ({ ...a, name: a.name || a.id }));
  const vmp = b.virtual_multi_press;
  if (vmp) {
    const base = actions.find((a) => a.id === vmp.action);
    if (base)
      for (let n = 2; n <= (vmp.max_presses || 3); n++)
        actions.push({ id: `${base.id}_${n}x`, name: `${base.name} (${n}×)`, virtual: true, presses: n });
  }
  return { ...b, name: b.name || b.id, actions };
}

if (!customElements.get("switchboard-panel")) customElements.define("switchboard-panel", SwitchboardPanel);
