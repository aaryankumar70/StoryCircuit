// CurioLoop Studio - Paper Atlas Style
// Topic: "The sunken Egyptian port city of Thonis-Heracleion"
// Visual Choreography: Ancient Mediterranean myth -> 8th Century BC Egyptian port -> Customs quay -> Earthquakes & liquefaction -> Year 2000 discovery -> Sunken metropolis preserved
import { ctx, W, H, TAU, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line } from './core/lib.js';
import { L, Wd, T } from './core/timing.js';
import * as K from './core/kit.js';

const { P, cut, P_rr, P_poly, P_circ } = K;

// ── Egyptian Architecture & Underwater Cut-Paper Helpers ──
function drawEgyptianPylon(x, y, s = 1) {
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  // Left pylon tower (slanted Egyptian wall)
  cut(P_poly([[-180, 0], [-130, -320], [-40, -320], [-20, 0]]), P.stone, { shadow: 0.7, edge: 4 });
  // Right pylon tower
  cut(P_poly([[20, 0], [40, -320], [130, -320], [180, 0]]), P.stone, { shadow: 0.7, edge: 4 });
  // Central portal lintel & winged sun disc
  cut(P_rr(-50, -220, 100, 220, 4), P.stoneDark, { shadow: 0, edge: 3 });
  cut(P_poly([[-150, -335], [150, -335], [130, -315], [-130, -315]]), P.gold, { shadow: 0.5, edge: 3 });
  circle(0, -350, 24, P.crimson);
  // Two Egyptian palm column pillars
  for (const px of [-230, 230]) {
    cut(P_rr(px - 14, -260, 28, 260, 4), P.stoneDark);
    cut(P_poly([[px - 36, -280], [px + 36, -280], [px, -240]]), P.green);
  }
  ctx.restore();
}

function drawEgyptNileMap(t) {
  K.parchment(5);
  // Mediterranean Sea on top, Nile Delta below
  cut(() => {
    ctx.beginPath();
    ctx.moveTo(-300, 0);
    ctx.lineTo(W + 300, 0);
    ctx.lineTo(W + 300, 780);
    for (let x = W + 300; x >= -300; x -= 40) {
      ctx.lineTo(x, 780 + Math.sin(x * 0.008 + t * 0.5) * 32);
    }
    ctx.closePath();
  }, P.sea, { shadow: 0.8, edge: 6 });

  // Nile Delta river branches flowing north into the sea
  ctx.strokeStyle = P.seaDark; ctx.lineWidth = 14; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(540, 1600); ctx.lineTo(540, 1150); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(540, 1150); ctx.bezierCurveTo(460, 980, 360, 880, 320, 800); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(540, 1150); ctx.bezierCurveTo(620, 980, 720, 880, 760, 800); ctx.stroke();

  // Location pin of Thonis-Heracleion at the mouth of the Nile
  circle(460, 770, 16, P.crimson);
  circle(460, 770, 28, 'rgba(168, 50, 45, 0.35)');
  K.slip('THONIS-HERACLEION', 460, 690, 1, 0.02, 42);
  K.slip('CANOPIC MOUTH OF THE NILE', 540, 1340, 1, 0, 36);
  K.compass(880, 480, 0.6);
}

function drawUnderwaterRuins(t, diverProgress = 1) {
  K.parchment(9);
  // Deep submerged seabed (Aboukir Bay)
  ctx.fillStyle = '#2A4A48'; ctx.fillRect(-300, -300, W + 600, H + 600);
  ctx.fillStyle = '#3E6662'; ctx.fillRect(-300, 100, W + 600, 1200);

  // Sea water ripple layers
  for (let i = 0; i < 3; i++) {
    const y = 300 + i * 220;
    ctx.strokeStyle = 'rgba(247, 239, 220, 0.22)'; ctx.lineWidth = 8;
    ctx.beginPath();
    for (let x = -300; x <= W + 300; x += 30) {
      const yy = y + Math.sin(x * 0.01 + t * 2 + i) * 16;
      x === -300 ? ctx.moveTo(x, yy) : ctx.lineTo(x, yy);
    }
    ctx.stroke();
  }

  // Seabed mud / silt floor
  cut(P_rr(-300, 1320, W + 600, 600, 0), '#6B5A44', { shadow: 0, edge: 4 });

  // Submerged colossal Egyptian stone statue (Hapi, God of the Nile)
  ctx.save(); ctx.translate(540, 1330);
  // Base plinth
  cut(P_rr(-140, -40, 280, 60, 6), P.stoneDark);
  // Colossal torso and headdress
  cut(P_poly([[-70, -40], [-90, -420], [90, -420], [70, -40]]), P.stone);
  cut(P_circ(0, -490, 68), P.stone);
  cut(P_poly([[-45, -550], [45, -550], [25, -640], [-25, -640]]), P.gold, { shadow: 0.6, edge: 3 });
  // Papyrus offering table in hands
  cut(P_rr(-60, -260, 120, 36, 4), P.stoneDark);
  ctx.restore();

  // Floating silt specks & bubbles
  for (let i = 0; i < 20; i++) {
    const by = ((H + 300) - (t * 120 + rnd(i) * 1600) % (H + 400));
    const bx = 160 + rnd(i + 14) * 760 + Math.sin(t * 2 + i) * 18;
    circle(bx, by, 6 + rnd(i) * 8, 'rgba(255, 255, 255, 0.45)');
  }

  // Diver explorer flashlight beam
  const dx = lerp(160, 380, diverProgress);
  const dy = 880 + Math.sin(t * 1.5) * 20;
  ctx.save();
  const beam = ctx.createRadialGradient(dx, dy, 20, 540, 1050, 480);
  beam.addColorStop(0, 'rgba(255, 240, 180, 0.7)');
  beam.addColorStop(1, 'rgba(255, 240, 180, 0)');
  ctx.fillStyle = beam;
  ctx.beginPath(); ctx.moveTo(dx, dy); ctx.lineTo(720, 850); ctx.lineTo(660, 1350); ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Diver silhouette cut-out
  cut(P_poly([[dx - 40, dy], [dx + 30, dy - 20], [dx + 50, dy + 15], [dx - 20, dy + 25]]), P.ink);
  circle(dx + 32, dy - 6, 14, P.royal);
}

