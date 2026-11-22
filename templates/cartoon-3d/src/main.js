// CurioLoop's browser renderer: 3D cartoon worlds, original 2D character sprites,
// narration-synchronized shots and word-level captions.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { BokehPass } from 'three/addons/postprocessing/BokehPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { buildShots } from './shots.js';

const W = 1080, H = 1920, SCALE = Math.max(0.42, Math.min(0.72, +(new URLSearchParams(location.search).get('res') || 0.56)));
const canvas = document.getElementById('cv'), glCanvas = document.getElementById('gl');
const ctx = canvas.getContext('2d', { alpha: false, desynchronized: true });
const OP = (window.OP = { ready: false });

async function readJson(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not read ${path}: HTTP ${response.status}`);
  return response.json();
}

function drawCaption(words, time) {
  if (!words.length) return;
  let lo = 0, hi = words.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (words[mid].s <= time) lo = mid + 1; else hi = mid; }
  const item = words[Math.max(0, lo - 1)];
  if (!item || time < item.s || time > item.e + 0.12) return;
  const text = String(item.w || '').trim();
  if (!text) return;
  ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = '900 76px Arial, sans-serif';
  ctx.lineJoin = 'round'; ctx.lineWidth = 11; ctx.strokeStyle = 'rgba(8, 14, 24, 0.92)';
  ctx.shadowColor = 'rgba(0,0,0,0.55)'; ctx.shadowBlur = 14; ctx.shadowOffsetY = 4;
  const y = 1478, width = Math.min(890, ctx.measureText(text).width + 52);
  ctx.fillStyle = 'rgba(13, 20, 31, 0.58)'; ctx.beginPath(); ctx.roundRect((W - width) / 2, y - 56, width, 112, 24); ctx.fill();
  ctx.strokeText(text, W / 2, y); ctx.fillStyle = '#FFF7E8'; ctx.fillText(text, W / 2, y);
  ctx.restore();
}

(async () => {
  try {
    canvas.width = W; canvas.height = H;
    const script = await readJson('script.json');
    const timing = await readJson('data/lines.json');
    const wordData = await readJson('data/words.json').catch(() => []);
    const words = Array.isArray(wordData) ? wordData.filter((w) => Number.isFinite(+w.s) && Number.isFinite(+w.e)).sort((a, b) => a.s - b.s) : [];
    const duration = Math.max(0.1, +timing.duration || 0);
    const result = buildShots(script, timing);
    const shots = result.shots.sort((a, b) => a.at - b.at);
    if (!shots.length || !duration) throw new Error('Narration timing or directed scenes are empty.');

    glCanvas.width = Math.round(W * SCALE); glCanvas.height = Math.round(H * SCALE);
    const renderer = new THREE.WebGLRenderer({ canvas: glCanvas, antialias: false, alpha: false, powerPreference: 'low-power', preserveDrawingBuffer: true });
    renderer.setSize(glCanvas.width, glCanvas.height, false);
    renderer.setPixelRatio(1); renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    const composer = new EffectComposer(renderer);
    const renderPass = new RenderPass(new THREE.Scene(), new THREE.PerspectiveCamera());
    const bokeh = new BokehPass(renderPass.scene, renderPass.camera, { focus: 8, aperture: 0.0018, maxblur: 0.004 });
    composer.addPass(renderPass); composer.addPass(bokeh); composer.addPass(new OutputPass());
    composer.setSize(glCanvas.width, glCanvas.height);

    const render3d = (scene, camera, look = {}) => {
      renderPass.scene = scene; renderPass.camera = camera;
      bokeh.scene = scene; bokeh.camera = camera;
      bokeh.uniforms.focus.value = look.focus || 8;
      bokeh.uniforms.aperture.value = look.aperture ?? 0.0018;
      bokeh.uniforms.maxblur.value = look.maxblur ?? 0.004;
      renderer.toneMappingExposure = look.exposure || 1.0;
      composer.render();
    };

    function draw(time) {
      const t = Math.max(0, Math.min(duration - 0.0001, Number(time) || 0));
      let index = shots.length - 1;
      while (index > 0 && shots[index].at > t) index--;
      const shot = shots[index], stop = index < shots.length - 1 ? shots[index + 1].at : duration;
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.fillStyle = '#101725'; ctx.fillRect(0, 0, W, H);
      const transition = shot.draw(t - shot.at, Math.max(0.35, stop - shot.at), t, render3d, ctx);
      ctx.drawImage(glCanvas, 0, 0, W, H);
      if (transition?.alpha > 0) { ctx.save(); ctx.globalAlpha = transition.alpha; ctx.fillStyle = transition.color; ctx.fillRect(0, 0, W, H); ctx.restore(); }
      const fadeIn = Math.max(0, 1 - t / 0.22), fadeOut = Math.max(0, 1 - (duration - t) / 0.3);
      if (fadeIn > 0 || fadeOut > 0) {
        ctx.fillStyle = '#101725'; ctx.globalAlpha = Math.max(fadeIn, fadeOut); ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1;
      }
      drawCaption(words, t);
      return t;
    }

    OP.script = script; OP.duration = () => duration;
    OP.shots = () => shots.map((s, i) => ({ id: s.id, at: +s.at.toFixed(3), end: +(i < shots.length - 1 ? shots[i + 1].at : duration).toFixed(3), note: s.note }));
    OP.captions = () => words.map((w) => ({ s: +w.s, e: +w.e, text: String(w.w || '') }));
    OP.cues = () => result.cues.slice().sort((a, b) => a.t - b.t);
    OP.draw = draw; OP.frame = (t, quality = 0.92) => { draw(t); return canvas.toDataURL('image/jpeg', quality); };
    OP.ready = true; draw(0);

    if (!new URLSearchParams(location.search).has('capture')) {
      const audio = new Audio('data/mix.wav'); let origin = null;
      const button = document.getElementById('play'); button.hidden = false;
      button.onclick = () => { button.hidden = true; origin = performance.now(); audio.currentTime = 0; audio.play().catch(() => {}); };
      const loop = (now) => {
        const t = origin == null ? 0 : (now - origin) / 1000;
        draw(t);
        if (origin != null && t >= duration) { origin = null; button.hidden = false; }
        requestAnimationFrame(loop);
      };
      requestAnimationFrame(loop);
    }
  } catch (error) {
    OP.bootError = String(error?.stack || error); console.error(OP.bootError);
  }
})();
