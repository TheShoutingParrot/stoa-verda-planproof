// Execute the app's complete form handler and renderer without a browser/graphics dependency.
// The input contains source geometry and questions. Expected values stay in the Python scorer.
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const {performance} = require('node:perf_hooks');

class Element {
  constructor(fragment = false) {
    this.fragment = fragment;
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.listeners = {};
    this.classList = {toggle() {}};
    this.value = '';
    this.text = '';
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(item => item.textContent).join(''); }
  append(...items) { for (const item of items) this.children.push(...(item.fragment ? item.children : [item])); }
  replaceChildren(...items) { this.text = ''; this.children = []; this.append(...items); }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key]; }
  add(option) { this.append(option); }
  contains() { return false; }
}

async function runSheet(source, sheet, questions) {
  const nodes = new Map();
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new Element());
      return nodes.get(id);
    },
    createElement() { return new Element(); },
    createElementNS() { return new Element(); },
    createDocumentFragment() { return new Element(true); },
    createTextNode(value) { const node = new Element(); node.textContent = value; return node; },
    activeElement: null
  };
  const context = vm.createContext({
    document, Intl, console, URL, URLSearchParams, Option: class extends Element {},
    window: {location: new URL('https://benchmark.invalid/?sheet='+encodeURIComponent(sheet.sheet.id)),
             addEventListener() {}},
    fetch: async () => ({ok: true, json: async () => sheet})
  });
  new vm.Script(source, {filename: 'public/app.js'}).runInContext(context);
  // Register the held-out asset as a test fixture in the in-memory sheet catalog.
  // Registration routes through loadFromAddress/loadSheet; only the two bundled sheets
  // are available to people on the normal site. The old revision has no catalog.
  vm.runInContext(`if (typeof sheetFiles !== "undefined") {
    const id = new URLSearchParams(window.location.search).get("sheet");
    sheetFiles.set(id, "/benchmark/" + id + ".json");
    loadFromAddress();
  }`, context);
  await new Promise(resolve => setImmediate(resolve));
  if (!nodes.get('loading').hidden) throw Error('Failed to load sheet ' + sheet.sheet.id);
  const readState = vm.runInContext('() => ({selection:state.roomType, metric:state.metric, roomId:state.roomId ?? null})', context);
  return questions.map(question => {
    nodes.get('query').value = question;
    const start = performance.now();
    nodes.get('query-form').listeners.submit({preventDefault() {}});
    const elapsedMs = performance.now() - start;
    const message = nodes.get('query-message');
    const display = nodes.get('answer').textContent;
    const match = display.replaceAll(',', '').match(/^(-?\d+(?:\.\d+)?)(?:\s*m²)?$/);
    const evidence = nodes.get('evidence').children
      .map(node => node.dataset.roomId).filter(id => id !== undefined);
    const abstained = !message.hidden || !match;
    return {
      ...readState(), display, caption: nodes.get('answer-caption').textContent,
      title: nodes.get('answer-title').textContent, value: abstained ? null : Number(match[1]),
      evidence: abstained ? [] : evidence, elapsedMs
    };
  });
}

(async () => {
  const source = fs.readFileSync(process.argv[2], 'utf8');
  const sheets = JSON.parse(fs.readFileSync(0, 'utf8'));
  const rows = [];
  for (const {sheet, questions} of sheets) rows.push(...await runSheet(source, sheet, questions));
  process.stdout.write(JSON.stringify(rows));
})().catch(error => {console.error(error); process.exitCode = 1;});
