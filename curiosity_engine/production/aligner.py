"""Word Timing Alignment Engine.
Produces word-level timestamps (data/words.json) using Whisper alignment
with deterministic inline phonetic length fallback.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.config import WHISPER_DIR

logger = logging.getLogger("curiosity_engine.aligner")

norm = lambda w: re.sub(r"[^a-z0-9]+", "", w.lower())


def align_tokens(script_words: List[str], heard: List[Tuple[str, float, float]], t0: float, t1: float) -> List[Tuple[float, float]]:
    """Align heard Whisper words to script tokens."""
    a = [norm(w) for w in script_words]
    b = [norm(h[0]) for h in heard]
    times = [None] * len(a)

    for blk in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            times[blk.a + k] = (heard[blk.b + k][1], heard[blk.b + k][2])

    i = 0
    while i < len(a):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(a) and times[j] is None:
            j += 1
        lo = times[i - 1][1] if i > 0 else t0
        hi = times[j][0] if j < len(a) else t1
        if hi <= lo:
            hi = lo + 0.05 * (j - i)
        lens = [max(1, len(a[k])) for k in range(i, j)]
        tot = sum(lens)
        c = lo
        for k, l in zip(range(i, j), lens):
            d = (hi - lo) * l / tot
            times[k] = (c, c + d * 0.9)
            c += d
        i = j
    return times


def inline_fallback(project_dir: Path, script: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Spread words inside each line's exact TTS window by phonetic length."""
    lines_file = project_dir / "data" / "lines.json"
    with open(lines_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    lines = meta["lines"]
    words = []

    for i, ln in enumerate(script["lines"]):
        toks = [w for w in ln["text"].split() if norm(w)]
        if not toks:
            continue
        wts = [
            len(norm(w)) + 2.5 + (2.5 if w.endswith(",") else 4.5 if re.search(r"[.?!]$", w) and k < len(toks) - 1 else 0)
            for k, w in enumerate(toks)
        ]
        lo = lines[i]["start"]
        hi = lines[i]["end"]
        c = lo
        tot = sum(wts) if sum(wts) > 0 else 1.0

        for w, wt in zip(toks, wts):
            d = (hi - lo) * wt / tot
            speak = d - (hi - lo) * (wt - len(norm(w)) - 2.5) / tot
            words.append({
                "w": w,
                "line": i,
                "s": round(c, 3),
                "e": round(c + speak * 0.92, 3),
            })
            c += d

    return words


def resolve_whisper_model_path(whisper_dir: Path = WHISPER_DIR) -> Optional[str]:
    """Resolve local faster-whisper CTranslate2 model directory containing model.bin.
    Supports both flat layout (WHISPER_DIR/model.bin) and HuggingFace cache layout
    (WHISPER_DIR/refs/main + WHISPER_DIR/snapshots/<hash>/model.bin).
    Returns None if no local model.bin is found.
    """
    if not whisper_dir.exists():
        return None

    # 1. Flat layout: model.bin directly in WHISPER_DIR
    if (whisper_dir / "model.bin").exists():
        return str(whisper_dir)

    # 2. HuggingFace hub cache layout: check refs/main first
    ref_main = whisper_dir / "refs" / "main"
    snapshots_dir = whisper_dir / "snapshots"
    if ref_main.exists() and snapshots_dir.exists():
        try:
            rev = ref_main.read_text(encoding="utf-8").strip()
            candidate = snapshots_dir / rev
            if (candidate / "model.bin").exists():
                return str(candidate)
        except Exception:
            pass

    # 3. Fallback scan inside snapshots/*/model.bin
    if snapshots_dir.exists():
        for candidate in sorted(snapshots_dir.iterdir()):
            if candidate.is_dir() and (candidate / "model.bin").exists():
                return str(candidate)

    return None


def align_narration_words(project_dir: Path) -> List[Dict[str, Any]]:
    """Generate data/words.json and data/words.txt for project."""
    script_path = project_dir / "script.json"
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    words = None
    # 1. Try local Whisper model cleanly (never silently trigger multi-hundred-MB downloads if local missing unless configured)
    local_model_path = resolve_whisper_model_path(WHISPER_DIR)
    try:
        if not local_model_path:
            raise FileNotFoundError(
                f"Local Whisper model.bin not found under '{WHISPER_DIR}' "
                "(expected flat model.bin or HuggingFace snapshots/<rev>/model.bin)."
            )
        from faster_whisper import WhisperModel
        model = WhisperModel(local_model_path, device="cpu", compute_type="int8", local_files_only=True)

        wav_path = project_dir / "data" / "narration.wav"
        import numpy as np
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(wav_path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            capture_output=True,
            check=True,
        ).stdout
        segs, _ = model.transcribe(np.frombuffer(raw, dtype=np.float32), word_timestamps=True, vad_filter=False)
        heard = [(w.word.strip(), w.start + 0.04, w.end) for s in segs for w in s.words]

        toks = [(w, i) for i, ln in enumerate(script["lines"]) for w in ln["text"].split() if norm(w)]
        dur_cmd = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        dur_audio = float(dur_cmd.stdout.strip())

        times = align_tokens([w for w, _ in toks], heard, 0.0, dur_audio)
        words = [{"w": w, "line": i, "s": round(s, 3), "e": round(e, 3)} for (w, i), (s, e) in zip(toks, times)]

        # Clamp inside exact TTS line window
        with open(project_dir / "data" / "lines.json", "r", encoding="utf-8") as f:
            lines_data = json.load(f)["lines"]
        for w in words:
            lo = lines_data[w["line"]]["start"]
            hi = lines_data[w["line"]]["end"]
            w["s"] = round(min(max(w["s"], lo), hi), 3)
            w["e"] = round(min(max(w["e"], w["s"]), hi), 3)
        logger.info(f"Whisper aligned {len(words)} words.")
    except Exception as e:
        logger.info(f"Whisper fallback active ({e}); calculating exact inline timings.")
        words = inline_fallback(project_dir, script)

    words_json_path = project_dir / "data" / "words.json"
    with open(words_json_path, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=2)

    words_txt_path = project_dir / "data" / "words.txt"
    with open(words_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(f"{w['s']:7.2f} {w['e']:7.2f}  L{w['line']:<2d} {w['w']}" for w in words))

    return words
