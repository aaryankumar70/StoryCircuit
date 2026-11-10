"""Kokoro-82M ONNX Text-to-Speech Engine for Curiosity Engine.
Generates local, 100% free offline audio ($0) and sentence-level line timings.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.io import wavfile

from curiosity_engine.config import KOKORO_DIR

logger = logging.getLogger("curiosity_engine.tts")

SR = 24000


def trim(x: np.ndarray, thr: float = 0.008) -> np.ndarray:
    """Cut leading/trailing silence so line start/end times are exact."""
    idx = np.where(np.abs(x) > thr)[0]
    if not len(idx):
        return x
    a = max(0, idx[0] - int(0.01 * SR))
    b = min(len(x), idx[-1] + int(0.03 * SR))
    return x[a:b]


def silences(x: np.ndarray, thr: float = 0.012, min_len: float = 0.06) -> List[Tuple[float, float]]:
    """Detect pauses inside speech: [(start_s, end_s)]."""
    hop = int(0.01 * SR)
    n = len(x) // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1))
    quiet = rms < thr * np.abs(x).max()
    out = []
    st = None
    for f, q in enumerate(quiet):
        if q and st is None:
            st = f
        if (not q or f == n - 1) and st is not None:
            if (f - st) * 0.01 >= min_len:
                out.append((st * 0.01, f * 0.01))
            st = None
    return out


def synthesize_narration(project_dir: Path) -> Path:
    """Read script.json in project_dir, synthesize narration.wav and data/lines.json."""
    script_path = project_dir / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing script.json in {project_dir}")

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    # Locate Kokoro ONNX model files
    onnx_path = KOKORO_DIR / "kokoro-v1.0.onnx"
    voices_path = KOKORO_DIR / "voices-v1.0.bin"

    if not onnx_path.exists():
        # Check system default
        alt_home = Path(os.environ.get("FACELESS_HOME", Path.home() / ".faceless-shorts")) / "kokoro"
        if (alt_home / "kokoro-v1.0.onnx").exists():
            onnx_path = alt_home / "kokoro-v1.0.onnx"
            voices_path = alt_home / "voices-v1.0.bin"

    if not onnx_path.exists():
        raise FileNotFoundError(f"Kokoro model not found at {onnx_path}")

    from kokoro_onnx import Kokoro
    kokoro = Kokoro(str(onnx_path), str(voices_path))

    voice = script.get("voice", "am_michael")
    speed = float(script.get("speed", 1.0))
    lang = "en-gb" if voice.startswith("b") else "en-us"

    def say(text: str) -> np.ndarray:
        samples, _ = kokoro.create(text, voice=voice, speed=speed, lang=lang)
        return trim(np.asarray(samples, dtype=np.float64))

    # Group lines into whole sentences
    groups: List[List[int]] = []
    cur: List[int] = []
    for i, ln in enumerate(script["lines"]):
        cur.append(i)
        if re.search(r'[.?!]["\')]*$', ln["text"].strip()) or ln.get("break") or i == len(script["lines"]) - 1:
            groups.append(cur)
            cur = []

    lead_sec = float(script.get("lead", 0.45))
    out_chunks = [np.zeros(int(lead_sec * SR))]
    t_cursor = len(out_chunks[0]) / SR
    lines_meta: List[Dict[str, Any]] = [None] * len(script["lines"])

    for g in groups:
        sentence_text = " ".join(script["lines"][i]["text"] for i in g)
        x = say(sentence_text)
        cuts = [0.0]

        if len(g) > 1:
            line_lens = np.array([len(say(script["lines"][i]["text"])) for i in g], dtype=float)
            total_lens = line_lens.sum() if line_lens.sum() > 0 else 1.0
            pauses = silences(x)
            for c in np.cumsum(line_lens)[:-1] / total_lens * len(x) / SR:
                near = [p for p in pauses if abs((p[0] + p[1]) / 2 - c) < 0.4]
                if near:
                    p = min(near, key=lambda p: abs((p[0] + p[1]) / 2 - c))
                    cuts.append((p[0], p[1]))
                else:
                    cuts.append((c, c))

        n_sec = len(x) / SR
        for j, i in enumerate(g):
            a = 0.0 if j == 0 else cuts[j][1]
            b = n_sec if j == len(g) - 1 else cuts[j + 1][0]
            lines_meta[i] = {
                "i": i,
                "text": script["lines"][i]["text"],
                "start": round(t_cursor + a, 3),
                "end": round(t_cursor + b, 3),
            }

        gap_sec = float(script["lines"][g[-1]].get("gap", script.get("gap", 0.32)))
        out_chunks.append(x)
        out_chunks.append(np.zeros(int(gap_sec * SR)))
        t_cursor += n_sec + gap_sec

    # Outro padding
    outro_sec = float(script.get("outro", 0.9))
    out_chunks.append(np.zeros(int(outro_sec * SR)))
    total_audio = np.concatenate(out_chunks)

    data_dir = project_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    wav_out = data_dir / "narration.wav"
    wavfile.write(str(wav_out), SR, (total_audio * 32767).astype(np.int16))

    lines_json_out = data_dir / "lines.json"
    with open(lines_json_out, "w", encoding="utf-8") as f:
        json.dump({"duration": round(len(total_audio) / SR, 3), "lines": lines_meta}, f, indent=2)

    logger.info(f"Synthesized {wav_out} ({round(len(total_audio) / SR, 2)}s, voice: {voice}).")
    return wav_out
