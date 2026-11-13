'use strict';

const el = id => document.getElementById(id);
const libraryQuery = new URLSearchParams(window.location.search);
const path = libraryQuery.get('path');
const chunk = 30;
let currentRequest = 0, pending, activeQuestion, model, quantityUnit, records = [], shown = 0, selected = -1;

function make(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function stepId(value) {
  if (value === undefined || value === null || value === '') return '';
  return String(value).startsWith('#') ? String(value) : '#' + value;
}
function status(text, retry = false) {
  el('model-status').textContent = text;
  el('model-status').hidden = !text;
  el('model-retry').hidden = !retry;
}
function clearResult() {
  records = []; shown = 0; selected = -1;
  el('model-result').hidden = true;
  el('model-evidence').replaceChildren(); el('model-record').replaceChildren();
  el('more-evidence').hidden = true;
}
function beginRequest() {
  pending?.abort();
  pending = new AbortController();
  clearResult();
  return ++currentRequest;
}
async function json(url, options) {
  const response = await fetch(url, {...options, signal: pending.signal});
  let result;
  try { result = await response.json(); }
  catch { throw Error('The local server could not read this model.'); }
  if (!response.ok) throw Error(result.message || 'The local server could not read this model.');
  return result;
}
function detail(label, value, table) {
  if (value === undefined || value === null || value === '') return;
  table.append(make('dt', label), make('dd', String(value)));
}
function excerpt(title, value, parent) {
  if (!value) return;
  parent.append(make('h3', title, 'excerpt-title'), make('pre', value, 'step-source'));
}
function showAttribution(attribution) {
  if (!attribution) return;
  el('model-attribution').hidden = false;
  el('model-work').textContent = attribution.work || '';
  el('model-license').textContent = attribution.license ? ' · ' + attribution.license : '';
  el('model-credit').textContent = attribution.credit || '';
  if (!attribution.sourceUrl) return;
  try {
    const url = new URL(attribution.sourceUrl);
    if (['https:', 'http:'].includes(url.protocol) && url.hostname && !url.username && !url.password) {
      el('model-source').href = url.href;
      el('model-source').hidden = false;
    }
  } catch { /* A malformed source link does not invalidate the printed credit. */ }
}
function showRecord(index, focus = false) {
  if (!records[index]) return;
  const old = el('model-evidence').querySelector('[aria-pressed="true"]');
  old?.setAttribute('aria-pressed','false');
  selected = index;
  const active = el('model-evidence').querySelector(`[data-index="${index}"]`);
  active?.setAttribute('aria-pressed','true');
  if (focus) active?.focus({preventScroll:true});
  const row = records[index];
  const source = el('model-record'); source.replaceChildren();
  el('record-ref').textContent = stepId(row.step_id);
  source.append(make('h3', row.name || row.ifc_type || 'Model element', 'record-name'));
  const list = make('dl', undefined, 'record-fields');
  detail('STEP ID', stepId(row.step_id), list); detail('Entity type', row.ifc_type, list);
  detail('Global ID', row.global_id, list); detail('Storey', row.storey, list);
  detail('Storey ID', stepId(row.storey_id), list); detail('Type ID', stepId(row.type_id), list);
  detail('Quantity ID', stepId(row.quantity_id), list);
  detail('Property set', stepId(row.property_set_id), list); detail('Unit ID', stepId(row.unit_id), list);
  if (row.value !== undefined && row.value !== null) detail('Contribution', String(row.value) + (quantityUnit === 'm2' ? ' m²' : ''), list);
  detail('Relations', row.relation_ids?.map(stepId).join(', '), list);
  detail('Geometry', row.geometry_ids?.map(stepId).join(', '), list);
  source.append(list);
  excerpt('STEP declaration', row.source_line, source);
  excerpt('Quantity declaration', row.quantity_source_line, source);
  excerpt('Geometry declaration', row.geometry_source_line, source);
  if (row.ifc_type === 'IFCSPACE' && row.storey) {
    const actions = make('div', undefined, 'starter-queries');
    const add = (label, query) => {
      const button = make('button', label); button.type = 'button';
      button.addEventListener('click', () => ask(query)); actions.append(button);
    };
    if (row.name) add('Measure this space', `What is the net floor area of the room '${row.name}' on '${row.storey}', in m²?`);
    add('Measure all spaces on this storey', `What is the total net floor area of all rooms (spaces) on '${row.storey}', in m²?`);
    source.append(actions);
  }
}
function appendRecords() {
  const start = shown;
  shown = Math.min(records.length, shown + chunk);
  const list = el('model-evidence');
  for (let i = start; i < shown; i++) {
    const record = records[i];
    const button = make('button', undefined, 'evidence-row');
    button.type = 'button'; button.dataset.index = String(i); button.setAttribute('aria-pressed', String(selected === i));
    button.append(make('span', stepId(record.step_id) || String(i + 1), 'record-chip'), make('span', record.name || record.ifc_type || 'Model element', 'record-label'));
    list.append(button);
  }
  el('more-evidence').hidden = shown >= records.length;
  el('more-evidence').textContent = `Show ${Math.min(chunk, records.length - shown)} more records`;
  if (start) list.querySelector(`[data-index="${start}"]`)?.focus();
}
function renderResult(result, question) {
  quantityUnit = result.unit;
  el('model-result').hidden = false;
  el('model-question').textContent = question;
  const value = el('model-value'); value.replaceChildren();
  value.append(document.createTextNode(new Intl.NumberFormat('en-GB', {maximumFractionDigits:2}).format(result.answer)));
  if (result.unit && result.unit !== 'count') value.append(make('small', result.unit === 'm2' ? ' m²' : ' '+result.unit));
  el('model-method').textContent = result.method || '';
  records = Array.isArray(result.evidence) ? result.evidence : [];
  el('model-count').textContent = records.length + (records.length === 1 ? ' record' : ' records');
  if (records.length) { appendRecords(); showRecord(0); }
  else {
    el('record-ref').textContent = '';
    el('model-record').textContent = result.answer === 0 ? 'No matching model elements.' : 'No itemized model records were returned.';
  }
}
async function ask(question) {
  question = question.trim();
  if (!model || !question) return;
  activeQuestion = question; el('model-query').value = question;
  const ticket = beginRequest();
  status('Reading model quantities…');
  try {
    const data = await json('/api/drawing-answer', {method:'POST', headers:{'Content-Type':'application/json','X-Planproof-Run':'1'}, body:JSON.stringify({path,question})});
    if (ticket !== currentRequest) return;
    if (data.drawing?.path !== path || !data.result) throw Error('Unexpected model response.');
    const result = data.result;
    if (result.status !== 'answered' || !Number.isFinite(result.answer)) {
      status(result.reason || 'This quantity could not be resolved from the model.');
      return;
    }
    status(''); renderResult(result, question);
  } catch (err) {
    if (ticket === currentRequest && err.name !== 'AbortError') status(err.message, true);
  }
}
async function openModel() {
  if (!path) { status('Choose an IFC model from the drawing library.'); return; }
  const ticket = beginRequest(); status('Opening model…');
  try {
    const data = await json('/api/drawing?' + new URLSearchParams({path}));
    if (ticket !== currentRequest) return;
    const drawing = data.drawing;
    if (drawing?.path !== path || drawing.kind !== 'ifc') throw Error('Select an IFC model from the drawing library.');
    model = drawing;
    showAttribution(drawing.attribution);
    el('model-title').textContent = drawing.title || drawing.name;
    document.title = `${drawing.title || drawing.name} · Planproof`;
    if (drawing.name && drawing.name !== drawing.title) {
      el('model-filename').hidden = false; el('model-filename').textContent = drawing.name;
    }
    el('original-model').href = '/api/drawing-file?' + new URLSearchParams({path});
    el('original-model').hidden = false; el('starters').hidden = false;
    el('model-query').disabled = false; el('model-submit').disabled = false;
    status('');
    if (libraryQuery.get('q')) ask(libraryQuery.get('q'));
  } catch (err) {
    if (ticket === currentRequest && err.name !== 'AbortError') status(err.message, true);
  }
}
el('model-form').addEventListener('submit', event => {event.preventDefault(); ask(el('model-query').value);});
el('starters').addEventListener('click', event => {const button = event.target.closest('[data-query]'); if (button) ask(button.dataset.query);});
el('model-evidence').addEventListener('click', event => {const button = event.target.closest('[data-index]'); if (button) showRecord(Number(button.dataset.index));});
el('more-evidence').addEventListener('click', appendRecords);
el('model-retry').addEventListener('click', () => model && activeQuestion ? ask(activeQuestion) : openModel());
openModel();
