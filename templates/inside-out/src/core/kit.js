// Inside Out engine: the COMPONENT ZOO. Every reusable thing on screen lives here.
// All functions draw immediately with the shared ctx, in 1080x1920 canvas pixels unless a scale is given.
import { ctx, C, W, H, TAU, lerp, clamp, rnd, rr, circle, ell, line, fillAll } from './lib.js';

// ═════════════════════════ PROPS ═════════════════════════
/** a piece of gum (pill shape). s = scale (1 = 80x52 px) */
export function gum(x, y, s, rot = 0, sx = 1, sy = 1) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(s * sx, s * sy);
  rr(-40, -26, 80, 52, 24); ctx.fillStyle = C.gum; ctx.fill(); ctx.lineWidth = 5; ctx.strokeStyle = C.gumEdge; ctx.stroke();
  ell(-14, -11, 14, 6, C.white, -0.3);
  circle(14, 8, 4, '#E2DCD0'); circle(24, -4, 3, '#E2DCD0'); circle(-4, 10, 3, '#E2DCD0');
  ctx.restore();
}

/** the J-shaped stomach (flat, pink, highlight). s = scale; pulse 0..1 swells it */
function stomachPath() {
  ctx.beginPath(); ctx.moveTo(-30, -110);
  ctx.bezierCurveTo(-30, -40, -120, -20, -100, 50);
  ctx.bezierCurveTo(-80, 120, 40, 120, 90, 60);
  ctx.bezierCurveTo(120, 25, 110, -10, 95, -20);
}
export function stomach(x, y, s, pulse = 0) {
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  stomachPath(); ctx.strokeStyle = C.pinkDark; ctx.lineWidth = 92 + pulse * 14; ctx.stroke();
  stomachPath(); ctx.strokeStyle = C.pink; ctx.lineWidth = 80 + pulse * 14; ctx.stroke();
  ctx.save(); ctx.translate(-8, -8); stomachPath(); ctx.strokeStyle = C.pinkLight; ctx.globalAlpha = 0.7; ctx.lineWidth = 22; ctx.stroke(); ctx.restore();
  ctx.restore();
}
/** the stomach's top opening in local units (where the esophagus joins), for a stomach drawn at (x, y, s) */
export const stomachTop = (x, y, s) => [x - 30 * s, y - 110 * s];

/** flat heart icon. beat 0..1 scales it up */
export function heart(x, y, s, beat = 0) {
  ctx.save(); ctx.translate(x, y); ctx.scale(s * (1 + beat * 0.12), s * (1 + beat * 0.12));
  const p = () => { ctx.beginPath(); ctx.moveTo(0, 70); ctx.bezierCurveTo(-150, -20, -90, -130, 0, -60); ctx.bezierCurveTo(90, -130, 150, -20, 0, 70); };
  p(); ctx.fillStyle = C.pinkDark; ctx.fill(); ctx.save(); ctx.translate(-6, -6); ctx.scale(0.92, 0.92); p(); ctx.fillStyle = C.red; ctx.fill(); ctx.restore();
  ell(-48, -52, 22, 12, C.pinkLight, -0.6);
  ctx.restore();
}

/** stopwatch. ang = hand angle in radians */
export function stopwatch(x, y, s, ang) {
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  rr(-40, -330, 80, 60, 14); ctx.fillStyle = C.watch; ctx.fill();
  ctx.save(); ctx.rotate(0.75); rr(-22, -300, 44, 46, 10); ctx.fill(); ctx.restore();
  circle(0, 0, 280, C.watch); circle(0, 0, 240, C.white);
  for (let i = 0; i < 12; i++) { ctx.save(); ctx.rotate(i * Math.PI / 6); rr(-6, -226, 12, i % 3 === 0 ? 44 : 26, 6); ctx.fillStyle = C.watch; ctx.fill(); ctx.restore(); }
  ctx.save(); ctx.rotate(ang); rr(-9, -200, 18, 220, 9); ctx.fillStyle = C.red; ctx.fill(); ctx.restore();
  circle(0, 0, 24, C.watch);
  ctx.restore();
}

