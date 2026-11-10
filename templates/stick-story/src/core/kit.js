// Stick Story: the COMPONENT ZOO. Black stick people with eyes that act, flat illustrated rooms, gold step cards.
import { ctx, W, H, TAU, lerp, clamp, rnd, rr, circle, ell, line } from './lib.js';

export const P = {
  wall: '#EFE6D6', wallShade: '#E2D5BE', floor: '#C99F7A', floorDark: '#B48A66', base: '#F7F1E6',
  ink: '#1C1C22', gold: '#F2B23E', goldDark: '#C98A1C', navy: '#22304A', red: '#E2574C', green: '#6DB36A',
  sky: '#A9D3E8', white: '#FFFFFF', wood: '#9C6B48', sofa: '#5E7FA3', sofaDark: '#4C6A8C', rug: '#D9826B', plant: '#6E9E5B',
  // night versions
  nWall: '#2C3348', nWallShade: '#252B3D', nFloor: '#3B3446', nFloorDark: '#322C3C', nSky: '#16213A', lamp: '#FFD98A',
};
export const FLOOR = 1350;                         // where the wall meets the floor in every room
export const GROUND = 1560;                        // where people stand

// ═════════════════════════ STICK PERSON ═════════════════════════
const rad = (d) => d * Math.PI / 180;
function limb(x, y, len1, a1, len2, a2, dir, w) {     // angles in degrees from straight down, + = toward facing dir
  const k = [x + Math.sin(rad(a1)) * len1 * dir, y + Math.cos(rad(a1)) * len1];
  const e = [k[0] + Math.sin(rad(a1 + a2)) * len2 * dir, k[1] + Math.cos(rad(a1 + a2)) * len2];
  line([[x, y], k, e], P.ink, w); return e;
}
/**
 * A stick person standing on (x, y). o = { h (height px, default 520), dir (1 faces right, -1 left), walk (phase, rad: animates
 * legs + arms), arms: { L: [shoulder, elbow], R: [...] } (deg, 0 = down, + = forward), legs: { L: [hip, knee], R: [...] },
 * look: [x, y] pupils -1..1, mood: 'calm' | 'happy' | 'worried' | 'scared' | 'determined' | 'sleepy', lean (deg),
 * hold: (x, y) => draw a prop at the FRONT hand, blink: 0..1, cap: colour of a cap (optional) }
 */