export function buildShots() {
  const S = [], CUES = [];
  const add = (o) => (S.push(o), o);
  const cue = (t, type, o = {}) => CUES.push({ t: +t.toFixed(3), type, ...o });
  const cut_ = (i) => (i === 0 ? 0 : L(i) - 0.08);

  // ── 1 · MYTH: Scholars believed it was just a Greek legend ─────────────────
  {
    const st = cut_(0);
    add({
      id: 'S01', at: st, cam: [540, 880], zoom: 0.08, note: 'ancient map of Mediterranean, myth ribbon',
      draw(lt, d, t) {
        drawEgyptNileMap(t);
        K.ribbon('A GREEK MYTH?', 540, 360, eob(seg(lt, 0.1, 0.45)));
        K.figure({ x: 300, y: 1440, h: 560, role: 'scholar', dir: 1, arm: 20 });
        K.figure({ x: 780, y: 1440, h: 540, role: 'merchant', dir: -1 });
        K.slip('HERODOTUS RECORDED IT', 540, 1140, eob(seg(lt, 0.5, 0.85)), -0.02, 38);
      }
    });
    cue(st, 'whoosh'); cue(st + 0.15, 'pop', { gain: 0.6 }); cue(st + 0.7, 'tock');
  }

  // ── 2 · FOUNDED 8TH CENTURY BC: Port gateway of Egypt ─────────────────────
  {
    const st = cut_(1);
    add({
      id: 'S02', at: st, cam: [540, 920], zoom: 0.1, note: 'grand Egyptian port, 8th century BC ribbon, temple pylons',
      draw(lt, d, t) {
        K.parchment(3);
        // Sky & Nile water
        ctx.fillStyle = P.sky; ctx.fillRect(-300, -300, W + 600, 1200);
        drawEgyptianPylon(540, 1180, 1.25);
        // River waves
        for (let i = 0; i < 3; i++) {
          const y = 1180 + i * 110;
          cut(() => {
            ctx.beginPath(); ctx.moveTo(-300, H + 300); ctx.lineTo(-300, y);
            for (let x = -300; x <= W + 300; x += 40) ctx.lineTo(x, y + Math.sin(x * 0.012 + t * 1.8 + i) * 16);
            ctx.lineTo(W + 300, H + 300); ctx.closePath();
          }, i % 2 ? P.seaDark : P.sea, { shadow: 0.6, edge: 4 });
        }
        K.ribbon('8TH CENTURY BC', 540, 320, eob(seg(lt, 0.1, 0.42)));
        K.slip('EGYPT’S GREATEST PORT GATEWAY', 540, 480, eob(seg(lt, 0.4, 0.75)), 0.02, 42);
      }
    });
    cue(st, 'whoosh'); cue(st + 0.15, 'pop', { gain: 0.5 }); cue(st + 0.8, 'slide', { dur: 0.9 });
  }

  // ── 3 · CUSTOMS & TAXES: Mandatory trade dock ──────────────────────────────
  {
    const st = cut_(2);
    add({
      id: 'S03', at: st, cam: [540, 960], note: 'customs harbor, ships paying royal taxes to Pharaoh',
      draw(lt, d, t) {
        K.harbor(t, 640);
        // Egyptian royal tax official & Greek merchant
        K.figure({ x: 380, y: 1250, h: 540, role: 'guard', dir: 1, arm: 15 });
        K.figure({ x: 700, y: 1250, h: 520, role: 'merchant', dir: -1 });
        // Royal Egyptian wax seal
        K.seal(820, 680, eob(seg(lt, 0.2, 0.55)), 'P');
        K.slip('MANDATORY ROYAL TAXES', 540, 340, eob(seg(lt, 0.1, 0.4)), -0.02, 44);
        K.slip('CUSTOMS PORT FOR ALL GREEK SHIPS', 540, 480, eob(seg(lt, 0.45, 0.8)), 0.01, 38);
      }
    });
    cue(st, 'whoosh'); cue(st + 0.2, 'pop', { gain: 0.6 }); cue(st + 0.7, 'thud');
  }

  // ── 4 · CATACLYSM: Earthquakes & soil liquefaction ──────────────────────────
  {
    const st = cut_(3);
    add({
      id: 'S04', at: st, cam: [540, 920], zoom: 0.15, note: 'earthquakes, soil liquefaction, temple sinks into sea',
      draw(lt, d, t) {
        K.parchment(8);
        const shake = Math.sin(lt * 60) * 12 * Math.exp(-lt * 0.4);
        ctx.save(); ctx.translate(shake, 0);

        // Cracking earth and rising sea surge
        const sinkY = 1180 + eio(clamp(lt / d)) * 260;
        drawEgyptianPylon(540, sinkY, 1.2);

        // Surging paper tidal waves
        for (let i = 0; i < 4; i++) {
          const y = 980 + i * 140 - lt * 30;
          cut(() => {
            ctx.beginPath(); ctx.moveTo(-300, H + 300); ctx.lineTo(-300, y);
            for (let x = -300; x <= W + 300; x += 35) ctx.lineTo(x, y + Math.sin(x * 0.015 + t * 4 + i) * 28);
            ctx.lineTo(W + 300, H + 300); ctx.closePath();
          }, i % 2 ? P.seaDark : P.sea, { shadow: 0.8, edge: 5 });
        }
        ctx.restore();

        K.slip('8TH CENTURY AD: EARTHQUAKES', 540, 320, eob(seg(lt, 0.1, 0.4)), -0.03, 44);
        K.slip('SOIL LIQUEFACTION SINKS THE CITY', 540, 470, eob(seg(lt, 0.4, 0.75)), 0.02, 40);
      }
    });
    cue(st, 'whoosh'); cue(st + 0.1, 'slam', { dur: 1.2 }); cue(st + 0.8, 'bubbles', { dur: 2.2 });
  }

  // ── 5 · REDISCOVERY: Year 2000 Franck Goddio & IEASM ─────────────────────
  {
    const st = cut_(4);
    add({
      id: 'S05', at: st, cam: [540, 920], note: 'year 2000 ribbon, underwater diver flashlight on colossal statue',
      draw(lt, d, t) {
        const diverProgress = eio(clamp(lt / (d * 0.85)));
        drawUnderwaterRuins(t, diverProgress);
        K.ribbon('YEAR 2000', 540, 320, eob(seg(lt, 0.1, 0.42)));
        K.slip('DISCOVERED 30 FEET UNDER SILT', 540, 480, eob(seg(lt, 0.35, 0.7)), -0.01, 42);
        K.slip('FRANCK GODDIO & IEASM EXPEDITION', 540, 1460, eob(seg(lt, 0.65, 0.95)), 0.02, 36);
      }
    });
    cue(st, 'whoosh'); cue(st + 0.15, 'pop', { gain: 0.5 }); cue(st + 0.7, 'bubbles', { dur: 1.8 });
  }

  // ── 6 · FROZEN IN TIME: Majestic underwater Egyptian metropolis ────────────
  {
    const st = cut_(5);
    add({
      id: 'S06', at: st, cam: [540, 900], zoom: 0.06, note: 'colossal statues, gold relics, peaceful conclusion',
      draw(lt, d, t) {
        drawUnderwaterRuins(t, 1.0);
        // Golden Egyptian artifacts resting in seabed silt
        for (const [gx, gy, gr] of [[340, 1340, 24], [720, 1360, 32], [480, 1370, 18]]) {
          circle(gx, gy, gr, P.gold);
          circle(gx, gy, gr * 0.7, P.parch);
        }
        K.slip('THRIVING EGYPTIAN METROPOLIS', 540, 320, eob(seg(lt, 0.15, 0.5)), -0.02, 46);
        K.slip('FROZEN IN TIME ON THE SEA FLOOR', 540, 460, eob(seg(lt, 0.5, 0.85)), 0.02, 40);
      }
    });
    cue(st, 'whoosh'); cue(st + 0.25, 'sparkle', { dur: 1.8 }); cue(st + 0.8, 'pop');
  }

  return { shots: S, cues: CUES };
}
