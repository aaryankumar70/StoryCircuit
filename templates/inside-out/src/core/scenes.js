// Inside Out: Dynamic Narration-Matched Scene Choreographer.
// Supports 12 animated vector visual archetypes strictly within top/mid mobile safe zone (y = 250..1160)
// so captions at y=1400 remain completely unobstructed on vertical Shorts screens.
import { ctx, C, W, H, TAU, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line, fillAll, bigText } from './lib.js';
import { L, Le, T } from './timing.js';
import * as K from './kit.js';

function resolveAccent(accent) {
  switch (accent) {
    case 'cyan': return C.cyan;
    case 'crimson': return C.red;
    case 'green': return C.leaf;
    case 'white': return C.white;
    default: return C.yellow;
  }
}

function drawSceneChrome(idx, total, headline, sublabel, accentColor, lt, d) {
  const prog = eob(seg(lt, 0.08, 0.38));
  const subProg = eob(seg(lt, 0.25, 0.58));

  // Subtle chapter track (top bar y=250)
  const trackW = 680, tx0 = (W - trackW) / 2, ty = 248;
  ctx.fillStyle = 'rgba(255,255,255,0.12)';
  rr(tx0, ty, trackW, 6, 3); ctx.fill();
  const frac = total > 1 ? (idx + clamp(lt / Math.max(0.2, d))) / total : clamp(lt / Math.max(0.2, d));
  ctx.fillStyle = accentColor;
  rr(tx0, ty, Math.max(12, trackW * frac), 6, 3); ctx.fill();

  if (headline) {
    K.pill(String(headline).toUpperCase().slice(0, 30), 540, 326, 42, '#0B1524', accentColor, prog);
  }
  if (sublabel) {
    K.pill(String(sublabel).toUpperCase().slice(0, 32), 540, 408, 28, 'rgba(255,255,255,0.12)', C.white, subProg);
  }
}

