'use strict';

const node = id => document.getElementById(id);
const scanPath = new URLSearchParams(window.location.search).get('path');
let info, reports = [], selectedReport = -1, selectionRevision = 0, running = false, openRequest = 0;

function message(text, retry = false) {
  node('scan-status').textContent = text;
  node('scan-status').hidden = !text;
  node('retry-scan').hidden = !retry;
}
function normalize(question) { return question.trim().replace(/\s+/g, ' ').toLowerCase(); }
function boxOK(item) {
  const b = item?.box;
  return Array.isArray(b) && b.length === 4 && b.every(Number.isFinite)
    && b[0] >= 0 && b[1] >= 0 && b[2] <= 1000 && b[3] <= 1000 && b[2] > b[0] && b[3] > b[1];
}
function listOptions() {
  const picker = node('saved-questions');
  picker.replaceChildren();
  reports.forEach((r,i) => picker.add(new Option(r.question, String(i))));
  if (!reports.length) picker.add(new Option('No saved questions', ''));
  picker.disabled = !reports.length;
  if (selectedReport >= 0) picker.value = String(selectedReport);
}
function syncAction() {
  const query = node('scan-question').value.trim();
  const saved = reports.some(r => normalize(r.question) === normalize(query));
  node('scan-submit').disabled = !info || running || !query || (!info.configured && !saved);
  node('scan-submit').textContent = running ? 'Counting…' : saved ? 'Show saved answer' : 'Run hosted count';
}
function selectBox(index, fromList = false) {
  const pins = node('scan-overlay').children, buttons = node('scan-evidence').children;
  Array.from(pins).forEach((pin, i) => pin.setAttribute('aria-pressed', String(index === i)));
  Array.from(buttons).forEach((button, i) => button.setAttribute('aria-pressed', String(index === i)));
  node('scan-selection').textContent = buttons[index] ? 'Selected ' + buttons[index].textContent : '';
  if (fromList && node('scan-viewport').classList.contains('native')) pins[index]?.scrollIntoView({block:'nearest',inline:'nearest'});
}
function drawBoxes(items) {
  items.forEach((item, i) => {
    const label = item.label || 'Drawing mark';
    const [l,t,r,b] = item.box;
    const pin = document.createElement('button'); pin.type = 'button'; pin.className = 'scan-pin';
    pin.style.left = `${l/10}%`; pin.style.top = `${t/10}%`;
    pin.style.width = `${(r-l)/10}%`; pin.style.height = `${(b-t)/10}%`;
    pin.setAttribute('aria-label', `Evidence ${i+1}: ${label}`); pin.setAttribute('aria-pressed','false');
    pin.addEventListener('click', () => selectBox(i)); node('scan-overlay').append(pin);
    const button = document.createElement('button'); button.type = 'button'; button.className = 'evidence-row';
    button.setAttribute('aria-pressed','false'); button.textContent = `${i+1}. ${label}`;
    button.addEventListener('click', () => selectBox(i, true)); node('scan-evidence').append(button);
  });
  if (items.length) selectBox(0);
}
function clearScanEvidence() {
  node('scan-overlay').replaceChildren(); node('scan-evidence').replaceChildren();
  node('scan-selection').textContent = ''; node('scan-evidence-count').textContent = '';
  node('scan-provenance').hidden = true; node('scan-provenance').textContent = '';
}
function showReport(index) {
  ++selectionRevision; selectedReport = index;
  const report = reports[index];
  clearScanEvidence();
  if (!report) {
    node('answer-question').textContent = 'Count'; node('scan-answer').textContent = '—';
    node('answer-reason').textContent = 'No saved count for this scan.';
    syncAction(); return;
  }
  node('saved-questions').value = String(index); node('scan-question').value = report.question;
  node('answer-question').textContent = report.question;
  const items = Array.isArray(report.evidence) ? report.evidence : [];
  const matchesImage = typeof info.imageSha256 === 'string' && report.image_sha256 === info.imageSha256;
  const valid = matchesImage && report.status === 'answered' && Number.isSafeInteger(report.answer) && report.answer >= 0
    && items.length === report.answer && items.every(boxOK);
  if (valid) {
    node('scan-answer').textContent = String(report.answer);
    node('answer-reason').textContent = report.answer === 0 ? 'The model returned a count of zero.' : (report.reason || 'Select an evidence mark to locate it on the original scan.');
    node('scan-evidence-count').textContent = `${items.length} ${items.length === 1 ? 'mark' : 'marks'}`;
    drawBoxes(items);
  } else {
    node('scan-answer').textContent = report.status === 'unavailable' ? 'Unavailable' : 'Unknown';
    node('answer-reason').textContent = !matchesImage ? 'The saved report could not be matched to this original image.' : report.reason || (report.status === 'unavailable' ? 'The inference service could not return a result.' : 'The evidence was insufficient to verify a count.');
  }
  const origin = typeof report.origin === 'string' ? report.origin.replaceAll('_',' ') : '';
  const meta = [origin, report.served_model || report.model, report.provider_host].filter(Boolean);
  node('scan-provenance').hidden = !meta.length; node('scan-provenance').textContent = meta.join(' · ');
  syncAction();
}
async function request(url, options) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw Error('The local scan service could not return a result.'); }
  if (!response.ok) throw Error(data.message || 'The local scan service could not return a result.');
  return data;
}
async function loadScan() {
  const ticket = ++openRequest;
  if (!scanPath) { message('Choose a CubiCasa5K drawing in the library.'); return; }
  message('Opening scan…');
  try {
    const result = await request('/api/scan-drawing?' + new URLSearchParams({path:scanPath}));
    if (ticket !== openRequest) return;
    if (result.drawing?.path !== scanPath || result.drawing?.kind !== 'scan') throw Error('Choose a CubiCasa5K PNG from the drawing library.');
    info = result;
    reports = (Array.isArray(result.saved) ? result.saved : []).filter(r => r && typeof r.question === 'string' && r.question.trim());
    node('scan-filename').textContent = info.drawing.name;
    document.title = `${info.drawing.name} · Planproof`;
    const file = '/api/drawing-file?' + new URLSearchParams({path:scanPath});
    node('original-scan').href = file; node('original-scan').hidden = false;
    node('scan-workspace').hidden = false; node('scan-image').src = file;
    node('scan-question').disabled = false;
    node('scan-service').hidden = false;
    node('scan-service').textContent = info.configured ? 'New counts use the configured vision model. A run can take about 90 seconds.' : 'Hosted inference is unconfigured. Saved questions can be inspected offline.';
    listOptions(); showReport(reports.length ? 0 : -1); message('');
  } catch (error) { if (ticket === openRequest) message(error.message, true); }
}
async function ask() {
  if (!info || running) return;
  const question = node('scan-question').value.trim();
  if (!question) return;
  const saved = reports.findIndex(r => normalize(r.question) === normalize(question));
  if (saved >= 0) { showReport(saved); message('Showing saved answer.'); return; }
  if (!info.configured) { message('A new question requires a configured hosted endpoint.'); return; }
  const revision = ++selectionRevision;
  selectedReport = -1; node('saved-questions').selectedIndex = -1;
  clearScanEvidence();
  node('answer-question').textContent = question; node('scan-answer').textContent = 'Pending';
  node('answer-reason').textContent = 'Waiting for the model to read this drawing.';
  running = true; syncAction(); message('Reading the original scan with the hosted model…');
  try {
    const answer = await request('/api/scan-drawing', {method:'POST',headers:{'Content-Type':'application/json','X-Planproof-Run':'1'},body:JSON.stringify({path:scanPath,question})});
    const report = answer.report || answer;
    if (typeof report.question !== 'string' || normalize(report.question) !== normalize(question) || !['answered','unknown','unavailable'].includes(report.status)) throw Error('Unexpected scan response.');
    if (!info.imageSha256 || report.image_sha256 !== info.imageSha256) throw Error('The model response could not be matched to this original image.');
    const index = reports.push(report) - 1;
    listOptions();
    if (revision === selectionRevision) showReport(index);
    else if (selectedReport < 0) { node('saved-questions').selectedIndex = -1; node('scan-answer').textContent = '—'; node('answer-reason').textContent = 'Select a saved question to inspect its result.'; }
    message(report.status === 'unavailable' ? (report.reason || 'The model was unavailable.') : answer.reused ? 'Showing saved answer.' : 'Count complete.');
  } catch (error) {
    if (selectedReport < 0) { node('scan-answer').textContent = 'Unavailable'; node('answer-reason').textContent = error.message; }
    message(error.message);
  }
  finally { running = false; syncAction(); }
}
node('scan-form').addEventListener('submit', event => {event.preventDefault(); ask();});
node('saved-questions').addEventListener('change', event => {showReport(Number(event.target.value)); if (!running) message('');});
node('scan-question').addEventListener('input', () => {selectionRevision++; syncAction();});
node('retry-scan').addEventListener('click', loadScan);
node('scan-image').addEventListener('load', () => {node('image-state').hidden = true; node('scan-size').disabled = false;});
node('scan-image').addEventListener('error', () => {node('image-state').textContent = 'The original image could not be loaded. Open the PNG to inspect the source file.'; node('image-state').hidden = false; node('scan-size').disabled = true; node('scan-overlay').hidden = true;});
node('scan-size').addEventListener('click', () => {
  const native = node('scan-viewport').classList.toggle('native');
  node('scan-size').setAttribute('aria-pressed', String(native)); node('scan-size').textContent = native ? 'Fit to view' : 'Actual size';
});
loadScan();
