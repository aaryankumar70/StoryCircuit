// WHAT IF THE POWER WENT OUT FOR 3 DAYS? : the shot list (Stick Story example).
// One picture per clause. A shot: { id, at, cam: [cx, cy], zoom, note, draw(lt, d, t) }. cut(i) = just before line i,
// Wd('word', i) = when the word is said. Sound: cue(t, type, { gain, dur }).
import { ctx, W, H, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line } from './core/lib.js';
import { L, Wd, T } from './core/timing.js';
import * as K from './core/kit.js';
const { P, GROUND } = K;

// small set pieces for this story
function tv(x, y, on) { rr(x - 170, y - 230, 340, 210, 16); ctx.fillStyle = P.ink; ctx.fill(); rr(x - 150, y - 212, 300, 174, 8); ctx.fillStyle = on ? '#7FB8E6' : '#2E3445'; ctx.fill(); rr(x - 120, y - 20, 240, 30, 8); ctx.fillStyle = '#6B4A34'; ctx.fill(); ctx.fillStyle = '#6B4A34'; ctx.fillRect(x - 110, y + 10, 20, 120); ctx.fillRect(x + 90, y + 10, 20, 120); }
function plug(x, y, inWall) { line([[x - 300, y + 40], [x - 120, y + 60], [x - 10, y + 10]], P.ink, 10); rr(x - 20, y - 22, inWall ? 40 : 56, 44, 8); ctx.fillStyle = '#E8E3D8'; ctx.fill(); ctx.strokeStyle = P.ink; ctx.lineWidth = 5; ctx.stroke(); if (!inWall) { line([[x + 36, y - 10], [x + 56, y - 10]], '#B8A36A', 7); line([[x + 36, y + 10], [x + 56, y + 10]], '#B8A36A', 7); } }
function socket(x, y) { rr(x - 50, y - 70, 100, 140, 14); ctx.fillStyle = '#F7F1E6'; ctx.fill(); ctx.strokeStyle = '#C9BFA9'; ctx.lineWidth = 5; ctx.stroke(); for (const dy of [-28, 28]) { circle(x, dy + y, 20, '#C9BFA9'); ctx.fillStyle = P.ink; ctx.fillRect(x - 8, y + dy - 8, 5, 14); ctx.fillRect(x + 3, y + dy - 8, 5, 14); } }
function candle(x, y, s, t) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); rr(-26, -140, 52, 150, 10); ctx.fillStyle = '#F4EEDC'; ctx.fill(); line([[0, -140], [0, -158]], P.ink, 5); const f = 1 + Math.sin(t * 20) * 0.08; ell(0, -190, 20 * f, 38 * f, '#F2B23E'); ell(0, -182, 10, 20, '#FFF3C4'); ctx.restore(); }
function curtain(x, y, h, wave) { ctx.beginPath(); ctx.moveTo(x, y); for (let k = 0; k <= 10; k++) ctx.lineTo(x + 200 + Math.sin(k + wave) * 18, y + h * k / 10); ctx.lineTo(x, y + h); ctx.closePath(); ctx.fillStyle = '#C96B5B'; ctx.fill(); }
function bolt(x, y, s) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); ctx.beginPath(); ctx.moveTo(10, -120); ctx.lineTo(-50, 10); ctx.lineTo(0, 10); ctx.lineTo(-20, 120); ctx.lineTo(60, -20); ctx.lineTo(10, -20); ctx.closePath(); ctx.fillStyle = '#FFD43B'; ctx.fill(); ctx.lineWidth = 8; ctx.strokeStyle = P.ink; ctx.stroke(); ctx.restore(); }