export function person(o) {
  const h = o.h || 520, d = o.dir || 1, w = h * 0.034, wk = o.walk;
  const hipY = o.y - h * 0.46, shY = o.y - h * 0.77, r = h * 0.105;
  ctx.save(); if (o.glow) ctx.filter = `drop-shadow(0px 0px ${Math.round(h * 0.014)}px rgba(255,226,170,0.95))`; ctx.translate(o.x, hipY); ctx.rotate(rad((o.lean || 0) * d)); ctx.translate(-o.x, -hipY);
  const sw = wk != null ? Math.sin(wk) : 0;
  const legs = o.legs || { L: [wk != null ? sw * 26 : 6, wk != null ? Math.max(0, -sw) * 30 + 6 : 4], R: [wk != null ? -sw * 26 : -6, wk != null ? Math.max(0, sw) * 30 + 6 : 4] };
  const arms = o.arms || { L: [wk != null ? -sw * 24 : -8, 12], R: [wk != null ? sw * 24 : 10, 16] };
  // back limbs first
  limb(o.x, hipY, h * 0.25, legs.L[0], h * 0.23, -legs.L[1] * 1.0, d, w);
  limb(o.x, shY + h * 0.02, h * 0.17, arms.L[0], h * 0.16, arms.L[1], d, w);
  line([[o.x, hipY], [o.x, shY]], P.ink, w * 1.15);                                       // spine
  const footR = limb(o.x, hipY, h * 0.25, legs.R[0], h * 0.23, -legs.R[1], d, w);
  const hand = limb(o.x, shY + h * 0.02, h * 0.17, arms.R[0], h * 0.16, arms.R[1], d, w);
  circle(hand[0], hand[1], w * 0.9, P.ink);
  if (o.hold) o.hold(hand[0], hand[1]);
  // head
  const hx = o.x + d * r * 0.08, hy = shY - r * 1.12;
  if (o.cap) { ctx.beginPath(); ctx.arc(hx, hy - r * 0.15, r * 1.04, Math.PI, TAU); ctx.fillStyle = o.cap; ctx.fill(); }
  circle(hx, hy, r, P.ink);
  if (o.cap) { ctx.beginPath(); ctx.arc(hx, hy - r * 0.1, r * 1.03, Math.PI * 1.05, Math.PI * 1.95); ctx.lineWidth = r * 0.32; ctx.strokeStyle = o.cap; ctx.stroke(); rr(hx + d * r * 0.3 - (d < 0 ? r * 0.9 : 0), hy - r * 0.62, r * 0.9, r * 0.2, r * 0.1); ctx.fillStyle = o.cap; ctx.fill(); }
  ctx.filter = 'none'; face(hx + d * r * 0.22, hy, r, d, o);
  ctx.restore();
}
function face(fx, fy, r, d, o) {
  const m = o.mood || 'calm', lk = o.look || [d * 0.3, 0], blink = o.blink || 0;
  const big = m === 'scared' ? 1.22 : 1, ex = r * 0.3, ey = -r * 0.05;
  for (const s of [-1, 1]) {
    const cx = fx + s * ex, cy = fy + ey;
    if (m === 'happy') { ctx.beginPath(); ctx.arc(cx, cy + r * 0.06, r * 0.17, Math.PI * 1.1, Math.PI * 1.9); ctx.strokeStyle = P.white; ctx.lineWidth = r * 0.09; ctx.lineCap = 'round'; ctx.stroke(); continue; }
    const ry = r * 0.3 * big * (1 - blink * 0.92) * (m === 'sleepy' ? 0.45 : 1);
    ell(cx, cy, r * 0.22 * big, Math.max(1, ry), P.white);
    if (blink < 0.6) circle(cx + lk[0] * r * 0.08, cy + lk[1] * r * 0.1 + (m === 'sleepy' ? r * 0.04 : 0), r * (m === 'scared' ? 0.08 : 0.12), P.ink);
  }
  ctx.strokeStyle = P.white; ctx.lineWidth = r * 0.08; ctx.lineCap = 'round';
  if (m === 'worried' || m === 'scared') for (const s of [-1, 1]) { ctx.beginPath(); ctx.moveTo(fx + s * ex - r * 0.2, fy - r * 0.42 + (s > 0 ? -r * 0.08 : 0)); ctx.lineTo(fx + s * ex + r * 0.2, fy - r * 0.42 + (s > 0 ? 0 : -r * 0.08)); ctx.stroke(); }
  if (m === 'determined') for (const s of [-1, 1]) { ctx.beginPath(); ctx.moveTo(fx + s * ex - r * 0.2 * s, fy - r * 0.5); ctx.lineTo(fx + s * ex + r * 0.2 * s, fy - r * 0.38); ctx.stroke(); }
  // mouth
  ctx.beginPath();
  if (m === 'happy') ctx.arc(fx, fy + r * 0.38, r * 0.2, 0.15 * Math.PI, 0.85 * Math.PI);
  else if (m === 'scared') { ell(fx, fy + r * 0.5, r * 0.1, r * 0.13, P.white); return; }
  else if (m === 'worried') { ctx.moveTo(fx - r * 0.14, fy + r * 0.52); ctx.quadraticCurveTo(fx, fy + r * 0.42, fx + r * 0.14, fy + r * 0.52); }
  else { ctx.moveTo(fx - r * 0.12, fy + r * 0.47); ctx.lineTo(fx + r * 0.12, fy + r * 0.47); }
  ctx.stroke();
}
/** a big face close-up (head fills the frame): same face, huge */
export function bigHead(x, y, r, o = {}) { circle(x, y, r, P.ink); face(x + (o.dir || 1) * r * 0.1, y, r, o.dir || 1, o); }

