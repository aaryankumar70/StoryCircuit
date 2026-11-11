// Stick Story: Dynamic Illustrated Narrative Scene Choreographer.
// Supports tech/space/survival/science storytelling within y=250..1180 strictly clear of y=1400 captions.
import { ctx, W, H, TAU, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line } from './lib.js';
import { L } from './timing.js';
import * as K from './kit.js';

const { P } = K;

function drawStoryScene(vt, lt, d, t, sc, idx, total) {
  const blink = (t % 3.4) < 0.12 ? 1 : 0;
  const mood = sc.mood || 'mystery';
  const isNight = mood === 'urgent' || mood === 'tense' || mood === 'mystery';

  if (vt === 'cosmic_burst' || vt === 'meter_surge') {
    K.livingRoom({ night: true, lampOn: false });
    ctx.fillStyle = 'rgba(8, 12, 24, 0.72)'; ctx.fillRect(-300, -300, W + 600, H + 600);
    // Glowing celestial / electrical arc waves in upper half
    const sunY = 660;
    circle(540, sunY, 130, '#FFB703');
    for (let k = 0; k < 5; k++) {
      const ph = (t * 0.9 + k * 0.2) % 1;
      ctx.strokeStyle = `rgba(255, 212, 59, ${0.75 * (1 - ph)})`; ctx.lineWidth = 8;
      ctx.beginPath(); ctx.arc(540, sunY, 145 + ph * 260, 0, TAU); ctx.stroke();
    }
    K.person({ glow: true, x: 540, y: 1160, h: 460, mood: 'scared', look: [0, -0.7], blink: 0, arms: { L: [-35, 35], R: [-35, 35] } });
  } else if (vt === 'radar_scan' || vt === 'neural_pulse') {
    K.livingRoom({ night: true, lampOn: true });
    ctx.fillStyle = 'rgba(10, 16, 30, 0.55)'; ctx.fillRect(-300, -300, W + 600, H + 600);
    const cy = 740;
    for (let r = 80; r <= 270; r += 65) {
      ctx.strokeStyle = 'rgba(127, 184, 230, 0.32)'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(540, cy, r, 0, TAU); ctx.stroke();
    }
    const ang = (t * 2.4) % TAU;
    line([[540, cy], [540 + Math.cos(ang) * 260, cy + Math.sin(ang) * 260]], '#FFD43B', 6);
    K.person({ glow: true, x: 260, y: 1160, h: 460, mood: 'determined', look: [0.8, -0.3], blink });
  } else if (vt === 'ocean_depth' || vt === 'micro_stream') {
    ctx.fillStyle = '#0D2636'; ctx.fillRect(-300, -300, W + 600, H + 600);
    for (let i = 0; i < 4; i++) {
      const yy = 600 + i * 120;
      ctx.strokeStyle = 'rgba(127, 184, 230, 0.35)'; ctx.lineWidth = 8;
      ctx.beginPath();
      for (let x = -100; x <= W + 100; x += 40) {
        const y = yy + Math.sin(x * 0.015 + t * 3 + i) * 22;
        x === -100 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    K.person({ glow: true, x: 540, y: 1140, h: 440, mood: 'determined', look: [0.6, -0.2], blink });
  } else if (vt === 'split_compare' || vt === 'vault_mystery') {
    K.livingRoom({ night: isNight, lampOn: !isNight });
    if (isNight) { ctx.fillStyle = 'rgba(8, 12, 24, 0.42)'; ctx.fillRect(-300, -300, W + 600, H + 600); }
    const p = eob(seg(lt, 0.15, 0.5));
    K.person({ x: 350, y: 1160, h: 460, mood: 'worried', dir: 1, look: [0.6, -0.2], blink });
    K.person({ x: 750, y: 1160, h: 460, mood: 'determined', dir: -1, look: [-0.6, -0.2], blink, cap: '#E2574C' });
    K.check(750, 740, p * 0.9);
  } else if (vt === 'payoff_reveal') {
    K.livingRoom({});
    K.person({ x: 500, y: 1160, h: 480, mood: 'happy', look: [0, 0], blink, arms: { L: [-20, 30], R: [130, 60] } });
    K.check(790, 740, eob(seg(lt, 0.2, 0.55)) * 1.15);
  } else {
    // archive_map / timeline / tension_room
    K.livingRoom({ night: isNight, lampOn: !isNight });
    if (isNight) { ctx.fillStyle = 'rgba(8, 12, 24, 0.45)'; ctx.fillRect(-300, -300, W + 600, H + 600); }
    K.person({ glow: isNight, x: 460, y: 1160, h: 480, mood: mood === 'urgent' ? 'scared' : 'calm', look: [0.4, -0.3], blink });
    K.thought(780, 690, 0.85 * eob(seg(lt, 0.25, 0.6)), () => circle(780, 675, 42, P.gold), 600, 840);
  }

  // Chapter & sublabel pills strictly inside safe zone (y=250..420)
  const scPop = eob(seg(lt, 0.08, 0.35));
  if (sc.headline) {
    K.counterPill(String(sc.headline).toUpperCase().slice(0, 26), 540, 318, scPop * 0.86);
  }
  if (sc.sublabel) {
    K.counterPill(String(sc.sublabel).toUpperCase().slice(0, 28), 540, 412, eob(seg(lt, 0.22, 0.5)) * 0.68);
  }
  const bw = 640, bx = (W - bw) / 2;
  ctx.fillStyle = 'rgba(255,255,255,0.16)'; rr(bx, 246, bw, 5, 3); ctx.fill();
  ctx.fillStyle = P.gold; rr(bx, 246, Math.max(12, bw * ((idx + clamp(lt / Math.max(0.2, d))) / Math.max(1, total))), 5, 3); ctx.fill();
}

export function buildDynamicStoryShots(script) {
  const S = [], CUES = [];
  const lines = Array.isArray(script?.lines) ? script.lines : [];
  const total = lines.length;
  lines.forEach((ln, i) => {
    const at = i === 0 ? 0 : Math.max(0, L(i) - 0.08);
    const sc = ln.scene || {};
    const vt = sc.visual_type || 'tension_room';
    const zoom = (sc.mood === 'urgent' || sc.mood === 'tense') ? 0.11 : 0.06;
    S.push({
      id: `S${String(i + 1).padStart(2, '0')}`,
      at,
      cam: [540, 860],
      zoom,
      note: `${vt}: ${sc.headline || ln.text.slice(0, 40)}`,
      draw(lt, d, t) {
        drawStoryScene(vt, lt, d, t, sc, i, total);
      },
    });
    const cueType = sc.cue || (i === total - 1 ? 'sparkle' : i === 0 ? 'whoosh' : 'pop');
    CUES.push({ t: +at.toFixed(3), type: cueType, gain: 0.65 });
  });
  return { shots: S, cues: CUES };
}
