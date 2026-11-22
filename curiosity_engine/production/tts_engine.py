"""Kokoro-82M ONNX Text-to-Speech Engine for Curiosity Engine.
Generates local, 100% free offline audio ($0) and sentence-level line timings.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.io import wavfile

from curiosity_engine.config import KOKORO_DIR, MAX_DURATION_SEC, MAX_WORD_COUNT
from curiosity_engine.generation.resource_lock import sequential_resource_stage

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


@sequential_resource_stage
def synthesize_narration(project_dir: Path) -> Path:
    """Read script.json in project_dir, synthesize narration.wav and data/lines.json."""
    script_path = project_dir / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing script.json in {project_dir}")

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    lines = script.get("lines") or []
    if not isinstance(lines, list) or not lines or len(lines) > 60:
        raise ValueError("Narration must contain between 1 and 60 lines.")
    word_count = sum(len(re.findall(r"\b[\w’'-]+\b", str(line.get("text") or ""))) for line in lines if isinstance(line, dict))
    if word_count > MAX_WORD_COUNT:
        raise ValueError(f"Narration contains {word_count} words; the Shorts limit is {MAX_WORD_COUNT}.")
    if any(not isinstance(line, dict) or len(str(line.get("text") or "")) > 1200 for line in lines):
        raise ValueError("Narration lines must be objects no longer than 1,200 characters.")

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

    from curiosity_engine.production.narration_director import (
        get_storytelling_delivery_plan,
        smooth_storytelling_text,
    )

    voice = script.get("voice", "am_michael")
    try:
        base_speed = float(script.get("speed", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Narration speed must be numeric.") from exc
    if not 0.75 <= base_speed <= 1.35:
        raise ValueError("Narration speed must stay between 0.75x and 1.35x for intelligible local speech.")
    lang = "en-gb" if voice.startswith("b") else "en-us"
    use_storytelling = bool(script.get("storytelling_delivery", True))

    delivery_plan = get_storytelling_delivery_plan(
        lines, base_speed=base_speed, enable_storytelling=use_storytelling
    )

    def say(text: str, custom_speed: Optional[float] = None) -> np.ndarray:
        s = custom_speed or base_speed
        samples, _ = kokoro.create(text, voice=voice, speed=s, lang=lang)
        return trim(np.asarray(samples, dtype=np.float64))

    # Group lines into whole sentences
    groups: List[List[int]] = []
    cur: List[int] = []
    for i, ln in enumerate(lines):
        cur.append(i)
        if re.search(r'[.?!]["\')]*$', ln["text"].strip()) or ln.get("break") or i == len(lines) - 1:
            groups.append(cur)
            cur = []

    lead_sec = float(script.get("lead", 0.45))
    if not 0 <= lead_sec <= 1.5:
        raise ValueError("Narration lead padding must be between 0 and 1.5 seconds.")
    out_chunks = [np.zeros(int(lead_sec * SR))]
    t_cursor = len(out_chunks[0]) / SR
    lines_meta: List[Dict[str, Any]] = [None] * len(lines)

    for g in groups:
        first_idx = g[0]
        last_idx = g[-1]
        plan_item = delivery_plan[first_idx]
        group_speed = plan_item["speed"]
        pre_pause = plan_item.get("pre_pause_sec", 0.0)

        # Insert pre-pause breath before major reveal/twist
        if pre_pause > 0.0:
            out_chunks.append(np.zeros(int(pre_pause * SR)))
            t_cursor += pre_pause

        sentence_text = " ".join(smooth_storytelling_text(lines[i]["text"]) for i in g)
        x = say(sentence_text, custom_speed=group_speed)
        cuts = [0.0]

        if len(g) > 1:
            line_lens = np.array([len(say(smooth_storytelling_text(lines[i]["text"]), custom_speed=group_speed)) for i in g], dtype=float)
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
                "text": lines[i]["text"],
                "start": round(t_cursor + a, 3),
                "end": round(t_cursor + b, 3),
                "delivery_mode": delivery_plan[i]["mode"],
                "speed": delivery_plan[i]["speed"],
            }

        gap_sec = float(delivery_plan[last_idx].get("gap_sec") or lines[last_idx].get("gap", script.get("gap", 0.30)))
        if not 0 <= gap_sec <= 1.25:
            raise ValueError("Narration pauses must be between 0 and 1.25 seconds per spoken group.")
        out_chunks.append(x)
        out_chunks.append(np.zeros(int(gap_sec * SR)))
        t_cursor += n_sec + gap_sec

    # Outro padding
    outro_sec = float(script.get("outro", 0.9))
    if not 0 <= outro_sec <= 2.0:
        raise ValueError("Narration outro padding must be between 0 and 2 seconds.")
    out_chunks.append(np.zeros(int(outro_sec * SR)))
    total_audio = np.concatenate(out_chunks)
    duration_sec = len(total_audio) / SR
    if duration_sec > MAX_DURATION_SEC:
        raise ValueError(f"Synthesized narration is {duration_sec:.1f}s, above the configured 180-second TTS safety limit.")

    data_dir = project_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    wav_out = data_dir / "narration.wav"
    wavfile.write(str(wav_out), SR, (total_audio * 32767).astype(np.int16))

    lines_json_out = data_dir / "lines.json"
    with open(lines_json_out, "w", encoding="utf-8") as f:
        json.dump({"duration": round(duration_sec, 3), "lines": lines_meta}, f, indent=2)

    logger.info(f"Synthesized {wav_out} ({round(duration_sec, 2)}s, voice: {voice}).")
    return wav_out
