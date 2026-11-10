// The Stick Story style sheet, drawn with the style's own kit.
import { ctx } from './core/lib.js';
import { startBoard, panel, frame, cell, small, swatches, rules } from './core/board.js';
import * as K from './core/kit.js';
const { P } = K;

const cv = document.getElementById('cv');
await document.fonts.load('900 40px Inter'); await document.fonts.load('800 40px Inter');
startBoard(cv, { title: 'STICK STORY: VIDEO STYLE SHEET', accent: P.gold });

// 1 · hero frame
let b = panel(20, 80, 560, 520, 1, 'HERO FRAME');
frame(b.x + 6, b.y, 240, () => {
  K.livingRoom({ night: true, lampOn: false });
  K.person({ x: 520, y: K.GROUND, h: 720, dir: 1, mood: 'worried', look: [1, -0.2], arms: { L: [-10, 20], R: [70, 20] }, hold: (x, y) => K.flashlight(x + 10, y, 1.3, true, -0.15) });
  K.counterPill('9:12 P.M.', 540, 230, 1.1);
  K.captionBar([{ txt: 'The power' }, { txt: 'goes' }, { txt: 'out.', hi: 1 }], 540, K.CAPLOOK.y, 1.05);
});
small('A STICK HERO WITH\nEYES THAT ACT', b.x + 270, b.y + 40, 'left', 17);
small('FLAT ROOMS,\nDAY OR NIGHT', b.x + 270, b.y + 130, 'left', 17);
small('ONE PICTURE\nPER CLAUSE', b.x + 270, b.y + 220, 'left', 17);
small('GOLD = STEPS,\nRED = DANGER', b.x + 270, b.y + 310, 'left', 17);

// 2 · palette
b = panel(590, 80, 660, 520, 2, 'PALETTE');
const yy = swatches(b, [['WALL', P.wall], ['FLOOR', P.floor], ['INK', P.ink], ['GOLD', P.gold], ['NAVY', P.navy], ['DANGER', P.red], ['SAFE', P.green], ['NIGHT', P.nWall]]);
['PEOPLE ARE ALWAYS INK BLACK. COLOUR LIVES IN THE ROOM.', 'GOLD IS ONLY FOR STEP CARDS AND KEY WORDS.', 'NIGHT = THE SAME ROOM IN BLUE, LIT BY ONE LAMP.']
  .forEach((t, i) => small(t, b.x + 4, yy + 20 + i * 40, 'left', 16, '#E6E7EA'));
// expressions strip (the eyes are the style's signature)
ctx.fillStyle = P.wall; ctx.beginPath(); ctx.roundRect(b.x, yy + 140, b.w, 150, 14); ctx.fill();
['calm', 'happy', 'worried', 'scared', 'determined', 'sleepy'].forEach((m, i) => cell(b.x + 55 + i * 104, yy + 195, 0.36, () => K.bigHead(0, 0, 100, { mood: m }), m.toUpperCase(), 72));

// 3 · components
b = panel(1260, 80, 640, 520, 3, 'COMPONENTS');
ctx.fillStyle = P.wall; ctx.beginPath(); ctx.roundRect(b.x, b.y, b.w, b.h, 14); ctx.fill();
const gx = (i) => b.x + 75 + i * 150, gy = (r) => b.y + 140 + r * 195;
cell(gx(0), gy(0) + 80, 0.38, () => K.person({ x: 0, y: 0, h: 520, mood: 'happy', arms: { L: [-30, 40], R: [150, 20] } }), 'HERO', 30);
cell(gx(1), gy(0) + 80, 0.38, () => K.person({ x: 0, y: 0, h: 520, mood: 'scared', walk: 1.2, dir: -1 }), 'WALKING', 30);
cell(gx(2), gy(0), 0.55, () => K.bigHead(0, -20, 120, { mood: 'determined' }), 'CLOSE-UP', 90);
cell(gx(3), gy(0), 0.5, () => K.thought(0, -40, 0.8, () => K.bottle(0, -20, 0.6), 60, 120), 'THOUGHT', 90);
cell(gx(0), gy(1), 0.55, () => { K.bottle(-40, 60); K.can(50, 60); }, 'SUPPLIES', 70);
cell(gx(1), gy(1), 0.5, () => K.phone(0, 0, 0.8, true), 'PHONE', 70);
cell(gx(2), gy(1) - 10, 0.55, () => { K.check(-55, 0, 0.8); K.cross(55, 0, 0.8); }, 'YES / NO', 80);
cell(gx(3), gy(1), 0.2, () => K.stepCard(1, 'FILL THE TUB', 0, 0), 'STEP CARD', 70);

// 4 · scenes
b = panel(20, 610, 760, 456, 4, 'SCENES');
const sw = 200, sx = (i) => b.x + 20 + i * (sw + 45);
frame(sx(0), b.y, sw, () => { K.livingRoom({}); K.person({ x: 420, y: K.GROUND, h: 700, mood: 'calm', dir: 1, look: [1, 0] }); });
frame(sx(1), b.y, sw, () => { K.kitchen({}); K.person({ x: 650, y: K.GROUND, h: 700, mood: 'determined', dir: -1, hold: (x, y) => K.bottle(x, y + 40, 1) }); });
frame(sx(2), b.y, sw, () => { K.hallway({ night: true, openB: 0.3 }); K.person({ x: 520, y: K.GROUND, h: 700, mood: 'scared', dir: 1, walk: 0.6 }); });
['(A) LIVING ROOM', '(B) KITCHEN', '(C) HALLWAY · NIGHT'].forEach((t, i) => small(t, sx(i) + sw / 2, b.y + sw * 16 / 9 + 26, 'center', 15));

// 5 · captions
b = panel(790, 610, 520, 456, 5, 'CAPTIONS');
ctx.fillStyle = P.wall; ctx.fillRect(b.x, b.y, b.w, b.h - 10);
[[[{ txt: 'Lock' }, { txt: 'the' }, { txt: 'door.', hi: 1 }], 70], [[{ txt: 'Then' }, { txt: 'fill' }, { txt: 'the' }, { txt: 'tub.', hi: 1 }], 175], [[{ txt: 'Day' }, { txt: 'three.', hi: 1 }], 280]]
  .forEach(([w, y]) => cell(b.x + b.w / 2, b.y + y, 0.42, () => K.captionBar(w, 0, 0), null));
small('SENTENCE CASE · 2-4 WORDS · ONE GOLD WORD', b.x + b.w / 2, b.y + b.h - 26, 'center', 14, '#5A5560');

// 6 · rules
b = panel(1320, 610, 580, 456, 6, 'RULES');
rules(b, ['ONE PICTURE PER CLAUSE: CUT EVERY 1-2 S.', 'EYES ACT FIRST: LOOK, THEN REACT.', 'EVERY STEP GETS A GOLD NUMBERED CARD.', 'SAME ROOMS ALL VIDEO: DAY, THEN NIGHT.', 'CINEMA BARS ONLY ON THE SCARY BEAT.', 'SOFT CARTOON SOUND: POP, WHOOSH, STEPS.', 'MOOD: TENSE, CLEVER, A LITTLE FUNNY.'], b.y + 26, 17, 52);
window.SHEET_READY = true;