// ═════════════════════════ ROOMS (full 1080x1920 frames) ═════════════════════════
const pal = (night) => night ? { wall: P.nWall, shade: P.nWallShade, floor: P.nFloor, floorD: P.nFloorDark, sky: P.nSky } : { wall: P.wall, shade: P.wallShade, floor: P.floor, floorD: P.floorDark, sky: P.sky };
function shell(night) {
  const c = pal(night);
  ctx.fillStyle = c.wall; ctx.fillRect(-300, -300, W + 600, FLOOR + 300);
  ctx.fillStyle = c.shade; ctx.fillRect(-300, FLOOR - 70, W + 600, 70);
  ctx.fillStyle = night ? '#4A4254' : P.base; ctx.fillRect(-300, FLOOR - 20, W + 600, 20);
  ctx.fillStyle = c.floor; ctx.fillRect(-300, FLOOR, W + 600, H - FLOOR + 300);
  ctx.strokeStyle = c.floorD; ctx.lineWidth = 6; for (let y = FLOOR + 90; y < H + 300; y += 110) { ctx.beginPath(); ctx.moveTo(-300, y); ctx.lineTo(W + 300, y); ctx.stroke(); }
  return c;
}
export function windowPane(x, y, w, h, night) {
  rr(x - 16, y - 16, w + 32, h + 32, 14); ctx.fillStyle = night ? '#4A4254' : P.white; ctx.fill();
  rr(x, y, w, h, 8); ctx.fillStyle = pal(night).sky; ctx.fill();
  if (night) { circle(x + w * 0.7, y + h * 0.3, 40, '#F4EBC8'); for (let i = 0; i < 8; i++) circle(x + rnd(i) * w, y + rnd(i + 4) * h * 0.7, 3, '#F4EBC8'); }
  else { ell(x + w * 0.3, y + h * 0.3, 60, 24, P.white); ell(x + w * 0.38, y + h * 0.26, 40, 26, P.white); }
  ctx.fillStyle = night ? '#4A4254' : P.white; ctx.fillRect(x + w / 2 - 7, y, 14, h); ctx.fillRect(x, y + h / 2 - 7, w, 14);
}
export function couch(x, y, s = 1, night) {
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  rr(-300, -230, 600, 160, 40); ctx.fillStyle = night ? '#3E5070' : P.sofaDark; ctx.fill();
  rr(-330, -120, 660, 120, 30); ctx.fillStyle = night ? '#4A5E82' : P.sofa; ctx.fill();
  rr(-360, -180, 90, 180, 30); ctx.fillStyle = night ? '#3E5070' : P.sofaDark; ctx.fill(); rr(270, -180, 90, 180, 30); ctx.fill();
  ctx.fillStyle = P.ink; ctx.fillRect(-300, 0, 20, 30); ctx.fillRect(280, 0, 20, 30);
  ctx.restore();
}
export function lamp(x, y, on = true, night) {
  if (on && night) { ctx.save(); ctx.globalAlpha = 0.18; ctx.beginPath(); ctx.moveTo(x - 60, y - 400); ctx.lineTo(x + 60, y - 400); ctx.lineTo(x + 260, y); ctx.lineTo(x - 260, y); ctx.closePath(); ctx.fillStyle = P.lamp; ctx.fill(); ctx.restore(); }
  line([[x, y], [x, y - 400]], P.ink, 10); ell(x, y, 60, 12, P.ink);
  ctx.beginPath(); ctx.moveTo(x - 50, y - 400); ctx.lineTo(x + 50, y - 400); ctx.lineTo(x + 80, y - 500); ctx.lineTo(x - 80, y - 500); ctx.closePath(); ctx.fillStyle = on ? P.lamp : '#C9BFA9'; ctx.fill();
}
export function frameArt(x, y, w, h, night) { rr(x, y, w, h, 6); ctx.fillStyle = P.ink; ctx.fill(); rr(x + 12, y + 12, w - 24, h - 24, 3); ctx.fillStyle = night ? '#5A5470' : '#F3C97A'; ctx.fill(); ctx.beginPath(); ctx.moveTo(x + 12, y + h - 12); ctx.lineTo(x + w * 0.4, y + h * 0.45); ctx.lineTo(x + w * 0.6, y + h * 0.65); ctx.lineTo(x + w * 0.75, y + h * 0.5); ctx.lineTo(x + w - 12, y + h - 12); ctx.fillStyle = night ? '#3F3A55' : P.rug; ctx.fill(); }
export function plant(x, y) { for (const [dx, dy, r] of [[-30, -90, -0.5], [0, -120, 0], [30, -90, 0.5], [-15, -150, -0.2], [20, -155, 0.25]]) ell(x + dx, y + dy, 28, 70, P.plant, r); rr(x - 60, y - 40, 120, 130, 16); ctx.fillStyle = P.wood; ctx.fill(); }
export function door(x, y, label, open = 0, night) {
  rr(x - 150, y - 560, 300, 560, [16, 16, 0, 0]); ctx.fillStyle = night ? '#1A1F2C' : '#7A5236'; ctx.fill();
  ctx.save(); ctx.translate(x - 130, 0); ctx.scale(1 - open * 0.75, 1); rr(0, y - 540, 260, 540, [10, 10, 0, 0]); ctx.fillStyle = night ? '#5B4A3E' : '#A8754E'; ctx.fill();
  rr(30, y - 500, 200, 200, 8); ctx.strokeStyle = night ? '#4A3C33' : '#8E6142'; ctx.lineWidth = 8; ctx.stroke(); rr(30, y - 260, 200, 200, 8); ctx.stroke();
  circle(225, y - 270, 14, P.gold); ctx.restore();
  if (label) { rr(x - 50, y - 640, 100, 56, 10); ctx.fillStyle = P.ink; ctx.fill(); ctx.font = '900 34px Inter'; ctx.fillStyle = P.white; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label, x, y - 611); }
}
export function fridge(x, y) { rr(x - 140, y - 620, 280, 620, 24); ctx.fillStyle = '#E9EEF2'; ctx.fill(); ctx.fillStyle = '#C9D2DA'; ctx.fillRect(x - 140, y - 400, 280, 10); rr(x + 90, y - 560, 16, 120, 8); ctx.fillStyle = '#9AA6B2'; ctx.fill(); rr(x + 90, y - 360, 16, 160, 8); ctx.fill(); }
export function counter(x, y, w) { ctx.fillStyle = '#7E5A41'; ctx.fillRect(x, y - 300, w, 300); ctx.fillStyle = '#D9CDBA'; ctx.fillRect(x - 20, y - 330, w + 40, 34); for (let i = 0; i < Math.floor(w / 160); i++) { rr(x + 20 + i * 160, y - 270, 130, 230, 10); ctx.strokeStyle = '#6A4A34'; ctx.lineWidth = 8; ctx.stroke(); circle(x + 85 + i * 160, y - 150, 9, P.gold); } }