export function buildShots() {
  const S = [], CUES = [], add = (o) => (S.push(o), o), cue = (t, type, o = {}) => CUES.push({ t: +t.toFixed(3), type, ...o });
  const cut = (i) => (i === 0 ? 0 : L(i) - 0.08);
  const blink = (t) => ((t % 3.1) < 0.12 ? 1 : 0);

  // 1 · a normal evening, phone in hand
  add({ id: 'S01', at: 0, cam: [540, 1100], note: 'evening, hero scrolls phone, looks up', draw(lt, d, t) {
    K.livingRoom({ night: true, lampOn: true });
    const up = lt > d * 0.6;
    K.person({ glow: true, x: 520, y: GROUND, h: 840, mood: up ? 'worried' : 'calm', look: up ? [0.2, -1] : [0.6, 0.6], blink: blink(t), arms: { L: [-6, 14], R: [60, 60] }, hold: (x, y) => K.phone(x + 12, y - 40, 0.55, true) });
    if (up) K.thought(800, 560, 0.9 * eob(seg(lt, d * 0.6, d * 0.6 + 0.25)), () => bolt(800, 545, 0.75), 640, 760);
  } });
  cue(0.2, 'pop', { gain: 0.5 });

  // 2 · nine at night … everything goes dark
  { const st = cut(1), dark = Wd('dark', 1) - st;
    add({ id: 'S02', at: st, cam: [540, 1000], zoom: 0.1, note: 'lamp on, then BLACKOUT on "dark"', draw(lt, d, t) {
      const off = lt > dark;
      K.livingRoom({ night: true, lampOn: !off });
      if (off) { ctx.fillStyle = 'rgba(5,8,18,0.62)'; ctx.fillRect(-300, -300, W + 600, H + 600); }
      K.person({ glow: true, x: 520, y: GROUND, h: 840, mood: off ? 'scared' : 'calm', look: off ? [Math.sin(lt * 4), -0.3] : [0.5, 0], blink: off ? 0 : blink(t), arms: off ? { L: [-30, 40], R: [-30, 40] } : undefined });
      K.counterPill('9:00 P.M.', 540, 300, eob(seg(lt, 0, 0.25)));
      K.cinemaBars(off ? eo(seg(lt, dark, dark + 0.3)) : 0);
    } });
    cue(st, 'whoosh'); cue(st + dark, 'thud'); cue(st + dark + 0.05, 'whoosh', { gain: 0.6 }); }

  // 3 · step one: don't touch the fridge
  { const st = cut(2), fr = Wd('fridge', 2) - st;
    add({ id: 'S03', at: st, cam: [400, 1100], note: 'kitchen, hand stops before the fridge', draw(lt, d, t) {
      K.kitchen({ night: true }); ctx.fillStyle = 'rgba(5,8,18,0.35)'; ctx.fillRect(-300, -300, W + 600, H + 600);
      const reach = eio(seg(lt, 0.1, fr)), stop = lt > fr;
      K.person({ glow: true, x: 560, y: GROUND, h: 840, dir: -1, mood: stop ? 'determined' : 'calm', look: [-1, 0], arms: { L: [-6, 12], R: [lerp(10, stop ? 40 : 75, reach), 10] }, blink: blink(t) });
      if (stop) K.cross(260, 760, eob(seg(lt, fr, fr + 0.25)));
      K.stepCard(1, "DON'T OPEN IT", 540, 300, eob(seg(lt, 0.05, 0.3)));
    } });
    cue(st, 'whoosh'); cue(st + 0.05, 'pop'); cue(st + fr, 'boing', { gain: 0.5 }); }

  // 4 · closed fridge = 4 hours, full freezer = 2 days
  { const st = cut(3), h4 = Wd('four', 3) - st, fz = Wd('freezer', 3) - st;
    add({ id: 'S04', at: st, cam: [300, 1050], zoom: 0.08, note: 'fridge with 4 HOURS and 2 DAYS timers', draw(lt, d, t) {
      K.kitchen({ night: true }); ctx.fillStyle = 'rgba(5,8,18,0.35)'; ctx.fillRect(-300, -300, W + 600, H + 600);
      K.person({ glow: true, x: 640, y: GROUND, h: 840, dir: -1, mood: lt > fz ? 'happy' : 'calm', look: [-1, -0.5], blink: blink(t) });
      K.counterPill('FRIDGE: 4 HOURS', 330, 560, lt > h4 ? eob(seg(lt, h4, h4 + 0.25)) : 0);
      K.counterPill('FREEZER: 2 DAYS', 330, 430, lt > fz ? eob(seg(lt, fz, fz + 0.25)) : 0);
      if (lt > fz + 0.5) K.check(170, 900, eob(seg(lt, fz + 0.5, fz + 0.75)));
    } });
    cue(st, 'whoosh'); cue(st + h4, 'pop'); cue(st + fz, 'pop'); cue(st + fz + 0.5, 'sparkle', { dur: 0.6 }); }

  // 5 · step two: flashlight, not a candle
  { const st = cut(4), fl = Wd('flashlight', 4) - st, ca = Wd('candle', 4) - st;
    add({ id: 'S05', at: st, cam: [540, 1100], note: 'flashlight beam on; candle gets a red X', draw(lt, d, t) {
      K.livingRoom({ night: true, lampOn: false }); ctx.fillStyle = 'rgba(5,8,18,0.5)'; ctx.fillRect(-300, -300, W + 600, H + 600);
      const on = lt > fl;
      K.person({ glow: true, x: 420, y: GROUND, h: 840, mood: 'determined', look: [1, 0], arms: { L: [-6, 14], R: [80, 10] }, hold: (x, y) => K.flashlight(x + 10, y, 1.2, on, -0.05) });
      K.stepCard(2, 'FLASHLIGHT', 540, 300, eob(seg(lt, 0.05, 0.3)));
      if (lt > ca) { candle(860, 1250, 1, t); K.cross(860, 1020, eob(seg(lt, ca, ca + 0.25)) * 0.9); }
    } });
    cue(st, 'whoosh'); cue(st + 0.05, 'pop'); cue(st + fl, 'tock'); cue(st + ca, 'boing', { gain: 0.5 }); }

  // 6 · candles are a real fire risk (close-up: candle by a curtain)
  { const st = cut(5);
    add({ id: 'S06', at: st, cam: [540, 1000], zoom: 0.14, note: 'candle flame licks toward the curtain', draw(lt, d, t) {
      ctx.fillStyle = P.nWall; ctx.fillRect(-300, -300, W + 600, H + 600); curtain(380, 200, 1150, t * 2);
      ctx.fillStyle = '#5C4636'; ctx.fillRect(-300, 1380, W + 600, 700);
      candle(560, 1380, 1.6, t); const glow = ctx.createRadialGradient(560, 1070, 10, 560, 1070, 420); glow.addColorStop(0, 'rgba(242,178,62,0.35)'); glow.addColorStop(1, 'rgba(242,178,62,0)'); ctx.fillStyle = glow; ctx.fillRect(0, 600, W, 900);
      K.counterPill('FIRE RISK', 540, 330, eob(seg(lt, 0.2, 0.45)));
    } });
    cue(st, 'whoosh'); cue(st + 0.2, 'alarm', { dur: 1.2, gain: 0.6 }); }

  // 7 · step three: fill bottles with water
  { const st = cut(6), wt = Wd('water', 6) - st;
    add({ id: 'S07', at: st, cam: [540, 1100], note: 'bottles pop onto the counter one by one', draw(lt, d, t) {
      K.kitchen({ night: true }); ctx.fillStyle = 'rgba(5,8,18,0.3)'; ctx.fillRect(-300, -300, W + 600, H + 600);
      K.person({ glow: true, x: 230, y: GROUND, h: 840, mood: 'happy', look: [1, 0], blink: blink(t) });
      for (let i = 0; i < 6; i++) { const p = seg(lt, 0.3 + i * 0.22, 0.5 + i * 0.22); if (p > 0) K.bottle(470 + i * 95, 1060, eob(p) * 1.05); }
      K.stepCard(3, 'STORE WATER', 540, 300, eob(seg(lt, 0.05, 0.3)));
    } });
    cue(st, 'whoosh'); cue(st + 0.05, 'pop'); for (let i = 0; i < 6; i++) cue(st + 0.32 + i * 0.22, 'plop', { gain: 0.45 }); }

  // 8 · a gallon per person, per day
  { const st = cut(7);
    add({ id: 'S08', at: st, cam: [540, 1000], zoom: 0.1, note: 'big rule card: 1 gallon / person / day', draw(lt, d, t) {
      ctx.fillStyle = P.wall; ctx.fillRect(-300, -300, W + 600, H + 600);
      K.counterPill('1 GALLON', 540, 520, eob(seg(lt, 0.1, 0.35)) * 1.5);
      K.counterPill('PER PERSON', 540, 720, eob(seg(lt, 0.5, 0.75)) * 1.2);
      K.counterPill('EVERY DAY', 540, 890, eob(seg(lt, 0.9, 1.15)) * 1.2);
      K.person({ x: 280, y: 1560, h: 660, mood: 'happy', look: [1, -0.5] }); K.person({ x: 800, y: 1560, h: 600, mood: 'happy', dir: -1, look: [-1, -0.5], cap: '#E2574C' });
      for (let i = 0; i < 2; i++) K.bottle(450 + i * 180, 1550, 1.3);
    } });
    cue(st + 0.1, 'pop'); cue(st + 0.5, 'pop'); cue(st + 0.9, 'pop'); }

  // 9 · step four: unplug your electronics
  { const st = cut(8), un = Wd('unplug', 8) - st;
    add({ id: 'S09', at: st, cam: [600, 1200], note: 'hero pulls the TV plug from the socket', draw(lt, d, t) {
      K.livingRoom({ night: true, lampOn: false }); ctx.fillStyle = 'rgba(5,8,18,0.4)'; ctx.fillRect(-300, -300, W + 600, H + 600);
      tv(800, 1250, false); socket(560, 1380);
      const pulled = eio(seg(lt, un, un + 0.4));
      plug(560 - pulled * 90, 1380, pulled < 0.1);
      K.person({ glow: true, x: 330, y: GROUND, h: 840, mood: 'determined', look: [1, 0.8], lean: 18, arms: { L: [-6, 14], R: [lerp(60, 50, pulled), 0] } });
      K.stepCard(4, 'UNPLUG IT', 540, 300, eob(seg(lt, 0.05, 0.3)));
    } });
    cue(st, 'whoosh'); cue(st + 0.05, 'pop'); cue(st + un + 0.1, 'pop', { gain: 0.7 }); }

  // 10 · a surge can fry them
  { const st = cut(9), sg = Wd('surge', 9) - st;
    add({ id: 'S10', at: st, cam: [540, 1100], zoom: 0.12, note: 'power returns: zap on the TV', draw(lt, d, t) {
      K.livingRoom({ night: true, lampOn: lt > sg }); ctx.fillStyle = 'rgba(5,8,18,0.35)'; ctx.fillRect(-300, -300, W + 600, H + 600);
      tv(560, 1350, false); socket(880, 1380); plug(880, 1380, true);
      if (lt > sg) { const p = seg(lt, sg, sg + 0.6); bolt(560, 1050, eob(clamp(p * 2)) * 1.3); if (Math.floor(lt * 14) % 2 === 0) { ctx.fillStyle = 'rgba(255,240,180,0.25)'; ctx.fillRect(0, 0, W, H); } K.cross(800, 860, eob(seg(lt, sg + 0.3, sg + 0.55)) * 0.8); }
    } });
    cue(st, 'whoosh'); cue(st + sg, 'zip'); cue(st + sg + 0.05, 'slam', { gain: 0.6 }); }

  // 11 · day three: lights flicker back on
  { const st = cut(10), on = Wd('flicker', 10) - st;
    add({ id: 'S11', at: st, cam: [540, 1050], note: 'DAY 3 card, lamp flickers back on', draw(lt, d, t) {
      const flick = lt > on && (lt > on + 0.8 || Math.floor(lt * 12) % 2 === 0);
      K.livingRoom({ night: true, lampOn: flick }); if (!flick) { ctx.fillStyle = 'rgba(5,8,18,0.55)'; ctx.fillRect(-300, -300, W + 600, H + 600); }
      K.person({ glow: true, x: 520, y: GROUND, h: 840, mood: flick ? 'happy' : 'sleepy', look: [-0.6, -0.8], blink: 0, arms: flick ? { L: [150, 10], R: [150, 10] } : undefined });
      K.counterPill('DAY 3', 540, 300, eob(seg(lt, 0, 0.25)));
    } });
    cue(st, 'whoosh'); cue(st + on, 'tock'); cue(st + on + 0.2, 'tock'); cue(st + on + 0.8, 'sparkle', { dur: 0.8 }); }

  // 12 · because you were ready, you're totally fine
  { const st = cut(11), fine = Wd('fine', 11) - st;
    add({ id: 'S12', at: st, cam: [540, 1000], zoom: 0.1, note: 'daylight, hero relaxed, big check', draw(lt, d, t) {
      K.livingRoom({}); K.person({ x: 480, y: GROUND, h: 860, mood: 'happy', look: [0, 0], blink: blink(t), arms: { L: [-20, 30], R: [130, 60] } });
      K.check(820, 700, lt > fine - 0.3 ? eob(seg(lt, fine - 0.3, fine)) * 1.3 : 0);
    } });
    cue(st, 'whoosh'); cue(st + fine - 0.3, 'sparkle', { dur: 1 }); }

  return { shots: S, cues: CUES };
}