/** tear-off calendar card: big number + word under it. Card is 600x680 at s = 1 */
export function calendar(x, y, s, big, small, rot = 0) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(s, s);
  rr(-300, -340, 600, 680, 46); ctx.fillStyle = C.white; ctx.fill(); ctx.lineWidth = 10; ctx.strokeStyle = C.ink; ctx.stroke();
  rr(-300, -340, 600, 170, [46, 46, 0, 0]); ctx.fillStyle = C.red; ctx.fill(); ctx.lineWidth = 10; ctx.stroke();
  for (const bx of [-150, 150]) { rr(bx - 18, -390, 36, 100, 18); ctx.fillStyle = C.ink; ctx.fill(); }
  ctx.fillStyle = C.ink; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.font = '900 330px Inter'; ctx.fillText(big, 0, 170);
  ctx.font = '900 92px Inter'; ctx.letterSpacing = '4px'; ctx.fillText(small, 0, 285); ctx.letterSpacing = '0px';
  ctx.restore();
}

// ═════════════════════════ GRAPHICS ═════════════════════════
/** dark rounded label ("GUM BASE"). sc animates the pop */
export function pill(text, x, y, size, bg = C.ink, fg = C.white, sc = 1) {
  if (sc <= 0) return;
  ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc);
  ctx.font = `900 ${size}px Inter`; ctx.letterSpacing = '2px';
  const w = ctx.measureText(text).width + size * 1.1, h = size * 1.6;
  rr(-w / 2, -h / 2, w, h, h / 2); ctx.fillStyle = bg; ctx.fill();
  ctx.fillStyle = fg; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, 0, size * 0.05);
  ctx.letterSpacing = '0px'; ctx.restore();
}
/** label with a pointer line down to a target point */
export function tag(text, x, y, tx, ty, size = 60, sc = 1) {
  if (sc <= 0) return;
  ctx.save(); ctx.globalAlpha = clamp(sc); line([[x, y], [tx, ty]], C.ink, 8); ctx.restore();
  pill(text, x, y, size, C.ink, C.white, sc);
}
/** the danger X (red, ink outline). a = alpha */
export function redX(x, y, s, a = 1) {
  if (a <= 0) return;
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s); ctx.globalAlpha = a; ctx.lineCap = 'round';
  for (const [w, c] of [[96, C.ink], [72, C.red]]) { ctx.strokeStyle = c; ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(-230, -230); ctx.lineTo(230, 230); ctx.moveTo(230, -230); ctx.lineTo(-230, 230); ctx.stroke(); }
  ctx.restore();
}
/** flat red arrow pointing along ang (radians). len in px */
export function arrow(x, y, len, ang = 0, a = 1) {
  if (a <= 0) return;
  ctx.save(); ctx.translate(x, y); ctx.rotate(ang); ctx.globalAlpha = a;
  ctx.beginPath(); ctx.moveTo(-len / 2, -28); ctx.lineTo(len / 2 - 110, -28); ctx.lineTo(len / 2 - 110, -80); ctx.lineTo(len / 2, 0);
  ctx.lineTo(len / 2 - 110, 80); ctx.lineTo(len / 2 - 110, 28); ctx.lineTo(-len / 2, 28); ctx.closePath(); ctx.fillStyle = C.red; ctx.fill();
  ctx.restore();
}
/** red warning triangle with "!" */
export function warning(x, y, s) {
  if (s <= 0) return;
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  ctx.beginPath(); ctx.moveTo(0, -130); ctx.lineTo(140, 110); ctx.lineTo(-140, 110); ctx.closePath();
  ctx.lineJoin = 'round'; ctx.lineWidth = 40; ctx.strokeStyle = C.red; ctx.stroke(); ctx.fillStyle = C.red; ctx.fill();
  rr(-14, -60, 28, 110, 14); ctx.fillStyle = C.white; ctx.fill(); circle(0, 82, 17, C.white);
  ctx.restore();
}
/** "enzyme" chomper: pink pac-man. open = mouth angle (rad), flip = face left */
export function chomper(x, y, r, open, flip) {
  ctx.save(); ctx.translate(x, y); if (flip) ctx.scale(-1, 1);
  ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, r, open, TAU - open); ctx.closePath(); ctx.fillStyle = C.pink; ctx.fill();
  ctx.lineWidth = 6; ctx.strokeStyle = C.pinkDark; ctx.stroke(); circle(r * 0.15, -r * 0.5, r * 0.13, C.ink);
  ctx.restore();
}
/** impact burst (yellow rays) */
export function burst(x, y, s, a) {
  if (a <= 0) return;
  ctx.save(); ctx.translate(x, y); ctx.globalAlpha = a; ctx.strokeStyle = C.yellow; ctx.lineCap = 'round'; ctx.lineWidth = 12;
  for (let i = 0; i < 8; i++) { const an = i * Math.PI / 4; ctx.beginPath(); ctx.moveTo(Math.cos(an) * 30 * s, Math.sin(an) * 30 * s); ctx.lineTo(Math.cos(an) * 80 * s, Math.sin(an) * 80 * s); ctx.stroke(); }
  ctx.restore();
}
/** horizontal speed lines trailing left of (x, y) */
export function speedLines(x, y, a) {
  if (a <= 0) return;
  ctx.save(); ctx.globalAlpha = a; for (let i = 0; i < 5; i++) line([[x - 80 - i * 20, y - 60 + i * 30], [x - 260 - i * 40, y - 60 + i * 30]], C.ink, 10); ctx.restore();
}
/** three "shock" strokes around a point (head reaction) */
export function shockLines(x, y, r, a) {
  if (a <= 0) return;
  ctx.save(); ctx.globalAlpha = a;
  for (const an of [-2.4, -Math.PI / 2, -0.75]) line([[x + Math.cos(an) * r, y + Math.sin(an) * r], [x + Math.cos(an) * (r + 70), y + Math.sin(an) * (r + 70)]], C.ink, 14);
  ctx.restore();
}

