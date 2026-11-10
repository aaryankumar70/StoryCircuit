// Timing: everything on screen is placed on the narration's clock.
// Adaptive timing supporting dynamic lines and safe fallback word alignment.
export const T = { dur: 0, lines: [], words: [] };
const norm = (w) => String(w).toLowerCase().replace(/[^a-z0-9']+/g, '');

export async function loadTiming() {
  const get = async (f) => {
    const r = await fetch(f, { cache: 'no-store' });
    if (!r.ok) throw new Error(`missing ${f}: run voice.py + words.py`);
    return r.json();
  };
  const lines = await get('data/lines.json'), words = await get('data/words.json');
  T.lines = lines.lines;
  T.words = words;
  T.dur = lines.duration;
  return T;
}

export const L = (i) => {
  if (i >= 0 && i < T.lines.length) return T.lines[i].start;
  if (T.lines.length > 0) return T.lines[T.lines.length - 1].end;
  return 0;
};

export const Le = (i) => {
  if (i >= 0 && i < T.lines.length) return T.lines[i].end;
  if (T.lines.length > 0) return T.lines[T.lines.length - 1].end;
  return T.dur;
};

export function Wd(word, line, which = 's') {
  const n = norm(word);
  const hit = T.words.find((w) => (line == null || w.line === line) && norm(w.w).startsWith(n));
  if (hit) return hit[which];
  if (line != null && line < T.lines.length) {
    const l = T.lines[line];
    return l.start + (l.end - l.start) * 0.45;
  }
  return T.dur * 0.5;
}

export const lineWords = (i) => T.words.filter((w) => w.line === i);
