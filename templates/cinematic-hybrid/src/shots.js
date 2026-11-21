// CurioLoop Studio - Inside Out Style
// Topic: "Why do your ears ring in absolute silence?"
// Visual Choreography: Soundproof chamber -> High-pitch acoustic ring -> Ear anatomy -> Brainstem gain knob -> Blood cells -> Neural search radar
import { ctx, C, W, H, TAU, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line, fillAll, bigText } from './core/lib.js';
import { L, Le, Wd, T } from './core/timing.js';
import * as K from './core/kit.js';
import { buildDynamicStoryShots } from './core/scenes.js';

// ── Additional Anatomical & Acoustic Set Pieces ──
function drawAcousticChamber(doorClosed = 1) {
  fillAll('#1E2530');
  // Wall acoustic foam wedges (triangles)
  ctx.fillStyle = '#2A3444';
  const wedgeH = 60, wedgeW = 40;
  for (let y = 100; y < 1500; y += wedgeH) {
    // Left wall wedges
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(80, y + wedgeH / 2); ctx.lineTo(0, y + wedgeH); ctx.fill();
    // Right wall wedges
    ctx.beginPath(); ctx.moveTo(W, y); ctx.lineTo(W - 80, y + wedgeH / 2); ctx.lineTo(W, y + wedgeH); ctx.fill();
  }
  // Floor grid
  ctx.fillStyle = '#141A22';
  ctx.fillRect(-300, 1500, W + 600, 700);
  ctx.strokeStyle = '#344256'; ctx.lineWidth = 4;
  for (let x = 80; x < W; x += 90) { ctx.beginPath(); ctx.moveTo(x, 1500); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 1500; y < H; y += 70) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

  // Chamber door frame
  if (doorClosed > 0) {
    ctx.fillStyle = `rgba(10, 14, 20, ${0.45 * doorClosed})`;
    ctx.fillRect(100, 260, W - 200, 1200);
  }
}

