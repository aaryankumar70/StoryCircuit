// The Paper Atlas style sheet, drawn with the style's own kit.
import { ctx } from './core/lib.js';
import { startBoard, panel, frame, cell, small, swatches, rules } from './core/board.js';
import * as K from './core/kit.js';
const { P } = K;

const cv = document.getElementById('cv');
await document.fonts.load('900 40px Inter'); await document.fonts.load('700 40px Caladea');
startBoard(cv, { title: 'PAPER ATLAS: VIDEO STYLE SHEET', bg: '#1D1712', line: '#4D3E2F', head: '#F1E6CC', accent: P.gold });

// 1 · hero frame
let b = panel(20, 80, 560, 520, 1, 'HERO FRAME');
frame(b.x + 6, b.y, 240, () => {
  const m = K.map({ highlight: 0, route: 1 });
  K.ship(600, 870, 0.32);
  K.ribbon('1911', 540, 290, 1);
  K.captionStrip([{ txt: 'The' }, { txt: 'ship' }, { txt: 'vanished.', hi: 1 }], 540, K.CAPLOOK.y, 0.95);
});
small('EVERYTHING IS\nCUT PAPER', b.x + 270, b.y + 40, 'left', 17);
small('AGED PARCHMENT\nMAPS', b.x + 270, b.y + 130, 'left', 17);
small('CRIMSON ROUTES,\nGOLD DATES', b.x + 270, b.y + 220, 'left', 17);
small('SLOW PANS\nACROSS THE PAGE', b.x + 270, b.y + 310, 'left', 17);

// 2 · palette
b = panel(590, 80, 660, 520, 2, 'PALETTE');
const yy = swatches(b, [['PAPER', P.parch], ['INK', P.ink], ['CRIMSON', P.crimson], ['GOLD', P.gold], ['SEA', P.sea], ['LAND', P.land], ['ROYAL', P.royal], ['FOREST', P.forest]]);
['CRIMSON ONLY FOR ROUTES, TARGETS AND THE KEY WORD.', 'GOLD ONLY FOR DATES, CROWNS AND SEALS.', 'EVERY SHAPE HAS A PAPER EDGE AND A SOFT SHADOW.']
  .forEach((t, i) => small(t, b.x + 4, yy + 20 + i * 40, 'left', 16, '#EFE6D2'));
ctx.save(); ctx.beginPath(); ctx.roundRect(b.x, yy + 140, b.w, 150, 14); ctx.clip(); ctx.translate(b.x, yy + 140); ctx.scale(b.w / 1080, 150 / 300); K.parchment(2); ctx.restore();
['king', 'queen', 'sailor', 'scholar', 'guard', 'merchant'].forEach((r, i) => cell(b.x + 55 + i * 104, yy + 262, 0.15, () => K.figure({ x: 0, y: 0, role: r }), r.toUpperCase(), 22, '#3E2C1E'));

// 3 · components
b = panel(1260, 80, 640, 520, 3, 'COMPONENTS');
ctx.save(); ctx.beginPath(); ctx.roundRect(b.x, b.y, b.w, b.h, 14); ctx.clip(); ctx.translate(b.x, b.y); ctx.scale(b.w / 1080, b.h / 900); K.parchment(5); ctx.restore();
const gx = (i) => b.x + 80 + i * 158, gy = (r) => b.y + 110 + r * 205, L = '#3E2C1E';
cell(gx(0) + 40, gy(0) - 10, 0.3, () => K.ribbon('1666', 0, 0), 'DATE RIBBON', 90, L);
cell(gx(2), gy(0) - 10, 0.5, () => K.seal(0, 0), 'WAX SEAL', 90, L);
cell(gx(3), gy(0) - 10, 0.5, () => K.compass(0, 0, 0.9), 'COMPASS', 90, L);
cell(gx(0) + 70, gy(1) - 20, 0.26, () => K.timeline([1492, 1588, 1666, 1776], -420, 0, 840, 0.66, 2), 'TIMELINE', 80, L);
cell(gx(2), gy(1) - 10, 0.22, () => K.ship(0, 120), 'SHIP', 80, L);
cell(gx(3) - 22, gy(1) - 10, 0.4, () => K.slip('LISBON', 0, 0), 'PINNED SLIP', 80, L);

// 4 · scenes
b = panel(20, 610, 760, 456, 4, 'SCENES');
const sw = 200, sx = (i) => b.x + 20 + i * (sw + 45);
frame(sx(0), b.y, sw, () => { K.map({ highlight: 1, route: 0.6 }); });
frame(sx(1), b.y, sw, () => { K.hall(); K.figure({ x: 540, y: 1330, h: 620, role: 'king' }); K.figure({ x: 240, y: 1500, h: 700, role: 'guard', dir: 1 }); K.figure({ x: 860, y: 1520, h: 700, role: 'scholar', dir: -1, arm: 60 }); });
frame(sx(2), b.y, sw, () => { K.harbor(0.5, 560); K.figure({ x: 160, y: 1250, h: 420, role: 'sailor', arm: 120 }); });
['(A) THE MAP', '(B) THE COURT', '(C) THE HARBOR'].forEach((t, i) => small(t, sx(i) + sw / 2, b.y + sw * 16 / 9 + 26, 'center', 15, '#E6DCC6'));

// 5 · captions
b = panel(790, 610, 520, 456, 5, 'CAPTIONS');
ctx.save(); ctx.beginPath(); ctx.rect(b.x, b.y, b.w, b.h - 10); ctx.clip(); ctx.translate(b.x, b.y); ctx.scale(b.w / 1080, (b.h - 10) / 800); K.parchment(9); ctx.restore();
[[[{ txt: 'In' }, { txt: '1666,', hi: 1 }], 70], [[{ txt: 'London' }, { txt: 'burned.', hi: 1 }], 175], [[{ txt: 'The' }, { txt: 'king' }, { txt: 'fled.', hi: 1 }], 280]]
  .forEach(([w, y]) => cell(b.x + b.w / 2, b.y + y, 0.48, () => K.captionStrip(w, 0, 0), null));
small('SERIF ON TORN PAPER · 2-4 WORDS · ONE CRIMSON WORD', b.x + b.w / 2, b.y + b.h - 26, 'center', 13, '#5A4632');

// 6 · rules
b = panel(1320, 610, 580, 456, 6, 'RULES');
rules(b, ['EVERY SHAPE IS CUT PAPER WITH A SHADOW.', 'A DATE RIBBON OPENS EVERY NEW ERA.', 'MAPS FIRST: WHERE, THEN WHO, THEN WHAT.', 'CAMERA PANS AND PUSHES, 2-4 S SHOTS.', 'NO BATTLES SHOWN: TELL IT WITH OBJECTS.', 'SOUND: PAPER RUSTLE, QUILL, SOFT STRINGS.', 'MOOD: STORYBOOK, CURIOUS, GRAND.'], b.y + 26, 17, 52);
window.SHEET_READY = true;
