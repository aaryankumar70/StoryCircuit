// CurioLoop's original zero-dependency Node/Chromium/FFmpeg capture driver (Node 22+).
import { spawn, spawnSync } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REAL_ROOT = fs.realpathSync(ROOT);
const TMP_ROOT = path.resolve(process.env.CURIOLOOP_RENDER_TMP_DIR || os.tmpdir());
fs.mkdirSync(TMP_ROOT, { recursive: true });
const ownerFile = path.join(TMP_ROOT, 'owner.json'), ownTemps = new Set();
const stageOwnerFile = process.env.CURIOLOOP_STAGE_OWNER_FILE;
let chromeProcess = null;
const FPS = Math.max(1, Math.min(60, +(process.env.FPS || 30)));
const CHROME = process.env.CHROME;
const FFMPEG = process.env.CURIOLOOP_FFMPEG || 'ffmpeg';
const args = process.argv.slice(2), flags = new Set(args.filter((a) => a.startsWith('--')));
const [mode, ...rest] = args.filter((a) => !a.startsWith('--'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const ownTemp = (prefix) => { const p = fs.mkdtempSync(path.join(TMP_ROOT, `curioloop-${prefix}-`)); ownTemps.add(p); return p; };
function projectOutput(relative) {
  const out = path.resolve(ROOT, relative);
  const rel = path.relative(ROOT, out);
  if (rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) throw new Error('Capture output must stay inside its render project.');
  return out;
}
function updateOwner(file, updates) {
  if (!file) return;
  try {
    const old = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
    fs.writeFileSync(file, JSON.stringify({ ...old, ...updates }));
  } catch {}
}
function noteOwner(browserPid = null) {
  const updates = { node_pid: process.pid, browser_pid: browserPid, updated_at: Date.now() };
  updateOwner(ownerFile, updates);
  updateOwner(stageOwnerFile, updates);
}
function killBrowserTree() {
  if (!chromeProcess || chromeProcess.exitCode !== null) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/F', '/T', '/PID', String(chromeProcess.pid)], { windowsHide: true, stdio: 'ignore' });
  else try { chromeProcess.kill('SIGKILL'); } catch {}
}
function cleanTemps() {
  killBrowserTree();
  for (const p of ownTemps) try { fs.rmSync(p, { recursive: true, force: true }); } catch {}
  ownTemps.clear();
}
process.on('exit', cleanTemps);
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { cleanTemps(); process.exit(1); });
noteOwner();

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json', '.wav': 'audio/wav', '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.png': 'image/png', '.jpg': 'image/jpeg' };
function serve(port = 0) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405, { Allow: 'GET, HEAD' }); res.end(); return; }
      let relative;
      try { relative = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname).replace(/^\/+/, '') || 'index.html'; }
      catch { res.writeHead(400); res.end(); return; }
      try {
        const file = path.resolve(ROOT, relative);
        if (file.includes('\0') || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
        const realFile = fs.realpathSync(file), inside = path.relative(REAL_ROOT, realFile), stat = fs.statSync(realFile);
        if (inside === '..' || inside.startsWith(`..${path.sep}`) || path.isAbsolute(inside) || !stat.isFile()) { res.writeHead(404); res.end(); return; }
        res.writeHead(200, { 'Content-Type': MIME[path.extname(realFile)] || 'application/octet-stream', 'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; font-src 'self' data:" });
        if (req.method === 'HEAD') { res.end(); return; }
        const stream = fs.createReadStream(realFile);
        stream.on('error', () => { if (!res.headersSent) res.writeHead(500); res.end(); });
        stream.pipe(res);
      } catch { if (!res.headersSent) res.writeHead(404); res.end(); }
    });
    server.once('error', reject); server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

async function openPage(port) {
  if (!CHROME || !fs.existsSync(CHROME)) throw new Error(`Chromium/Edge executable not found: ${CHROME || '(CHROME is unset)'}`);
  const profile = ownTemp('profile');
  const childArgs = ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', '--window-size=1080,1920', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-features=Translate,BackForwardCache', '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--disable-gpu-sandbox',
    '--disable-dev-shm-usage', '--disable-crash-reporter', 'about:blank'];
  chromeProcess = spawn(CHROME, childArgs, { stdio: 'ignore', windowsHide: true });
  let launchError = null; chromeProcess.on('error', (e) => { launchError = e; }); noteOwner(chromeProcess.pid);
  let debugPort = '';
  for (let i = 0; i < 200 && !debugPort; i++) {
    if (launchError) throw new Error(`Browser launch failed: ${launchError.message}`);
    if (chromeProcess.exitCode !== null) throw new Error(`Browser exited during startup (code ${chromeProcess.exitCode}).`);
    try { debugPort = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim(); } catch { await sleep(100); }
  }
  if (!debugPort) throw new Error('Browser remote debugging did not become ready within 20 seconds.');
  const opened = await fetch(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(`http://127.0.0.1:${port}/index.html?capture=1${process.env.QS || ''}`)}`, { method: 'PUT' });
  if (!opened.ok) throw new Error(`Chromium refused a local capture tab: HTTP ${opened.status}`);
  const target = await opened.json(), ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0; const pending = new Map(), logs = [];
  ws.onmessage = (event) => {
    let message; try { message = JSON.parse(event.data); } catch { return; }
    if (message.id && pending.has(message.id)) { const p = pending.get(message.id); pending.delete(message.id); message.error ? p.reject(new Error(message.error.message)) : p.resolve(message.result); }
    else if (message.method === 'Runtime.exceptionThrown') logs.push('EXCEPTION ' + (message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text));
    else if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') logs.push('ERROR ' + message.params.args.map((a) => a.value ?? a.description).join(' '));
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => { const key = ++id; pending.set(key, { resolve, reject }); ws.send(JSON.stringify({ id: key, method, params })); });
  const evaluate = async (expression) => {
    const response = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
    return response.result.value;
  };
  await send('Runtime.enable');
  for (let i = 0; i < 1200; i++) {
    const ready = await evaluate('window.OP ? (OP.bootError ? "ERR:" + OP.bootError : OP.ready) : false').catch(() => false);
    if (ready === true) break;
    if (typeof ready === 'string') throw new Error('Renderer boot failed: ' + ready + '\n' + logs.join('\n'));
    if (i === 1199) throw new Error('Renderer boot timed out. ' + logs.join('\n'));
    await sleep(100);
  }
  const close = () => {
    try { ws.close(); } catch {}
    const cleanup = () => { try { fs.rmSync(profile, { recursive: true, force: true }); ownTemps.delete(profile); } catch {} };
    if (chromeProcess && chromeProcess.exitCode === null) { chromeProcess.once('close', cleanup); try { chromeProcess.kill('SIGKILL'); } catch {} }
    else cleanup();
    chromeProcess = null;
  };
  return { evaluate, logs, close };
}

const jpegBytes = (dataUrl) => Buffer.from(dataUrl.slice(dataUrl.indexOf(',') + 1), 'base64');
const frameExpression = (time, quality) => `OP.frame(${Number(time)}, ${Number(quality)})`;
const server = await serve(mode === 'preview' ? 8765 : 0), port = server.address().port;
if (mode === 'preview') {
  console.log(`CurioLoop preview listening at http://127.0.0.1:${port}/`);
} else {
  let page;
  try { page = await openPage(port); }
  catch (error) { server.close(); throw error; }
  try {
    const duration = await page.evaluate('OP.duration()');
    if (mode === 'check') {
      console.log(`duration ${duration.toFixed(2)} s`);
      for (const shot of await page.evaluate('OP.shots()')) console.log(`${shot.id} ${shot.at.toFixed(2)}-${shot.end.toFixed(2)}s ${shot.note}`);
      let errors = 0;
      for (let t = 0; t < duration; t += 0.5) { try { await page.evaluate(`OP.draw(${t})`); } catch (e) { errors++; console.log(`ERROR at ${t.toFixed(2)}s: ${e.message}`); } }
      if (page.logs.length) console.log(page.logs.join('\n'));
      if (errors || page.logs.length) { console.log('CHECK FAILED'); process.exitCode = 1; }
      else console.log('CHECK OK');
    } else if (mode === 'cues') {
      const cues = await page.evaluate('OP.cues()'); fs.mkdirSync(path.join(ROOT, 'data'), { recursive: true });
      fs.writeFileSync(path.join(ROOT, 'data/cues.json'), JSON.stringify({ duration, cues }, null, 2));
      console.log(`Saved ${cues.length} narration-based sound cues (${duration.toFixed(2)}s).`);
    } else if (mode === 'frames') {
      const dest = projectOutput(rest[0] || 'review/frames'); fs.mkdirSync(dest, { recursive: true });
      for (const time of (rest[1] || '0').split(',').map(Number)) fs.writeFileSync(path.join(dest, `t${time.toFixed(2)}.jpg`), jpegBytes(await page.evaluate(frameExpression(time, 0.94))));
      console.log(dest);
    } else if (mode === 'sheet') {
      const out = projectOutput(rest[0] || 'review/contact.jpg'), step = Math.max(0.2, +(rest[1] || 1.0)), columns = Math.max(2, Math.min(12, +(rest[2] || 6)));
      const temp = ownTemp('sheet'); let count = 0;
      for (let t = step / 2; t < duration; t += step) fs.writeFileSync(path.join(temp, `f${String(count++).padStart(4, '0')}.jpg`), jpegBytes(await page.evaluate(frameExpression(t, 0.78))));
      const rows = Math.ceil(count / columns); fs.mkdirSync(path.dirname(out), { recursive: true });
      const result = spawnSync(FFMPEG, ['-v', 'error', '-y', '-framerate', '1', '-i', path.join(temp, 'f%04d.jpg'), '-vf', `scale=180:320,tile=${columns}x${rows}:padding=4:color=black`, '-frames:v', '1', out], { windowsHide: true });
      if (result.status !== 0) throw new Error(`Contact-sheet FFmpeg failed: ${result.stderr}`);
      console.log(`${out} (${count} sampled frames)`);
    } else if (mode === 'video') {
      const out = path.resolve(ROOT, rest[0] || 'renders/curioloop.mp4');
      const allowed = process.env.CURIOLOOP_ALLOWED_STAGE_MP4 && path.resolve(process.env.CURIOLOOP_ALLOWED_STAGE_MP4);
      if (!allowed || out !== allowed) throw new Error('Video output must match the owning CurioLoop render staging path.');
      const start = Math.max(0, +(rest[1] || 0)), end = Math.min(duration, +(rest[2] || duration));
      if (!(end > start)) throw new Error('Video capture interval is empty.');
      const mix = path.resolve(ROOT, process.env.CURIOLOOP_MIX_AUDIO || path.join('data', 'mix.wav'));
      if (!fs.existsSync(mix)) throw new Error('Mixed narration audio is missing; refusing to produce a silent video.');
      const allowedMix = process.env.CURIOLOOP_ALLOWED_MIX_AUDIO && path.resolve(process.env.CURIOLOOP_ALLOWED_MIX_AUDIO);
      if (allowedMix && mix !== allowedMix) throw new Error('Narration mix does not match the owning render temporary file.');
      const mixRelative = path.relative(ROOT, mix);
      const tempRelative = path.relative(TMP_ROOT, mix);
      const mixStat = fs.lstatSync(mix);
      if ((!allowedMix && (mixRelative === '..' || mixRelative.startsWith(`..${path.sep}`) || path.isAbsolute(mixRelative)))
          || (allowedMix && (tempRelative === '..' || tempRelative.startsWith(`..${path.sep}`) || path.isAbsolute(tempRelative)))
          || mixStat.isSymbolicLink() || !mixStat.isFile()) {
        throw new Error('Narration mix path is outside the prepared project or is a symbolic link.');
      }
      fs.mkdirSync(path.dirname(out), { recursive: true });
      const total = Math.ceil((end - start) * FPS);
      const ff = spawn(FFMPEG, ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-', '-ss', String(start), '-t', String(end - start), '-i', mix,
        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p', '-r', String(FPS),
        '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out], { stdio: ['pipe', 'ignore', 'inherit'], windowsHide: true });
      let ffError = null; ff.on('error', (e) => { ffError = e; });
      const closed = new Promise((resolve) => ff.once('close', resolve));
      for (let i = 0; i < total; i++) {
        const image = jpegBytes(await page.evaluate(frameExpression(start + i / FPS, 0.90)));
        if (!ff.stdin.write(image)) await new Promise((resolve, reject) => { ff.stdin.once('drain', resolve); ff.stdin.once('error', reject); });
        if (i % 90 === 0) console.log(`Captured ${i}/${total} frames`);
      }
      ff.stdin.end(); const code = await closed;
      if (ffError) throw ffError;
      if (code !== 0) throw new Error(`FFmpeg H.264/AAC render exited ${code}.`);
      console.log(`Rendered ${out} (${total} frames at ${FPS} fps, narration audio included).`);
    } else throw new Error('Use one of: check, cues, frames, sheet, video.');
  } finally { page.close(); server.close(); }
}