function drawSpiralCochlea(cx, cy, s = 1, glow = 0) {
  ctx.save(); ctx.translate(cx, cy); ctx.scale(s, s);
  if (glow > 0) {
    ctx.shadowColor = C.yellow; ctx.shadowBlur = 24 * glow;
  }
  ctx.strokeStyle = C.yellow; ctx.lineWidth = 22; ctx.lineCap = 'round';
  ctx.beginPath();
  for (let a = 0; a < Math.PI * 4.5; a += 0.1) {
    const r = 160 * Math.exp(-0.25 * a);
    const x = r * Math.cos(a), y = r * Math.sin(a);
    a === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
  circle(0, 0, 24, C.white);
  ctx.restore();
}

function drawGainDial(cx, cy, gain = 1, t = 0) {
  ctx.save(); ctx.translate(cx, cy);
  // Outer bezel
  circle(0, 0, 180, '#101A28');
  ctx.strokeStyle = C.cyan; ctx.lineWidth = 8; ctx.stroke();
  // Graduation marks
  for (let i = 0; i < 12; i++) {
    const ang = -Math.PI * 0.75 + (i / 11) * Math.PI * 1.5;
    ctx.strokeStyle = i < gain * 12 ? C.yellow : '#344660';
    ctx.lineWidth = i % 3 === 0 ? 8 : 4;
    ctx.beginPath();
    ctx.moveTo(Math.cos(ang) * 140, Math.sin(ang) * 140);
    ctx.lineTo(Math.cos(ang) * 165, Math.sin(ang) * 165);
    ctx.stroke();
  }
  // Indicator needle
  const needleAng = -Math.PI * 0.75 + gain * Math.PI * 1.5;
  ctx.save(); ctx.rotate(needleAng);
  ctx.fillStyle = C.red;
  ctx.beginPath(); ctx.moveTo(-10, 0); ctx.lineTo(0, -135); ctx.lineTo(10, 0); ctx.fill();
  circle(0, 0, 26, C.white);
  ctx.restore();

  // Digital gain readout
  K.pill(`+${Math.round(gain * 60)} dB GAIN`, 0, 240, 48, C.ink, C.yellow);
  ctx.restore();
}

function drawBloodVessel(t) {
  fillAll('#5C1424');
  // Arterial lumen walls
  ctx.fillStyle = '#821C34';
  ctx.fillRect(-300, 360, W + 600, 960);
  ctx.strokeStyle = '#B83252'; ctx.lineWidth = 18;
  ctx.beginPath(); ctx.moveTo(-300, 360); ctx.lineTo(W + 300, 360); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(-300, 1320); ctx.lineTo(W + 300, 1320); ctx.stroke();

  // Flowing red blood cells (erythrocytes)
  for (let i = 0; i < 18; i++) {
    const speed = 380 + rnd(i) * 180;
    const x = ((t * speed + rnd(i + 10) * 1400) % 1500) - 200;
    const y = 480 + rnd(i + 20) * 720;
    const rot = Math.sin(t * 3 + i) * 0.5;
    const s = 0.85 + rnd(i + 3) * 0.4;

    ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(s, s);
    // Biconcave disc
    circle(0, 0, 52, '#D62839');
    circle(0, 0, 32, '#A61A28');
    ell(-12, -10, 16, 8, '#F27282', -0.3);

    // Microscopic acoustic vibration rings around blood cell
    const ringPhase = (t * 4 + i * 0.3) % 1;
    ctx.strokeStyle = `rgba(255, 212, 59, ${0.7 * (1 - ringPhase)})`;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(0, 0, 56 + ringPhase * 60, 0, TAU);
    ctx.stroke();
    ctx.restore();
  }
}

export function buildShots(script = null) {
  const isEarAnatomyTopic =
    script?.id === 'bio_silence_ringing' ||
    String(script?.topic || script?.title || '').toLowerCase().includes('ears ring');
  const hasExplicitDynamicScenes = Array.isArray(script?.lines) && script.lines.some((ln) => ln?.scene?.visual_type);
  if (script && (!isEarAnatomyTopic || hasExplicitDynamicScenes && script.lines.length !== 6)) {
    return buildDynamicStoryShots(script);
  }
  const S = [], CUES = [];
  const add = (o) => (S.push(o), o);
  const cue = (t, type, o = {}) => CUES.push({ t: +t.toFixed(3), type, ...o });
  const cut = (i) => (i === 0 ? 0 : L(i) - 0.08);

  // ── 1 · HOOK: Stepping into soundproof chamber ─────────────────────────────
  {
    const st = cut(0);
    add({
      id: 'S01', at: st, cam: [540, 840], note: 'anechoic chamber, silence tag, hero steps in',
      draw(lt, d, t) {
        drawAcousticChamber(clamp(lt / 0.5));
        const walk = eio(seg(lt, 0, 0.8));
        const manX = lerp(200, 540, walk);
        K.man({
          x: manX, y: 1200, s: 1.5,
          mouth: 'o', eyes: 'wide', brow: 1,
          arm: K.armPose(K.ARM.down, K.ARM.point, walk)
        });
        K.pill('ANECHOIC CHAMBER (0 dB)', 540, 360, 48, C.ink, C.white, eob(seg(lt, 0.2, 0.6)));
        if (lt > 0.8) {
          bigText('TOTAL SILENCE?', 540, 500, 78, C.yellow, 0, eob(seg(lt, 0.8, 1.1)));
        }
      }
    });
    cue(st, 'whoosh'); cue(st + 0.4, 'thud', { gain: 0.6 }); cue(st + 0.9, 'pop');
  }

  // ── 2 · HIGH-PITCHED RING: Ear frequency burst ──────────────────────────────
  {
    const st = cut(1);
    add({
      id: 'S02', at: st, cam: [540, 760], zoom: 0.15, note: 'ringing ear close-up, vibrating sine waves',
      draw(lt, d, t) {
        fillAll(C.navy);
        // Acoustic sine wave ripple across screen
        ctx.strokeStyle = 'rgba(79, 209, 232, 0.35)'; ctx.lineWidth = 6;
        ctx.beginPath();
        for (let x = 0; x <= W; x += 15) {
          const y = 800 + Math.sin(x * 0.04 + lt * 25) * 60;
          x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Hero clutching ear in astonishment
        const shake = Math.sin(lt * 80) * 8;
        K.man({
          x: 540 + shake, y: 1100, s: 1.6,
          mouth: 'o', eyes: 'wide', brow: 1,
          arm: K.ARM.mouth
        });

        // Pulsing ringing rings from ear
        for (let k = 0; k < 5; k++) {
          const ph = (lt * 3.5 + k * 0.22) % 1;
          ctx.strokeStyle = `rgba(255, 212, 59, ${1 - ph})`;
          ctx.lineWidth = 12 * (1 - ph * 0.5);
          ctx.beginPath();
          ctx.arc(680, 520, 40 + ph * 320, -Math.PI * 0.6, Math.PI * 0.6);
          ctx.stroke();
        }

        K.shockLines(540, 520, 240, clamp(lt * 4));
        K.pill('HIGH-FREQUENCY RING: 4,000 Hz', 540, 320, 52, C.ink, C.yellow, eob(seg(lt, 0.1, 0.4)));
      }
    });
    cue(st, 'whoosh'); cue(st + 0.15, 'sparkle', { dur: 1.4 }); cue(st + 0.5, 'boing');
  }

  // ── 3 · X-RAY EAR ANATOMY: Cochlea intact ─────────────────────────────────
  {
    const st = cut(2);
    add({
      id: 'S03', at: st, cam: [540, 860], note: 'ear cross section, golden spiral cochlea, not damaged',
      draw(lt, d, t) {
        K.xray(t);
        // Hero head silhouette in translucent cyan
        ctx.save(); ctx.translate(340, 820);
        circle(0, 0, 260, 'rgba(79, 209, 232, 0.12)');
        ctx.strokeStyle = C.cyan; ctx.lineWidth = 8; ctx.stroke();

        // Ear canal path
        ctx.strokeStyle = C.white; ctx.lineWidth = 18; ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(260, 0); ctx.lineTo(80, 0); ctx.stroke();
        ctx.restore();

        // Prominent glowing golden cochlea
        drawSpiralCochlea(540, 780, 1.4, 0.8 + 0.2 * Math.sin(lt * 8));

        // Green checkmark / Verification badge
        const popTime = seg(lt, 0.3, 0.6);
        K.pill('COCHLEA: 100% HEALTHY', 540, 420, 54, '#0D3820', '#5BAE6A', eob(popTime));
        K.pill('NO PHYSICAL DAMAGE', 540, 1160, 48, C.ink, C.white, eob(seg(lt, 0.6, 0.9)));
      }
    });
    cue(st, 'whoosh'); cue(st + 0.3, 'pop', { gain: 0.7 });
  }

  // ── 4 · BRAIN GAIN CONTROL: Volume slider turns up ─────────────────────────
  {
    const st = cut(3);
    add({
      id: 'S04', at: st, cam: [540, 850], note: 'brainstem neural gain dial surging to max',
      draw(lt, d, t) {
        fillAll(C.navy);
        // Brain neural network web
        ctx.strokeStyle = 'rgba(79, 209, 232, 0.25)'; ctx.lineWidth = 3;
        for (let i = 0; i < 14; i++) {
          const x1 = 200 + rnd(i) * 680, y1 = 300 + rnd(i + 5) * 500;
          const x2 = 200 + rnd(i + 1) * 680, y2 = 300 + rnd(i + 6) * 500;
          ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
          circle(x1, y1, 8, C.cyan);
        }

        // Active gain dial advancing smoothly
        const gainVal = eo(clamp(lt / (d * 0.75)));
        drawGainDial(540, 920, gainVal, t);

        K.pill('DORSAL COCHLEAR NUCLEUS', 540, 360, 50, C.ink, C.white, eob(seg(lt, 0.1, 0.4)));
        if (gainVal > 0.7) {
          K.burst(540, 920, 1.5, clamp((gainVal - 0.7) * 3));
        }
      }
    });
    cue(st, 'whoosh'); cue(st + 0.2, 'slide', { dur: 1.2 }); cue(st + 1.0, 'alarm', { dur: 0.8 });
  }

  // ── 5 · BLOOD CELLS FLOWING: Amplified vibration ───────────────────────────
  {
    const st = cut(4);
    add({
      id: 'S05', at: st, cam: [540, 880], zoom: 0.1, note: 'flowing red blood cells generating acoustic ripple',
      draw(lt, d, t) {
        drawBloodVessel(t);
        K.pill('AMPLIFYING BLOOD CELL FLOW', 540, 260, 50, C.ink, C.yellow, eob(seg(lt, 0.1, 0.4)));
        K.pill('INTERNAL SYNAPTIC NOISE', 540, 1460, 48, C.ink, C.white, eob(seg(lt, 0.5, 0.8)));
      }
    });
    cue(st, 'whoosh'); cue(st + 0.15, 'bubbles', { dur: 1.8 }); cue(st + 0.8, 'sparkle', { dur: 1.0 });
  }

  // ── 6 · SATISFYING RESOLUTION: Brain searching for sound ───────────────────
  {
    const st = cut(5);
    add({
      id: 'S06', at: st, cam: [540, 840], note: 'peaceful hero, radar search waves, satisfying resolution',
      draw(lt, d, t) {
        K.room();
        // Radiating radar antenna arcs from head
        for (let i = 0; i < 4; i++) {
          const p = (lt * 0.8 + i * 0.25) % 1;
          ctx.strokeStyle = `rgba(79, 209, 232, ${0.85 * (1 - p)})`;
          ctx.lineWidth = 8;
          ctx.beginPath();
          ctx.arc(540, 620, 60 + p * 420, -Math.PI * 0.9, -Math.PI * 0.1);
          ctx.stroke();
        }

        // Hero looking up calmly and knowingly
        K.man({
          x: 540, y: 1180, s: 1.55,
          mouth: 'smile', eyes: 'n', brow: 0,
          arm: K.armPose(K.ARM.down, K.ARM.hip, 0.8)
        });

        K.pill('NOT DAMAGE — AN ADAPTIVE BRAIN', 540, 320, 52, '#0B2238', C.yellow, eob(seg(lt, 0.2, 0.55)));
        K.pill('SEARCHING FOR FREQUENCIES', 540, 440, 46, C.ink, C.white, eob(seg(lt, 0.55, 0.85)));
      }
    });
    cue(st, 'whoosh'); cue(st + 0.25, 'sparkle', { dur: 1.5 }); cue(st + 0.7, 'pop');
  }

  return { shots: S, cues: CUES };
}