/** living room. o = { night, lampOn } */
export function livingRoom(o = {}) { const n = !!o.night; shell(n); windowPane(600, 360, 360, 420, n); frameArt(110, 420, 260, 190, n); lamp(140, FLOOR + 40, o.lampOn ?? true, n); couch(560, FLOOR + 120, 0.95, n); plant(960, FLOOR + 40); rr(170, FLOOR + 230, 760, 70, 35); ctx.fillStyle = n ? '#5B3F4A' : P.rug; ctx.fill(); }
export function kitchen(o = {}) { const n = !!o.night; shell(n); windowPane(470, 380, 300, 320, n); fridge(170, FLOOR + 60); counter(330, FLOOR + 60, 700); }
export function hallway(o = {}) { const n = !!o.night; shell(n); door(270, FLOOR + 40, o.a || '4A', o.openA || 0, n); door(810, FLOOR + 40, o.b || '4B', o.openB || 0, n); ell(540, 120, 120, 26, n ? '#3A3550' : '#D8CDB6'); }

// ═════════════════════════ PROPS ═════════════════════════
export function phone(x, y, s = 1, msg = null) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); rr(-60, -110, 120, 220, 22); ctx.fillStyle = P.ink; ctx.fill(); rr(-50, -96, 100, 180, 12); ctx.fillStyle = msg ? '#DDEBF7' : '#3B4A63'; ctx.fill(); if (msg) { rr(-42, -70, 84, 40, 12); ctx.fillStyle = P.white; ctx.fill(); rr(-30, -18, 72, 40, 12); ctx.fillStyle = '#4A90E2'; ctx.fill(); } ctx.restore(); }
export function bottle(x, y, s = 1) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); rr(-26, -110, 52, 120, 16); ctx.fillStyle = '#9FD3EC'; ctx.fill(); rr(-14, -132, 28, 26, 6); ctx.fillStyle = '#3F7FB5'; ctx.fill(); ctx.fillStyle = '#3F7FB5'; ctx.fillRect(-26, -70, 52, 30); ctx.restore(); }
export function can(x, y, s = 1) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); rr(-36, -90, 72, 100, 10); ctx.fillStyle = '#B8BEC6'; ctx.fill(); ctx.fillStyle = P.red; ctx.fillRect(-36, -70, 72, 56); ctx.fillStyle = P.white; ctx.fillRect(-20, -50, 40, 14); ctx.restore(); }
export function flashlight(x, y, s = 1, on = true, ang = 0) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(ang); ctx.scale(s, s);
  if (on) { ctx.save(); ctx.globalAlpha = 0.28; ctx.beginPath(); ctx.moveTo(60, -20); ctx.lineTo(600, -160); ctx.lineTo(600, 160); ctx.lineTo(60, 20); ctx.closePath(); ctx.fillStyle = P.lamp; ctx.fill(); ctx.restore(); }
  rr(-60, -18, 110, 36, 10); ctx.fillStyle = '#3B4152'; ctx.fill(); rr(40, -26, 30, 52, 6); ctx.fillStyle = '#596075'; ctx.fill(); ctx.restore();
}
export function backpack(x, y, s = 1) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); rr(-80, -180, 160, 190, 40); ctx.fillStyle = '#D9824A'; ctx.fill(); rr(-60, -80, 120, 70, 16); ctx.fillStyle = '#B9683A'; ctx.fill(); ctx.beginPath(); ctx.arc(0, -180, 40, Math.PI, TAU); ctx.lineWidth = 12; ctx.strokeStyle = '#B9683A'; ctx.stroke(); ctx.restore(); }