// ═════════════════════════ BACKGROUNDS ═════════════════════════
/** (A) real world: a simple room with a window, framed picture, plant and floor */
export function room() {
  fillAll(C.bg);
  ctx.fillStyle = C.floor; ctx.fillRect(-300, 1560, W + 600, 700);
  rr(600, 230, 360, 440, 22); ctx.fillStyle = C.white; ctx.fill();
  rr(622, 252, 316, 396, 12); ctx.fillStyle = C.sky; ctx.fill();
  ell(720, 360, 70, 30, C.white); ell(770, 345, 50, 34, C.white);
  ctx.fillStyle = C.white; ctx.fillRect(772, 252, 14, 396); ctx.fillRect(622, 442, 316, 14);
  rr(110, 330, 200, 150, 10); ctx.fillStyle = C.ink; ctx.fill(); rr(124, 344, 172, 122, 4); ctx.fillStyle = '#F7D88A'; ctx.fill();
  ctx.beginPath(); ctx.moveTo(124, 466); ctx.lineTo(190, 390); ctx.lineTo(240, 440); ctx.lineTo(270, 410); ctx.lineTo(296, 466); ctx.fillStyle = '#E0956B'; ctx.fill();
  for (const [x, y, r] of [[130, 1170, -0.5], [170, 1140, 0], [210, 1170, 0.5], [150, 1110, -0.2], [195, 1105, 0.25]]) ell(x, y, 26, 62, C.leaf, r);
  rr(110, 1200, 120, 130, 14); ctx.fillStyle = C.pot; ctx.fill();
}
/** (B) x-ray: navy film with a cyan grid and a sweeping scan line */
export function xray(t) {
  fillAll(C.navy);
  ctx.strokeStyle = C.cyan; ctx.globalAlpha = 0.07; ctx.lineWidth = 2;
  for (let x = 0; x <= W; x += 90) { ctx.beginPath(); ctx.moveTo(x, -300); ctx.lineTo(x, H + 300); ctx.stroke(); }
  for (let y = 0; y <= H; y += 90) { ctx.beginPath(); ctx.moveTo(-300, y); ctx.lineTo(W + 300, y); ctx.stroke(); }
  const sy = ((t * 700) % (H + 400)) - 200;
  ctx.globalAlpha = 0.1; ctx.fillStyle = C.cyan; ctx.fillRect(-300, sy, W + 600, 70);
  ctx.globalAlpha = 0.25; ctx.fillRect(-300, sy + 66, W + 600, 6); ctx.globalAlpha = 1;
}
/** (C) inside the stomach: wobbling pink wall, folds, acid pool (acid = 0..1 strength), rising bubbles */
export function insideStomach(t, acid = 1) {
  fillAll(C.stomachBg);
  for (let i = 0; i < 7; i++) circle(rnd(i) * W + Math.sin(t + i) * 20, rnd(i + 9) * H + Math.cos(t * 0.8 + i) * 20, 120 + rnd(i + 3) * 140, C.stomachBgDark);
  ctx.beginPath();
  for (let a = 0; a <= TAU + 0.01; a += 0.05) {
    const r = 1 + 0.035 * Math.sin(3 * a + t * 2) + 0.02 * Math.sin(5 * a - t * 3);
    const x = 540 + 480 * r * Math.cos(a), y = 880 + 660 * r * Math.sin(a); a === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.closePath(); ctx.fillStyle = C.pink; ctx.fill();
  ctx.save(); ctx.clip();
  ctx.strokeStyle = C.stomachFold; ctx.lineWidth = 20; ctx.lineCap = 'round';
  for (let i = 0; i < 5; i++) { const y0 = 360 + i * 120; ctx.beginPath(); for (let x = 80; x <= 1000; x += 20) { const y = y0 + Math.sin(x * 0.012 + t * 1.5 + i) * 26; x === 80 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); } ctx.stroke(); }
  if (acid > 0) {
    ctx.beginPath(); ctx.moveTo(0, H); for (let x = 0; x <= W; x += 20) ctx.lineTo(x, 1180 + Math.sin(x * 0.015 + t * 3) * 18); ctx.lineTo(W, H); ctx.closePath();
    ctx.fillStyle = C.yellow; ctx.globalAlpha = 0.55 * acid; ctx.fill(); ctx.globalAlpha = 1;
    for (let i = 0; i < 16; i++) {
      const ph = (t * 0.6 + rnd(i)) % 1; ctx.globalAlpha = 0.85 * (1 - ph) * acid;
      ctx.beginPath(); ctx.arc(120 + rnd(i + 20) * 840 + Math.sin(t * 3 + i) * 12, 1400 - ph * 700, 10 + rnd(i + 5) * 18, 0, TAU);
      ctx.strokeStyle = C.yellow; ctx.lineWidth = 6; ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
  ctx.restore();
}

// ═════════════════════════ INTESTINE ═════════════════════════
/** serpentine gut path (5 rows) filling the upper screen; returns { pts, at(u) -> [x, y, angle], draw() } */
export function makeGut({ L = 210, R = 870, r = 100, y0 = 320, rows = 5 } = {}) {
  const pts = [];
  for (let y = y0 - 260; y < y0; y += 8) pts.push([L, y]);
  for (let row = 0; row < rows; row++) {
    const y = y0 + row * 2 * r, ltr = row % 2 === 0;
    for (let i = 0; i <= 60; i++) pts.push([ltr ? lerp(L, R, i / 60) : lerp(R, L, i / 60), y]);
    if (row < rows - 1) { const cy = y + r; for (let i = 1; i <= 24; i++) { const k = i / 24, a = ltr ? -Math.PI / 2 + k * Math.PI : -Math.PI / 2 - k * Math.PI; pts.push([(ltr ? R : L) + r * Math.cos(a), cy + r * Math.sin(a)]); } }
  }
  const last = pts[pts.length - 1]; for (let x = last[0]; x < 1250; x += 10) pts.push([x, last[1]]);
  const cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const len = cum[cum.length - 1];
  const at = (u) => { const d = clamp(u) * len; let i = 1; while (i < cum.length - 1 && cum[i] < d) i++; const a = pts[i - 1], b = pts[i], k = (d - cum[i - 1]) / ((cum[i] - cum[i - 1]) || 1); return [lerp(a[0], b[0], k), lerp(a[1], b[1], k), Math.atan2(b[1] - a[1], b[0] - a[0])]; };
  const draw = () => {
    const path = () => { ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); for (const q of pts) ctx.lineTo(q[0], q[1]); };
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    path(); ctx.strokeStyle = C.cyan; ctx.globalAlpha = 0.25; ctx.lineWidth = 112; ctx.stroke(); ctx.globalAlpha = 1;
    path(); ctx.strokeStyle = C.pinkDark; ctx.lineWidth = 92; ctx.stroke();
    path(); ctx.strokeStyle = C.pink; ctx.lineWidth = 76; ctx.stroke();
    path(); ctx.strokeStyle = C.pinkLight; ctx.globalAlpha = 0.6; ctx.lineWidth = 22; ctx.stroke(); ctx.globalAlpha = 1;
  };
  return { pts, at, draw };
}
/** a straight gut segment across the screen at y (close-up). Returns nothing; draw blockages on top */
export function gutTube(y, t = 0, width = 300) {
  const tube = () => { ctx.beginPath(); for (let x = -150; x <= 1230; x += 20) { const yy = y + Math.sin(x * 0.006 + t * 0.5) * 20; x === -150 ? ctx.moveTo(x, yy) : ctx.lineTo(x, yy); } };
  ctx.lineCap = 'round';
  tube(); ctx.strokeStyle = C.pinkDark; ctx.lineWidth = width + 30; ctx.stroke();
  tube(); ctx.strokeStyle = C.pink; ctx.lineWidth = width; ctx.stroke();
  tube(); ctx.strokeStyle = C.pinkLight; ctx.globalAlpha = 0.5; ctx.lineWidth = width * 0.2; ctx.stroke(); ctx.globalAlpha = 1;
}

// ═════════════════════════ CHARACTER ═════════════════════════
// One hero: flat man, blue tee, navy pants. Origin = chest centre; at s = 1 he is ~950 px tall (head top -480, feet +620).
// Arm poses are elbow/hand points for the RIGHT arm (the left mirrors). Blend them with armPose(a, b, t).
export const ARM = {
  down: { e: [172, 0], h: [176, 138] },
  mouth: { e: [220, -50], h: [58, -262] },     // hand at the mouth (eating, gasp)
  point: { e: [240, -90], h: [205, -300] },    // index finger up (pass finger: angle)
  wave: { e: [250, -120], h: [300, -330] },
  hip: { e: [250, 20], h: [150, 110] },
};
export const armPose = (a, b, t) => ({ e: [lerp(a.e[0], b.e[0], t), lerp(a.e[1], b.e[1], t)], h: [lerp(a.h[0], b.h[0], t), lerp(a.h[1], b.h[1], t)] });
/** mouth position in the man's local coords (for things going in / out of the mouth) */
export const MOUTH = [0, -272];
/** points along the food path in local coords: mouth -> throat -> stomach top -> inside stomach */
export const FOOD_PATH = [[0, -262], [0, -200], [-4, -80], [-12, 58]];

function arm(side, pose, finger, xr) {
  const sx = side, sh = [140 * sx, -170], e = [pose.e[0] * sx, pose.e[1]], h = [pose.h[0] * sx, pose.h[1]];
  const ang = Math.atan2(h[1] - e[1], h[0] - e[0]);
  if (xr) {
    line([sh, e], C.cyan, 58); line([e, h], C.cyan, 52);
    ctx.save(); ctx.translate(h[0], h[1]); ctx.rotate(ang); ell(6, 0, 38, 32, C.cyan); ctx.restore();
    if (finger != null) { ctx.save(); ctx.translate(h[0], h[1]); ctx.rotate(finger); rr(-15, -90, 30, 88, 15); ctx.fillStyle = C.cyan; ctx.fill(); rr(-10, -85, 20, 78, 10); ctx.fillStyle = C.xnavy; ctx.fill(); line([[0, -76], [0, -10]], C.cyan, 6); ctx.restore(); }
    line([sh, e], C.xnavy, 48); line([e, h], C.xnavy, 42);
    ctx.save(); ctx.translate(h[0], h[1]); ctx.rotate(ang); ell(6, 0, 33, 27, C.xnavy); for (const k of [-12, 0, 12]) line([[-10, k * 0.8], [28, k]], C.cyan, 6); ctx.restore();
    line([sh, e], C.cyan, 13); circle(e[0], e[1], 11, C.cyan);
    const nx = -(h[1] - e[1]), ny = h[0] - e[0], nl = Math.hypot(nx, ny) || 1, ox = nx / nl * 7, oy = ny / nl * 7;
    line([[e[0] + ox, e[1] + oy], [h[0] + ox, h[1] + oy]], C.cyan, 7); line([[e[0] - ox, e[1] - oy], [h[0] - ox, h[1] - oy]], C.cyan, 7);
    return;
  }
  line([sh, e], C.skin, 50); line([e, h], C.skin, 44);
  line([sh, [lerp(sh[0], e[0], 0.55), lerp(sh[1], e[1], 0.55)]], C.shirt, 72);       // short sleeve
  if (finger != null) { ctx.save(); ctx.translate(h[0], h[1]); ctx.rotate(finger); rr(-11, -86, 22, 80, 11); ctx.fillStyle = C.skin; ctx.fill(); ctx.restore(); }
  ctx.save(); ctx.translate(h[0], h[1]); ctx.rotate(ang); ell(6, 0, 34, 28, C.skin); ell(-2, -sx * 22, 15, 10, C.skin, -0.5 * sx); ctx.restore();
}
function torsoPath() {
  ctx.beginPath(); ctx.moveTo(-50, -214);
  ctx.bezierCurveTo(-130, -214, -162, -196, -164, -120); ctx.lineTo(-140, 192); ctx.quadraticCurveTo(-138, 210, -120, 210);
  ctx.lineTo(120, 210); ctx.quadraticCurveTo(138, 210, 140, 192); ctx.lineTo(164, -120); ctx.bezierCurveTo(162, -196, 130, -214, 50, -214); ctx.closePath();
}
function skeletonTorso(pulse) {
  ctx.save(); torsoPath(); ctx.clip();
  ctx.fillStyle = C.xnavy; ctx.fillRect(-170, -220, 340, 440);
  for (let y = -192; y < 200; y += 32) { rr(-14, y, 28, 24, 7); ctx.fillStyle = C.cyan; ctx.globalAlpha = 0.9; ctx.fill(); }
  ctx.globalAlpha = 1; ctx.strokeStyle = C.cyan; ctx.lineCap = 'round';
  for (const sd of [-1, 1]) {
    ctx.lineWidth = 13; ctx.beginPath(); ctx.moveTo(sd * 22, -186); ctx.quadraticCurveTo(sd * 80, -202, sd * 146, -180); ctx.stroke();
    for (let i = 0; i < 6; i++) { const y = -150 + i * 37; ctx.lineWidth = 11; ctx.beginPath(); ctx.moveTo(sd * 18, y); ctx.quadraticCurveTo(sd * 152, y - 26, sd * 116, y + 56); ctx.stroke(); }
    ctx.lineWidth = 12; ctx.beginPath(); ctx.ellipse(sd * 72, 232, 74, 46, 0, Math.PI, TAU); ctx.stroke();
  }
  line([[0, -205], [-4, -80]], C.pink, 22);
  stomach(20, 10, 0.8, pulse);
  ctx.restore();
  ctx.save(); ctx.globalAlpha = 0.8; torsoPath(); ctx.strokeStyle = C.cyan; ctx.lineWidth = 7; ctx.stroke(); ctx.restore();
}
function head(o) {
  ctx.save(); ctx.translate(0, -350);
  ell(0, -34, 116, 94, C.hair);
  for (const sd of [-1, 1]) { ell(sd * 104, 14, 22, 28, C.skin); ell(sd * 106, 14, 10, 15, C.skinShade); }
  ell(0, 12, 102, 112, C.skin);
  // fringe with side part
  ctx.beginPath(); ctx.moveTo(-104, -6); ctx.quadraticCurveTo(-118, -112, -14, -124); ctx.quadraticCurveTo(96, -132, 112, -26);
  ctx.quadraticCurveTo(92, -70, 40, -74); ctx.quadraticCurveTo(-20, -76, -58, -50); ctx.quadraticCurveTo(-86, -34, -104, -6); ctx.closePath();
  ctx.fillStyle = C.hair; ctx.fill(); rr(-106, -40, 18, 46, 8); ctx.fill(); rr(88, -40, 18, 46, 8); ctx.fill();
  ctx.beginPath(); ctx.moveTo(-60, -98); ctx.quadraticCurveTo(0, -118, 62, -96); ctx.strokeStyle = C.hairHi; ctx.lineWidth = 9; ctx.lineCap = 'round'; ctx.stroke();
  // brows: brow 0..1 raises them; smirk tilts
  const br = (o.brow || 0) * 16, tl = o.smirk ? 1 : 0, fr = o.frown ? 1 : 0;
  ctx.strokeStyle = C.hair; ctx.lineWidth = 12;
  ctx.beginPath(); ctx.moveTo(-66, -26 - br - fr * 6); ctx.quadraticCurveTo(-44, -40 - br - tl * 4, -20, -32 - br + tl * 6 + fr * 12); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(20, -32 - br - tl * 8 + fr * 12); ctx.quadraticCurveTo(44, -42 - br - tl * 10, 66, -28 - br - tl * 6 - fr * 6); ctx.stroke();
  // eyes: 'n' | 'wide' | 'closed'
  if (o.eyes === 'wide') {
    for (const sd of [-1, 1]) { ctx.beginPath(); ctx.ellipse(sd * 40, 6, 24, 27, 0, 0, TAU); ctx.fillStyle = C.white; ctx.fill(); ctx.lineWidth = 4; ctx.strokeStyle = C.ink; ctx.stroke(); circle(sd * 40, 8, 12, C.ink); circle(sd * 40 + 4, 3, 4, C.white); }
  } else if (o.eyes === 'closed') {
    for (const sd of [-1, 1]) { ctx.beginPath(); ctx.arc(sd * 40, 2, 13, 0.15 * Math.PI, 0.85 * Math.PI); ctx.strokeStyle = C.ink; ctx.lineWidth = 7; ctx.stroke(); }
  } else {
    const look = o.look || 0;
    for (const sd of [-1, 1]) { ell(sd * 40 + look * 6, 6, 11, 14, C.ink); circle(sd * 40 + 4 + look * 6, 1, 4, C.white); }
  }
  ctx.beginPath(); ctx.moveTo(4, 26); ctx.quadraticCurveTo(16, 44, 0, 48); ctx.strokeStyle = C.skinShade; ctx.lineWidth = 7; ctx.lineCap = 'round'; ctx.stroke();
  ctx.globalAlpha = 0.3; for (const sd of [-1, 1]) ell(sd * 62, 46, 20, 12, C.pink); ctx.globalAlpha = 1;
  // mouth: 'smile' | 'smirk' | 'chew' | 'o' | 'flat' | 'grin'
  const m = o.mouth || 'smile'; ctx.lineCap = 'round'; ctx.strokeStyle = C.mouth; ctx.lineWidth = 8;
  if (m === 'smile') { ctx.beginPath(); ctx.moveTo(-24, 70); ctx.quadraticCurveTo(0, 90, 24, 70); ctx.stroke(); }
  if (m === 'smirk') { ctx.beginPath(); ctx.moveTo(-22, 74); ctx.quadraticCurveTo(8, 88, 32, 64); ctx.stroke(); }
  if (m === 'flat') { ctx.beginPath(); ctx.moveTo(-20, 76); ctx.lineTo(20, 76); ctx.stroke(); }
  if (m === 'chew') ell(0, 76, 18, 4 + 8 * (o.chew || 0), C.mouth);
  if (m === 'o') { ell(0, 80, 20, 27, C.mouth); ell(0, 96, 13, 8, C.pink); }
  if (m === 'grin') { ctx.beginPath(); ctx.moveTo(-34, 66); ctx.quadraticCurveTo(0, 112, 34, 66); ctx.closePath(); ctx.fillStyle = C.mouth; ctx.fill(); rr(-26, 66, 52, 12, 4); ctx.fillStyle = C.white; ctx.fill(); }
  ctx.restore();
}
/**
 * The hero. o = { x, y, s, arm (pose), finger (rad or null), eyes, mouth, chew, brow, smirk, frown, look (-1..1),
 *   xray (bool: whole body becomes x-ray, head stays normal), pulse (stomach swell 0..1),
 *   holding: [drawFn(x, y)] drawn at the right hand, inside: [x, y, rot] a gum drawn inside the body (local coords) }
 */
export function man(o) {
  const s = o.s || 1, XR = !!o.xray;
  ctx.save(); ctx.translate(o.x, o.y); ctx.scale(s, s);
  if (XR) {
    for (const x of [-128, 6]) {
      rr(x, 180, 122, 440, 40); ctx.fillStyle = C.xnavy; ctx.fill(); ctx.lineWidth = 7; ctx.strokeStyle = C.cyan; ctx.stroke();
      const cx = x + 61; line([[cx, 200], [cx, 380]], C.cyan, 16); circle(cx, 400, 20, C.cyan); line([[cx - 9, 420], [cx - 9, 600]], C.cyan, 8); line([[cx + 9, 420], [cx + 9, 600]], C.cyan, 8);
    }
    rr(-36, -250, 72, 60, 20); ctx.fillStyle = C.xnavy; ctx.fill();
    for (let y = -246; y < -200; y += 22) { rr(-13, y, 26, 16, 6); ctx.fillStyle = C.cyan; ctx.fill(); }
  } else {
    rr(-128, 180, 122, 440, 40); ctx.fillStyle = C.pants; ctx.fill(); rr(6, 180, 122, 440, 40); ctx.fill();
    rr(6, 180, 40, 440, [0, 0, 0, 30]); ctx.fillStyle = C.pantsShade; ctx.fill();
    rr(-36, -250, 72, 60, 20); ctx.fillStyle = C.skin; ctx.fill();
  }
  arm(-1, o.armL || ARM.down, null, XR);
  if (XR) skeletonTorso(o.pulse || 0);
  else {
    torsoPath(); ctx.fillStyle = C.shirt; ctx.fill();
    ctx.save(); torsoPath(); ctx.clip(); ctx.beginPath(); ctx.moveTo(95, -220); ctx.quadraticCurveTo(70, 0, 100, 220); ctx.lineTo(200, 220); ctx.lineTo(200, -220); ctx.closePath(); ctx.fillStyle = C.shirtShade; ctx.fill(); ctx.restore();
    ctx.beginPath(); ctx.ellipse(0, -214, 46, 26, 0, 0, Math.PI); ctx.fillStyle = C.skin; ctx.fill(); ctx.strokeStyle = C.shirtShade; ctx.lineWidth = 12; ctx.stroke();
  }
  head(o);
  const ra = o.arm || ARM.down;
  arm(1, ra, o.finger ?? null, XR);
  if (o.holding) o.holding(ra.h[0] - 34, ra.h[1] - 14);
  if (o.inside) gum(o.inside[0], o.inside[1], 0.5, o.inside[2] || 0);
  ctx.restore();
}
/** follow FOOD_PATH: u 0..1 → [x, y] in the man's local coords */
export function foodAt(u) {
  const P = FOOD_PATH, n = P.length - 1, k = clamp(u) * n, i = Math.min(n - 1, Math.floor(k)), f = k - i;
  return [lerp(P[i][0], P[i + 1][0], f), lerp(P[i][1], P[i + 1][1], f)];
}
