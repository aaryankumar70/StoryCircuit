"""Small deterministic procedural sound bed and narration-aware SFX mixer."""
from __future__ import annotations

import json
import math
import sys
import wave
from pathlib import Path

import numpy as np


def _read_pcm(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported narration PCM sample width: {width} bytes")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return rate, samples


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    size = round(len(samples) * target_rate / source_rate)
    old = np.arange(len(samples), dtype=np.float64) / source_rate
    new = np.arange(size, dtype=np.float64) / target_rate
    return np.interp(new, old, samples).astype(np.float32)


def _rms_envelope(samples: np.ndarray, rate: int, block_ms: int = 20) -> np.ndarray:
    block = max(1, rate * block_ms // 1000)
    padded = np.pad(samples, (0, (-len(samples)) % block))
    rms = np.sqrt(np.mean(padded.reshape(-1, block) ** 2, axis=1) + 1e-9)
    centers = (np.arange(len(rms)) + 0.5) * block / rate
    times = np.arange(len(samples)) / rate
    return np.interp(times, centers, rms, left=rms[0], right=rms[-1]).astype(np.float32)


def _event(track: np.ndarray, rate: int, at: float, kind: str, gain: float, rng: np.random.Generator) -> None:
    start = max(0, int(at * rate))
    if start >= len(track):
        return
    seconds = 0.85 if kind == "whoosh" else 0.62 if kind == "bell" else 0.42
    count = min(len(track) - start, int(seconds * rate))
    if count <= 0:
        return
    t = np.arange(count, dtype=np.float32) / rate
    decay = np.exp(-t * (3.3 if kind == "whoosh" else 5.5))
    if kind == "bell":
        tone = np.sin(2 * math.pi * 740 * t) + 0.48 * np.sin(2 * math.pi * 1110 * t)
    elif kind == "sparkle":
        tone = np.sin(2 * math.pi * (960 + 360 * np.sin(t * 12)) * t) + 0.35 * np.sin(2 * math.pi * 1530 * t)
    elif kind == "impact":
        tone = np.sin(2 * math.pi * (72 + 160 * np.exp(-t * 15)) * t) + 0.25 * rng.standard_normal(count)
    elif kind == "whoosh":
        noise = rng.standard_normal(count).astype(np.float32)
        smooth = np.convolve(noise, np.ones(85, dtype=np.float32) / 85, mode="same")
        tone = 0.8 * noise + 2.4 * smooth + 0.35 * np.sin(2 * math.pi * (260 - 170 * t / seconds) * t)
    else:
        tone = np.sin(2 * math.pi * 190 * t) + 0.22 * np.sin(2 * math.pi * 380 * t)
    track[start:start + count] += (tone * decay * min(0.45, max(0.0, gain)) * 0.12).astype(np.float32)


def mix(project: Path) -> Path:
    data = project / "data"
    source = data / "narration.wav"
    cues_file = data / "cues.json"
    if not source.is_file():
        raise FileNotFoundError(f"Narration WAV is missing: {source}")
    source_rate, speech_source = _read_pcm(source)
    rate = 48_000
    speech = _resample(speech_source, source_rate, rate)
    duration = len(speech) / rate
    if not 5 <= duration <= 75:
        raise ValueError(f"Narration duration {duration:.1f}s is outside the 5-75s mixer safety bound")
    env = _rms_envelope(speech, rate)
    duck = 1.0 / (1.0 + 4.2 * env)
    time_axis = np.arange(len(speech), dtype=np.float32) / rate
    pad = (np.sin(2 * math.pi * 110 * time_axis) + 0.55 * np.sin(2 * math.pi * 164.8 * time_axis)) * 0.012
    pad *= np.minimum(1.0, time_axis / 0.35) * np.minimum(1.0, np.maximum(0.0, (duration - time_axis) / 0.6))
    effects = np.zeros_like(speech)
    cues = json.loads(cues_file.read_text(encoding="utf-8")).get("cues", []) if cues_file.exists() else []
    rng = np.random.default_rng(1757)
    for cue in cues[:400]:
        _event(effects, rate, max(0.0, float(cue.get("t", 0))), str(cue.get("type", "soft_hit")), float(cue.get("gain", 0.22)), rng)
    mixed = speech + pad * duck + effects * (0.8 + 0.2 * duck)
    peak = float(np.max(np.abs(mixed))) if len(mixed) else 0.0
    if peak > 0.96:
        mixed *= 0.96 / peak
    stereo = np.column_stack((mixed, mixed)).astype(np.float32)
    output = data / "mix.wav"
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(rate)
        wav.writeframes((np.clip(stereo, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    print(f"Mixed {len(cues)} story cues into {output.name}: {duration:.2f}s, 48 kHz stereo")
    return output


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tools/mix.py PROJECT_DIR")
    mix(Path(sys.argv[1]))
