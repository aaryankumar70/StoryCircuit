// CurioLoop 2.0 Narrative Visual Engine Bootstrapping & OP Driver
// Exposes window.OP for tools/capture.mjs frame-exact headless Chromium rendering.
import { W, H, setCtx, ctx, clamp, eo, eio, drawCurioLoopBadge } from './core/lib.js';
import { T, loadTiming } from './core/timing.js';
import { buildCaptions, drawCaption, captionList } from './core/captions.js';
import { buildNarrativeShots } from './narrative_scenes.js';
import { initThreeVisualEngine } from './three_scenes.js';

const cv = document.getElementById('cv');
setCtx(cv.getContext('2d'));
const OP = (window.OP = { ready: false });

function draw(t) {
  t = clamp(t, 0, T.dur - 1e-4);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.letterSpacing = '0px';

  // Base background fill
  ctx.fillStyle = '#06080d';
  ctx.fillRect(0, 0, W, H);

  const S = OP._shots || [];
  if (S.length > 0) {
    let i = S.length - 1;
    while (i > 0 && S[i].at > t) i--;
    const sh = S[i];
    const end = i < S.length - 1 ? S[i + 1].at : T.dur;
    const d = Math.max(0.1, end - sh.at);
    const lt = t - sh.at;

    sh.draw(lt, d, t);

    // Subtle narrative cut transition (0.12s dip)
    if (i > 0 && lt < 0.12) {
      ctx.fillStyle = '#06080d';
      ctx.globalAlpha = 0.28 * (1 - lt / 0.12);
      ctx.fillRect(0, 0, W, H);
      ctx.globalAlpha = 1;
    }
  }

  // Fade from / to black on first and last 0.28 s
  const fade = Math.min(clamp(t / 0.28, 0, 1), clamp((T.dur - t) / 0.35, 0, 1));
  if (fade < 1) {
    ctx.fillStyle = '#000';
    ctx.globalAlpha = 1 - fade;
    ctx.fillRect(0, 0, W, H);
    ctx.globalAlpha = 1;
  }

  // Word-level Subtitles & Brand Badge
  drawCaption(t);
  drawCurioLoopBadge();
}

(async () => {
  try {
    initThreeVisualEngine();
    await document.fonts.load('900 100px Inter');
    const script = await (await fetch('script.json', { cache: 'no-store' })).json();
    
    // Fetch storyboard.json if available
    let storyboard = null;
    try {
      const sbResp = await fetch('storyboard.json', { cache: 'no-store' });
      if (sbResp.ok) storyboard = await sbResp.json();
    } catch (e) {
      console.warn('storyboard.json not found, falling back to script.json');
    }

    await loadTiming();
    buildCaptions(script);

    const { shots, cues } = buildNarrativeShots(script, storyboard);
    shots.sort((a, b) => a.at - b.at);

    OP._shots = shots;
    OP.script = script;
    OP.storyboard = storyboard;
    OP.duration = () => T.dur;
    OP.draw = draw;
    OP.frame = (t, q = 0.92) => {
      draw(t);
      return cv.toDataURL('image/jpeg', q);
    };
    OP.shots = () =>
      shots.map((s, i) => ({
        id: s.id,
        at: +s.at.toFixed(3),
        end: +(i < shots.length - 1 ? shots[i + 1].at : T.dur).toFixed(3),
        note: s.scene?.visual_objective || s.id,
      }));
    OP.captions = () =>
      captionList().map((c) => ({
        s: +c.s.toFixed(3),
        e: +c.e.toFixed(3),
        text: c.words.map((w) => (w.hi ? '*' : '') + w.txt).join(' '),
      }));
    OP.cues = () => cues.slice().sort((a, b) => a.t - b.t);
    OP.ready = true;

    // Interactive preview playback when ?capture is not present
    const q = new URLSearchParams(location.search);
    if (!q.has('capture')) {
      if (q.has('t')) {
        draw(+q.get('t'));
      } else {
        const audio = new Audio('data/mix.wav');
        let t0 = null;
        const btn = document.getElementById('play');
        btn.hidden = false;
        btn.onclick = () => {
          btn.hidden = true;
          t0 = performance.now();
          audio.currentTime = 0;
          audio.play().catch(() => {});
        };
        const loop = (now) => {
          const t = t0 == null ? 0 : (now - t0) / 1000;
          draw(t0 == null ? 0 : t);
          if (t0 != null && t > T.dur) {
            t0 = null;
            btn.hidden = false;
          }
          requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
      }
    }
  } catch (err) {
    console.error('Fatal bootstrapping error:', err);
    OP.bootError = String(err.message || err);
  }
})();
