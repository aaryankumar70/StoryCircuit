// Paper Atlas: Dynamic Cut-Paper & Archival Story Scene Choreographer.
// Places illustrations & archival overlays strictly within y=250..1160 above mobile captions (y=1400).
import { ctx, W, H, TAU, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line } from './lib.js';
import { L } from './timing.js';
import * as K from './kit.js';

const { P, cut, P_rr, P_poly, P_circ } = K;

function drawStoryStage(vt, lt, d, t, sc, idx, total) {
  const accent = sc.accent === 'crimson' ? P.crimson : (sc.accent === 'cyan' ? P.sea : P.gold);
  K.parchment(idx + 3);
  const cy = 830;

  if (vt === 'archive_map' || vt === 'timeline') {
    // Aged nautical map lines & crimson expedition route
    ctx.strokeStyle = 'rgba(168, 50, 45, 0.25)'; ctx.lineWidth = 4;
    for (let x = 140; x <= 940; x += 200) {
      ctx.beginPath(); ctx.moveTo(x, 480); ctx.lineTo(x, 1140); ctx.stroke();
    }
    const p = eo(clamp(lt / Math.max(0.3, d * 0.8)));
    ctx.strokeStyle = P.crimson; ctx.lineWidth = 10; ctx.setLineDash([20, 12]);
    ctx.beginPath();
    ctx.moveTo(200, 980);
    ctx.bezierCurveTo(420, 620, 660, 1020, lerp(200, 880, p), lerp(980, 660, p));
    ctx.stroke(); ctx.setLineDash([]);
    K.compass(840, 980, 0.55);
    K.seal(250, 660, eob(seg(lt, 0.15, 0.5)), String(idx + 1));
  } else if (vt === 'ocean_depth' || vt === 'micro_stream') {
    ctx.fillStyle = P.seaDark; ctx.fillRect(-300, 450, W + 600, 760);
    for (let i = 0; i < 4; i++) {
      const y = 580 + i * 130;
      cut(() => {
        ctx.beginPath(); ctx.moveTo(-300, H + 300); ctx.lineTo(-300, y);
        for (let x = -300; x <= W + 300; x += 40) ctx.lineTo(x, y + Math.sin(x * 0.014 + t * 2 + i) * 20);
        ctx.lineTo(W + 300, H + 300); ctx.closePath();
      }, i % 2 ? P.sea : '#254340', { shadow: 0.5, edge: 4 });
    }
    for (let i = 0; i < 12; i++) {
      const bx = 180 + rnd(i * 4) * 720;
      const by = 1120 - ((t * 95 + rnd(i) * 500) % 520);
      circle(bx, by, 7 + rnd(i + 2) * 7, 'rgba(255,248,230,0.45)');
    }
  } else if (vt === 'vault_mystery' || vt === 'split_compare') {
    const p = eo(seg(lt, 0.05, 0.48));
    cut(P_rr(130, 560, 380, 490, 18), P.parch, { shadow: 0.7, edge: 5 });
    cut(P_rr(570, 560, 380, 490, 18), P.parchDark, { shadow: 0.7, edge: 5 });
    K.figure({ x: 320, y: 1020, h: 360, role: 'scholar', dir: 1, arm: 25 * p });
    K.figure({ x: 760, y: 1020, h: 360, role: 'merchant', dir: -1 });
    K.seal(540, 810, eob(seg(lt, 0.25, 0.55)), '?');
  } else if (vt === 'radar_scan' || vt === 'neural_pulse' || vt === 'cosmic_burst') {
    for (let k = 0; k < 4; k++) {
      const ph = (t * 0.65 + k * 0.25) % 1;
      ctx.strokeStyle = `rgba(168, 50, 45, ${0.55 * (1 - ph)})`; ctx.lineWidth = 6;
      ctx.beginPath(); ctx.arc(540, cy, 80 + ph * 280, 0, TAU); ctx.stroke();
    }
    cut(P_circ(540, cy, 150), '#1E2A3A', { shadow: 0.8, edge: 5 });
    K.compass(540, cy, 0.95);
  } else if (vt === 'payoff_reveal') {
    cut(P_rr(150, 540, 780, 520, 24), P.parch, { shadow: 0.9, edge: 6 });
    K.figure({ x: 540, y: 1030, h: 420, role: 'scholar', dir: 1, arm: 20 });
    K.seal(810, 650, eob(seg(lt, 0.2, 0.5)), '✓');
  } else {
    // tension_room / meter_surge archival illustration
    cut(P_rr(140, 540, 800, 520, 18), '#EFE6CE', { shadow: 0.8, edge: 5 });
    const role = idx % 2 === 0 ? 'guard' : 'scholar';
    K.figure({ x: 540, y: 1020, h: 440, role, dir: idx % 2 === 0 ? 1 : -1, arm: 15 });
  }

  // Paper ribbons & index slips kept strictly above y=520 (safe zone >=250)
  const prog = eob(seg(lt, 0.08, 0.36));
  const subProg = eob(seg(lt, 0.25, 0.56));
  if (sc.headline) {
    K.ribbon(String(sc.headline).toUpperCase().slice(0, 28), 540, 316, prog);
  }
  if (sc.sublabel) {
    K.slip(String(sc.sublabel).toUpperCase().slice(0, 32), 540, 434, subProg, (idx % 2 ? 0.015 : -0.015), 34);
  }

  // Clean story progress strip
  const barW = 640, bx = (W - barW) / 2;
  ctx.fillStyle = 'rgba(28, 28, 34, 0.14)'; rr(bx, 242, barW, 5, 3); ctx.fill();
  ctx.fillStyle = accent; rr(bx, 242, Math.max(12, barW * ((idx + clamp(lt / Math.max(0.2, d))) / Math.max(1, total))), 5, 3); ctx.fill();
}

export function buildDynamicStoryShots(script) {
  const S = [], CUES = [];
  const lines = Array.isArray(script?.lines) ? script.lines : [];
  const total = lines.length;
  lines.forEach((ln, i) => {
    const at = i === 0 ? 0 : Math.max(0, L(i) - 0.08);
    const sc = ln.scene || {};
    const vt = sc.visual_type || 'archive_map';
    const zoom = (sc.mood === 'urgent' || sc.mood === 'tense') ? 0.10 : 0.06;
    S.push({
      id: `S${String(i + 1).padStart(2, '0')}`,
      at,
      cam: [540, 840],
      zoom,
      note: `${vt}: ${sc.headline || ln.text.slice(0, 40)}`,
      draw(lt, d, t) {
        drawStoryStage(vt, lt, d, t, sc, i, total);
      },
    });
    const cueType = sc.cue || (i === total - 1 ? 'sparkle' : i === 0 ? 'whoosh' : 'tock');
    CUES.push({ t: +at.toFixed(3), type: cueType, gain: 0.65 });
  });
  return { shots: S, cues: CUES };
}
