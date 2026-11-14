// Capture demo frames from the running Planproof server with a headless Chromium browser.
// usage: node demo/capture.mjs demo/storyboard.json demo/out/frames [--browser PATH] [--base http://127.0.0.1:4179]
// The storyboard lists shots: {name, url, wait?, actions?: [js], settle?: ms}. No dependencies: Node 22+ only.
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const args = process.argv.slice(2);
const option = (name, fallback) => { const i = args.indexOf(name); return i < 0 ? fallback : args[i + 1]; };
const storyboard = JSON.parse(readFileSync(args[0], 'utf8'));
const outDir = args[1];
const base = option('--base', 'http://127.0.0.1:4179');
const browser = option('--browser', process.env.DEMO_BROWSER || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser');
const [width, height] = (storyboard.size || [1920, 1080]);
const port = 9300 + Math.floor(process.pid % 500);
const profile = mkdtempSync(join(tmpdir(), 'planproof-demo-'));
mkdirSync(outDir, { recursive: true });
const sleep = ms => new Promise(done => setTimeout(done, ms));

const child = spawn(browser, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  `--window-size=${width},${height}`, '--hide-scrollbars', '--no-first-run', '--disable-extensions', 'about:blank'], { stdio: 'ignore' });

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = pages.find(p => p.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* browser still starting */ }
    await sleep(250);
  }
  throw new Error('The browser did not open a debugging port.');
}

try {
  const socket = new WebSocket(await target());
  await new Promise((done, fail) => { socket.onopen = done; socket.onerror = fail; });
  let next = 0;
  const waiting = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id && waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); }
  };
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++next;
    waiting.set(id, message => message.error ? fail(new Error(method + ': ' + message.error.message)) : done(message.result));
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text + ' in ' + expression.slice(0, 80));
    return result.result.value;
  };
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  for (const shot of storyboard.shots) {
    if (shot.url) {
      await send('Page.navigate', { url: /^(https?|file):/.test(shot.url) ? shot.url : base + shot.url });
      let ready = false;
      for (let i = 0; i < 120 && !ready; i++) {
        ready = await evaluate(`document.readyState === 'complete' && (${shot.wait || 'true'})`).catch(() => false);
        if (!ready) await sleep(250);
      }
      if (!ready) throw new Error(`Shot ${shot.name} never became ready: ${shot.wait}`);
      if (storyboard.css) await evaluate(`(() => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(storyboard.css)}; document.head.append(s); })()`);
    }
    for (const action of shot.actions || []) { await evaluate(action); await sleep(300); }
    await sleep(shot.settle ?? 600);
    const image = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(outDir, shot.name + '.png'), Buffer.from(image.data, 'base64'));
    console.log('captured', shot.name);
  }
  socket.close();
} finally {
  child.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