function drawVisualArchetype(vt, lt, d, t, accentColor, mood) {
  const cy = 790;
  if (vt === 'cosmic_burst' || vt === 'meter_surge') {
    fillAll('#0D1626');
    // Concentric radial field + animated surge gauge
    for (let k = 0; k < 5; k++) {
      const ph = (t * 0.7 + k * 0.2) % 1;
      ctx.strokeStyle = `rgba(255, 212, 59, ${0.42 * (1 - ph)})`;
      ctx.lineWidth = 6;
      ctx.beginPath(); ctx.arc(540, cy, 90 + ph * 340, 0, TAU); ctx.stroke();
    }
    const level = eo(clamp(lt / Math.max(0.4, d * 0.8)));
    circle(540, cy, 185, '#132036');
    ctx.strokeStyle = accentColor; ctx.lineWidth = 10; ctx.stroke();
    // Arc sweep meter
    ctx.strokeStyle = C.red; ctx.lineWidth = 22; ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.arc(540, cy, 145, Math.PI * 0.75, Math.PI * 0.75 + Math.PI * 1.5 * level);
    ctx.stroke();
    ctx.save(); ctx.translate(540, cy); ctx.rotate(-Math.PI * 0.75 + level * Math.PI * 1.5);
    ctx.fillStyle = C.white; ctx.beginPath(); ctx.moveTo(-10, 0); ctx.lineTo(0, -125); ctx.lineTo(10, 0); ctx.fill();
    circle(0, 0, 22, accentColor);
    ctx.restore();
  } else if (vt === 'radar_scan') {
    fillAll(C.navy);
    for (let r = 90; r <= 320; r += 75) {
      ctx.strokeStyle = 'rgba(79, 209, 232, 0.25)'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(540, cy, r, 0, TAU); ctx.stroke();
    }
    line([[200, cy], [880, cy]], 'rgba(79,209,232,0.18)', 2);
    line([[540, cy - 330], [540, cy + 330]], 'rgba(79,209,232,0.18)', 2);
    const sweepAng = (t * 2.1) % TAU;
    ctx.save(); ctx.translate(540, cy); ctx.rotate(sweepAng);
    const g = ctx.createRadialGradient(0, 0, 10, 0, 0, 320);
    g.addColorStop(0, 'rgba(79, 209, 232, 0.55)'); g.addColorStop(1, 'rgba(79, 209, 232, 0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, 320, -0.45, 0.05); ctx.closePath(); ctx.fill();
    ctx.restore();
    // Blip pings synchronized smoothly
    for (let b = 0; b < 3; b++) {
      const bx = 540 + Math.cos(b * 2.1 + 0.8) * (110 + b * 65);
      const by = cy + Math.sin(b * 2.1 + 0.8) * (110 + b * 65);
      const pulse = 0.5 + 0.5 * Math.sin(t * 6 + b * 2);
      circle(bx, by, 10 + pulse * 8, accentColor);
    }
  } else if (vt === 'ocean_depth' || vt === 'micro_stream') {
    fillAll('#092030');
    for (let layer = 0; layer < 4; layer++) {
      const baseY = 560 + layer * 135;
      ctx.strokeStyle = `rgba(79, 209, 232, ${0.22 + layer * 0.1})`;
      ctx.lineWidth = 6;
      ctx.beginPath();
      for (let x = -40; x <= W + 40; x += 30) {
        const y = baseY + Math.sin(x * 0.012 + t * (1.5 + layer * 0.4) + layer) * 26;
        x === -40 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    for (let i = 0; i < 16; i++) {
      const x = ((t * (180 + rnd(i) * 160) + rnd(i + 5) * 1200) % 1240) - 80;
      const y = 520 + rnd(i + 12) * 560 + Math.sin(t * 3 + i) * 18;
      circle(x, y, 10 + rnd(i + 3) * 16, i % 3 === 0 ? accentColor : 'rgba(255,255,255,0.45)');
    }
  } else if (vt === 'archive_map' || vt === 'timeline') {
    fillAll('#101A2B');
    // Vector timeline / route progression spline
    const p = eo(clamp(lt / Math.max(0.3, d * 0.75)));
    ctx.strokeStyle = 'rgba(255,255,255,0.16)'; ctx.lineWidth = 8;
    ctx.beginPath(); ctx.moveTo(180, cy + 90); ctx.bezierCurveTo(380, cy - 160, 700, cy + 160, 900, cy - 80); ctx.stroke();
    ctx.strokeStyle = accentColor; ctx.lineWidth = 10; ctx.setLineDash([18, 12]);
    ctx.beginPath(); ctx.moveTo(180, cy + 90); ctx.bezierCurveTo(380, cy - 160, lerp(380, 700, p), lerp(cy - 160, cy + 160, p), lerp(180, 900, p), lerp(cy + 90, cy - 80, p)); ctx.stroke();
    ctx.setLineDash([]);
    for (let node = 0; node < 4; node++) {
      const nx = lerp(180, 900, node / 3);
      const ny = cy + Math.sin(node * 1.6) * 110;
      const reached = p >= node / 3;
      circle(nx, ny, reached ? 24 : 16, reached ? accentColor : '#344660');
      if (reached) {
        circle(nx, ny, 10, '#0B1524');
      }
    }
  } else if (vt === 'split_compare') {
    fillAll('#0D1624');
    const slide = eo(seg(lt, 0.05, 0.5));
    rr(110 - (1 - slide) * 120, 520, 400, 540, 28); ctx.fillStyle = '#17253B'; ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.lineWidth = 4; ctx.stroke();
    rr(570 + (1 - slide) * 120, 520, 400, 540, 28); ctx.fillStyle = '#192B3D'; ctx.fill();
    ctx.strokeStyle = accentColor; ctx.lineWidth = 5; ctx.stroke();
    K.pill('A', 310, 620, 54, '#243652', C.white, slide);
    K.pill('B', 770, 620, 54, accentColor, C.ink, slide);
    K.arrow(540, 790, 120, 0, slide);
  } else if (vt === 'neural_pulse') {
    K.xray(t);
    for (let i = 0; i < 16; i++) {
      const x1 = 180 + rnd(i * 3) * 720, y1 = 500 + rnd(i * 3 + 1) * 560;
      const x2 = 180 + rnd((i + 1) * 3) * 720, y2 = 500 + rnd((i + 1) * 3 + 1) * 560;
      ctx.strokeStyle = 'rgba(79, 209, 232, 0.28)'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      const pulse = 0.5 + 0.5 * Math.sin(t * 5 + i);
      circle(x1, y1, 8 + pulse * 8, i % 3 === 0 ? accentColor : C.cyan);
    }
    K.heart(540, cy, 1.35, 0.5 + 0.5 * Math.sin(t * 4));
  } else if (vt === 'payoff_reveal') {
    fillAll('#0B1E1A');
    const burstAmt = eob(seg(lt, 0.15, 0.55));
    K.burst(540, cy, 1.4, burstAmt * 0.7);
    K.man({ x: 540, y: 1030, s: 1.35, mouth: 'smile', eyes: 'n', brow: 0, arm: K.armPose(K.ARM.down, K.ARM.point, clamp(lt * 2)) });
  } else {
    // tension_room / vault_mystery fallback inside safe zone
    fillAll(mood === 'urgent' ? '#1E1118' : '#131D2D');
    const pulse = eio(seg(lt, 0, d));
    circle(540, cy, 240 + pulse * 30, 'rgba(255,255,255,0.04)');
    ctx.strokeStyle = accentColor; ctx.lineWidth = 6; ctx.stroke();
    K.man({
      x: 540, y: 1020, s: 1.32,
      mouth: mood === 'urgent' ? 'o' : 'flat',
      eyes: mood === 'mystery' ? 'closed' : 'wide',
      brow: 1,
      arm: K.armPose(K.ARM.down, K.ARM.mouth, clamp(lt * 1.4)),
    });
  }
}

export function buildDynamicStoryShots(script) {
  const S = [], CUES = [];
  const lines = Array.isArray(script?.lines) ? script.lines : [];
  const total = lines.length;
  lines.forEach((ln, i) => {
    const at = i === 0 ? 0 : Math.max(0, L(i) - 0.08);
    const sc = ln.scene || {};
    const vt = sc.visual_type || 'tension_room';
    const accent = resolveAccent(sc.accent);
    const mood = sc.mood || 'mystery';
    const zoom = mood === 'urgent' || mood === 'tense' ? 0.11 : 0.06;
    S.push({
      id: `S${String(i + 1).padStart(2, '0')}`,
      at,
      cam: [540, 820],
      zoom,
      note: `${vt}: ${sc.headline || ln.text.slice(0, 40)}`,
      draw(lt, d, t) {
        drawVisualArchetype(vt, lt, d, t, accent, mood);
        drawSceneChrome(i, total, sc.headline, sc.sublabel, accent, lt, d);
      },
    });
    const cueType = sc.cue || (i === total - 1 ? 'sparkle' : i === 0 ? 'whoosh' : 'pop');
    CUES.push({ t: +at.toFixed(3), type: cueType, gain: 0.65 });
  });
  return { shots: S, cues: CUES };
}
