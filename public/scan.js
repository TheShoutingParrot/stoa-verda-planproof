const reportBox = document.querySelector('#report');
const evidenceList = document.querySelector('#evidence');
const pins = document.querySelector('#pins');
const runButton = document.querySelector('#run');
const service = document.querySelector('#service');
const expectedDigest = 'f1cf7f64462f9687e41b4a5848534cc409c32212cc3c6ae02b9e315039d6f6af';
const scanName = 'high_quality_architectural-13066.png';

function textBlock(tag, content, parent) {
  const element = document.createElement(tag);
  element.textContent = content;
  parent.append(element);
}

function showReport(report, local = false) {
  reportBox.replaceChildren();
  evidenceList.replaceChildren();
  pins.querySelectorAll(':not([data-baseline])').forEach(pin => pin.remove());
  if (!report || report.image !== scanName || report.image_sha256 !== expectedDigest || report.status === 'unavailable') {
    textBlock('strong', 'No model result yet', reportBox);
    if (report?.reason) textBlock('p', report.reason, reportBox);
    return;
  }
  textBlock('strong', report.status === 'answered'
    ? report.answer + (local ? (report.answer === 1 ? ' bedroom label' : ' bedroom labels') : (report.answer === 1 ? ' bedroom' : ' bedrooms'))
    : 'Could not verify the count', reportBox);
  if (report.reason) textBlock('p', report.reason, reportBox);
  const time = report.latency_ms == null ? '' : ' · ' + (report.latency_ms / 1000).toFixed(1) + ' s';
  if (local) {
    textBlock('p', 'Nemotron Parse v1.2 read the whole scan locally' + time + '. The highlight locates the matching OCR text. Inspect it against the green apartment boundary.', reportBox);
  } else {
    textBlock('p', (report.served_model || report.model) + (report.provider_host ? ' · ' + report.provider_host : '') + time, reportBox);
  }
  if (report.status !== 'answered') return;
  for (const [index, item] of report.evidence.entries()) {
    const [x, y, right, bottom] = item.box;
    const rect = document.createElementNS('http://www.w3.org/2000/svg','rect');
    for (const [key, val] of Object.entries({x, y, width: right - x, height: bottom - y})) rect.setAttribute(key,val);
    pins.append(rect);
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = (index + 1) + '. ' + item.label;
    button.setAttribute('aria-pressed','false');
    function select() {
      for (const pin of pins.children) pin.classList.toggle('selected',pin === rect);
      for (const row of evidenceList.children) row.setAttribute('aria-pressed',String(row === button));
    }
    rect.addEventListener('click',select);
    button.addEventListener('click',select);
    evidenceList.append(button);
  }
}

async function load() {
  try {
    const response = await fetch('/api/scan', {cache:'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (data.report && data.report.status !== 'unavailable') {
      showReport(data.report);
    } else {
      const response = await fetch('/data/finnish/parse-run.json', {cache:'no-store'});
      showReport(response.ok ? await response.json() : data.report, response.ok);
    }
    runButton.hidden = !data.configured;
    service.textContent = data.configured ? '' : 'For a new Super VL image run, configure an endpoint and key on the server.';
  } catch {
    try {
      const saved = await fetch('/data/finnish/run.json', {cache:'no-store'});
      if (saved.ok) showReport(await saved.json());
      else {
        const local = await fetch('/data/finnish/parse-run.json', {cache:'no-store'});
        showReport(local.ok ? await local.json() : null, local.ok);
      }
    } catch { showReport(null); }
    service.textContent = 'Start the local server for live inference.';
  }
}

runButton.addEventListener('click', async () => {
  runButton.disabled = true;
  service.textContent = 'Reading the original scan…';
  try {
    const response = await fetch('/api/scan', {method:'POST', headers:{'Content-Type':'application/json','X-Planproof-Run':'1'}, body:'{}'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.message);
    showReport(result.report);
    service.textContent = '';
  } catch (error) { service.textContent = error.message || 'Could not contact the local server.'; }
  finally { runButton.disabled = false; }
});
load();

async function showBaseline() {
  const details = document.querySelector('#ocr');
  try {
    const response = await fetch('/data/finnish/ocr-baseline.json');
    if (!response.ok) return;
    const data = await response.json();
    if (data.imageSha256 !== expectedDigest) return;
    const run = data.runs.find(run => run.scale === 4);
    if (!run) return;
    details.hidden = false;
    document.querySelector('#ocr-info').textContent = `Tesseract found ${run.exactLabels} exact bedroom labels and ${run.candidates.length} possible matches at 4× magnification. Click a candidate to inspect the original print.`;
    for (const candidate of run.candidates) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = candidate.text + ' · ' + Math.round(candidate.ocrConfidence) + '/100 OCR confidence';
      button.setAttribute('aria-pressed', 'false');
      const [left, top, right, bottom] = candidate.box;
      const [width, height] = data.imageSize;
      const mark = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      for (const [key,val] of Object.entries({x:1000*left/width, y:1000*top/height, width:1000*(right-left)/width, height:1000*(bottom-top)/height})) mark.setAttribute(key,val);
      mark.setAttribute('data-baseline','true');
      mark.classList.add('ocr-box');
      mark.style.display = 'none';
      pins.append(mark);
      button.addEventListener('click', () => {
        const active = button.getAttribute('aria-pressed') !== 'true';
        mark.style.display = active ? '' : 'none';
        button.setAttribute('aria-pressed',String(active));
      });
      details.addEventListener('toggle', () => {
        if (!details.open) {
          mark.style.display = 'none';
          button.setAttribute('aria-pressed','false');
        }
      });
      document.querySelector('#ocr-candidates').append(button);
    }
  } catch { /* The saved OCR comparison is optional. */ }
}
showBaseline();
