'use strict';

const $ = id => document.getElementById(id);
const formats = {
  swiss: {source: 'Swiss Dwellings', format: 'PDF / DXF', reader: '/'},
  ifc: {source: 'IFC models', format: 'IFC', reader: '/model.html'},
  scan: {source: 'CubiCasa5K', format: 'PNG', reader: '/scan-drawing.html'}
};
const pageSize = 20;
let currentOffset = 0, requestId = 0, controller, debounce;

function textNode(tag, value, className) {
  const el = document.createElement(tag);
  el.textContent = value;
  if (className) el.className = className;
  return el;
}
function drawingTitle(drawing, name) {
  const stem = name.replace(/\.(pdf|ifc|png)$/i, '');
  if (drawing.title && drawing.title !== stem && drawing.title !== name) return drawing.title;
  if (drawing.kind === 'swiss') {
    const match = stem.match(/^site(\d+)_bldg(\d+)_floor(\d+)$/i);
    if (match) return 'Site ' + match[1] + ' · Building ' + match[2];
  }
  if (drawing.kind === 'scan') {
    const match = stem.match(/^([a-z_]+)-(\d+)$/i);
    if (match) return 'Scan ' + match[2] + ' · ' + match[1].replaceAll('_', ' ');
  }
  const words = stem.replace(/[_-]+/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
function drawingRow(drawing) {
  const format = formats[drawing.kind];
  if (!format || !drawing.path) return null;
  const item = document.createElement('li');
  const link = document.createElement('a');
  link.href = format.reader + '?' + new URLSearchParams({path: drawing.path});
  const description = document.createElement('div');
  const name = drawing.name || drawing.path.split('/').pop();
  const title = drawingTitle(drawing, name);
  description.append(textNode('strong', title));
  if (title !== name) description.append(textNode('span', name, 'source-filename'));
  link.append(description, textNode('span', format.source, 'source-name'), textNode('span', format.format, 'format'));
  const arrow = textNode('span', '↗', 'open-arrow');
  arrow.setAttribute('aria-hidden', 'true');
  link.append(arrow);
  item.append(link);
  return item;
}
function invalidate() {
  clearTimeout(debounce);
  controller?.abort();
  requestId++;
  $('library-count').textContent = '';
  $('library-list').replaceChildren();
  $('library-pages').hidden = true;
  $('library-retry').hidden = true;
  $('library-state').textContent = 'Loading drawings…';
  $('library-state').hidden = false;
}
function setAddress(query, source, offset) {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries({q: query, source, offset: offset || ''})) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  history.replaceState(null, '', url);
}
async function search(offset = 0) {
  invalidate();
  currentOffset = offset;
  const ticket = requestId;
  controller = new AbortController();
  const query = $('library-query').value.trim(), source = $('library-source').value;
  setAddress(query, source, offset);
  const params = new URLSearchParams({q: query, source, offset: String(offset), limit: String(pageSize)});
  try {
    const response = await fetch('/api/drawings?' + params, {signal: controller.signal});
    const data = await response.json();
    if (ticket !== requestId) return;
    if (!response.ok || data.available === false) throw Error(data.message || 'Drawing library unavailable.');
    if (!Array.isArray(data.drawings) || !Number.isInteger(data.total)) throw Error('Invalid drawing library response.');
    if (offset && !data.drawings.length && data.total > 0) { search(0); return; }
    const rows = data.drawings.map(drawingRow).filter(Boolean);
    $('library-list').replaceChildren(...rows);
    $('library-state').hidden = rows.length > 0;
    if (!rows.length) $('library-state').textContent = 'No drawings match this search. Try a different filename or source.';
    $('library-count').textContent = data.total.toLocaleString() + (data.total === 1 ? ' drawing' : ' drawings');
    $('range').textContent = `${offset + 1}–${offset + rows.length} of ${data.total.toLocaleString()}`;
    $('prev').disabled = offset === 0;
    $('next').disabled = offset + rows.length >= data.total;
    $('library-pages').hidden = data.total <= pageSize || !rows.length;
  } catch (error) {
    if (ticket !== requestId || error.name === 'AbortError') return;
    $('library-state').textContent = error.message === 'Failed to fetch' || error instanceof SyntaxError
      ? 'Could not reach the drawing library. Check the local server and try again.' : error.message;
    $('library-retry').hidden = false;
  }
}
function fromAddress() {
  const params = new URLSearchParams(window.location.search);
  $('library-query').value = params.get('q') || '';
  $('library-source').value = params.get('source') || '';
  const offset = Number(params.get('offset'));
  search(Number.isSafeInteger(offset) && offset >= 0 ? offset : 0);
}
$('library-search').addEventListener('submit', event => { event.preventDefault(); search(); });
$('library-query').addEventListener('input', () => { invalidate(); debounce = setTimeout(() => search(), 250); });
$('library-source').addEventListener('change', () => search());
$('prev').addEventListener('click', () => search(Math.max(0, currentOffset - pageSize)));
$('next').addEventListener('click', () => search(currentOffset + pageSize));
$('library-retry').addEventListener('click', () => search(currentOffset));
window.addEventListener('popstate', fromAddress);
fromAddress();
