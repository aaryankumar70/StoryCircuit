// Style-sheet board (1920x1080): the style's look on one page, drawn with the style's OWN kit, so the sheet always
// matches what renders. Used by sheet.html -> node tools/capture.mjs stylesheet ../style-sheet.png
import { setCtx } from './lib.js';

export const BW = 1920, BH = 1080;
let B = null;                                   // the board's 2D context
const off = document.createElement('canvas'); off.width = 1080; off.height = 1920;
const offCtx = off.getContext('2d');

export function startBoard(canvas, { title, author = 'MADE BY YOUR NAME · 2026', bg = '#17181C', line = '#4A4D55', head = '#F2F2F2', accent = '#FFD43B', font = 'Inter' }) {
  B = canvas.getContext('2d'); setCtx(B);
  B.fillStyle = bg; B.fillRect(0, 0, BW, BH);
  B.font = `900 44px ${font}`; B.fillStyle = head; B.textBaseline = 'alphabetic'; B.textAlign = 'left'; B.letterSpacing = '3px';
  B.fillText(title, 24, 52);
  B.font = `800 22px Inter`; B.textAlign = 'right'; B.fillStyle = '#B9BCC4'; B.letterSpacing = '2px'; B.fillText(author, BW - 24, 48);
  B.letterSpacing = '0px';
  board.line = line; board.head = head; board.accent = accent; board.font = font;
  return B;
}
export const board = { line: '#444', head: '#fff', accent: '#ff0', font: 'Inter' };

/** a numbered panel with its heading; returns the inner content box */
export function panel(x, y, w, h, n, label) {
  B.strokeStyle = board.line; B.lineWidth = 2; B.strokeRect(x + 0.5, y + 0.5, w, h);
  B.font = `900 30px ${board.font}`; B.fillStyle = board.head; B.textAlign = 'left'; B.letterSpacing = '6px';
  B.fillText(`${n}. ${label}`, x + 18, y + 42); B.letterSpacing = '0px';
  B.strokeStyle = board.line; B.beginPath(); B.moveTo(x + 18, y + 58); B.lineTo(x + w - 18, y + 58); B.stroke();
  return { x: x + 18, y: y + 72, w: w - 36, h: h - 90 };
}
/** render a 1080x1920 frame with drawFn (which uses the kit) and place it at x, y, w (height = w * 16/9) */
export function frame(x, y, w, drawFn) {
  offCtx.setTransform(1, 0, 0, 1, 0, 0); offCtx.globalAlpha = 1; offCtx.clearRect(0, 0, 1080, 1920);
  setCtx(offCtx); offCtx.save(); drawFn(); offCtx.restore(); setCtx(B);
  const h = w * 16 / 9; B.drawImage(off, x, y, w, h);
  B.strokeStyle = board.line; B.lineWidth = 2; B.strokeRect(x, y, w, h);
  return h;
}
/** draw a kit component at (cx, cy) scaled by s, with a label under it */
export function cell(cx, cy, s, drawFn, label, labelY = 90, color = '#3A3640') {
  B.save(); B.translate(cx, cy); B.scale(s, s); drawFn(); B.restore(); setCtx(B);
  if (label) small(label, cx, cy + labelY, 'center', 15, color);
}
export function small(text, x, y, align = 'left', size = 17, color = '#D7D9DE') {
  B.font = `800 ${size}px Inter`; B.fillStyle = color; B.textAlign = align; B.letterSpacing = '2px';
  text.split('\n').forEach((l, i) => B.fillText(l, x, y + i * (size + 5))); B.letterSpacing = '0px';
}
export function swatches(box, list) {
  const n = list.length, gap = 12, sw = Math.min(78, (box.w - gap * (n - 1)) / n), tw = n * sw + (n - 1) * gap, x0 = box.x + (box.w - tw) / 2;
  list.forEach(([name, hex], i) => {
    const x = x0 + i * (sw + gap); B.fillStyle = hex; B.beginPath(); B.roundRect(x, box.y + 10, sw, sw * 0.9, 8); B.fill();
    B.strokeStyle = 'rgba(255,255,255,0.15)'; B.lineWidth = 1; B.stroke();
    small(name + '\n' + hex.toUpperCase(), x + sw / 2, box.y + sw * 0.9 + 34, 'center', 13);
  });
  return box.y + sw * 0.9 + 80;
}
export function rules(box, list, y0 = box.y + 20, size = 19, step = 52) {
  list.forEach((r, i) => {
    B.beginPath(); B.arc(box.x + 18, y0 + i * step - 6, 17, 0, 7); B.strokeStyle = board.head; B.lineWidth = 2; B.stroke();
    small(String(i + 1), box.x + 18, y0 + i * step + 1, 'center', 17, board.head);
    small(r, box.x + 50, y0 + i * step, 'left', size, '#E6E7EA');
  });
}