// ═════════════════════════ GRAPHICS ═════════════════════════
/** gold step card: number disc + label. sc = pop scale */
export function stepCard(n, label, x, y, sc = 1) {
  if (sc <= 0) return; ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc);
  ctx.font = '900 64px Inter'; const tw = ctx.measureText(label).width, w = tw + 230;
  rr(-w / 2 + 8, -82, w, 180, 34); ctx.fillStyle = 'rgba(0,0,0,0.25)'; ctx.fill();
  rr(-w / 2, -90, w, 180, 34); ctx.fillStyle = P.gold; ctx.fill();
  circle(-w / 2 + 95, 0, 62, P.navy); ctx.fillStyle = P.gold; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = '900 80px Inter'; ctx.fillText(String(n), -w / 2 + 95, 4);
  ctx.fillStyle = P.navy; ctx.font = '900 64px Inter'; ctx.textAlign = 'left'; ctx.fillText(label, -w / 2 + 180, 4);
  ctx.restore();
}
export function check(x, y, s = 1) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); circle(0, 0, 70, P.green); ctx.beginPath(); ctx.moveTo(-32, 2); ctx.lineTo(-8, 28); ctx.lineTo(36, -24); ctx.strokeStyle = P.white; ctx.lineWidth = 18; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke(); ctx.restore(); }
export function cross(x, y, s = 1) { ctx.save(); ctx.translate(x, y); ctx.scale(s, s); circle(0, 0, 70, P.red); ctx.beginPath(); ctx.moveTo(-28, -28); ctx.lineTo(28, 28); ctx.moveTo(28, -28); ctx.lineTo(-28, 28); ctx.strokeStyle = P.white; ctx.lineWidth = 18; ctx.lineCap = 'round'; ctx.stroke(); ctx.restore(); }
export function counterPill(text, x, y, sc = 1) { if (sc <= 0) return; ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc); ctx.font = '900 54px Inter'; const w = ctx.measureText(text).width + 70; rr(-w / 2, -45, w, 90, 45); ctx.fillStyle = P.navy; ctx.fill(); ctx.fillStyle = P.gold; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, 0, 3); ctx.restore(); }
/** thought bubble at (x, y) with an icon drawn inside by inner(x, y) */
export function thought(x, y, s, inner, tx, ty) {
  ctx.save(); circle(tx, ty, 14 * s, P.white); circle(lerp(tx, x, 0.45), lerp(ty, y, 0.45) + 20 * s, 22 * s, P.white);
  ctx.translate(x, y); ctx.scale(s, s); for (const [dx, dy, r] of [[-90, 10, 80], [0, -30, 100], [95, 5, 85], [0, 45, 90]]) circle(dx, dy, r, P.white);
  ctx.restore(); if (inner) inner(x, y);
}
/** cinema bars for dramatic beats (a 0..1) */
export function cinemaBars(a) { if (a <= 0) return; const h = 170 * a; ctx.fillStyle = P.ink; ctx.fillRect(-300, -300, W + 600, h + 300); ctx.fillRect(-300, H - h, W + 600, h + 300); }

// ═════════════════════════ CAPTION LOOK (used by captions.js and the sheet) ═════════════════════════
export const CAPLOOK = { font: '800 92px Inter', y: 1690, maxW: 920, fg: P.white, hi: P.gold, box: 'rgba(28,28,34,0.86)' };
/** draw one caption: words [{txt, hi}] centred at (x, y) on a dark rounded bar */
export function captionBar(words, x, y, sc = 1, look = CAPLOOK) {
  ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc); ctx.font = look.font; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  const sp = 26, ws = words.map((w) => ctx.measureText(w.txt).width), tw = ws.reduce((a, b) => a + b, 0) + sp * (words.length - 1);
  const fit = Math.min(1, (look.maxW || 960) / (tw + 80)); ctx.scale(fit, fit);
  rr(-tw / 2 - 40, -72, tw + 80, 144, 30); ctx.fillStyle = look.box; ctx.fill();
  let cx = -tw / 2; words.forEach((w, i) => { ctx.fillStyle = w.hi ? look.hi : look.fg; ctx.fillText(w.txt, cx, 4); cx += ws[i] + sp; });
  ctx.restore();
}
