"""Copyright-free ambient underscore audio generator, transition SFX, and music selector."""
from __future__ import annotations

import random
import subprocess
import wave
from pathlib import Path
from typing import List, Optional

import numpy as np

from reelforge import config


def _pick_user_music() -> Optional[Path]:
    tracks = [
        p for p in config.MUSIC_DIR.glob("*")
        if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
    ]
    return random.choice(tracks) if tracks else None


def _overlay_beat_whooshes(
    mix: np.ndarray,
    sr: int,
    beat_cut_times: Optional[List[float]],
    seed: int,
) -> np.ndarray:
    """Layer subtle soft whoosh + harmonic ping accents on scene transitions."""
    if not beat_cut_times:
        return mix
    rng = np.random.default_rng(seed + 101)
    whoosh_len = int(0.18 * sr)
    t_w = np.linspace(0.0, 0.18, whoosh_len, endpoint=False, dtype=np.float32)
    env = np.sin(np.pi * (t_w / 0.18)) ** 2
    noise = rng.normal(0.0, 0.14, size=whoosh_len).astype(np.float32)
    # Smooth noise with 5-tap moving average for soft air whoosh
    kernel = np.ones(7, dtype=np.float32) / 7.0
    soft_noise = np.convolve(noise, kernel, mode="same")
    chime = 0.08 * np.sin(2.0 * np.pi * 520.0 * t_w) * np.exp(-t_w * 18.0)
    sfx = (soft_noise * env + chime).astype(np.float32)

    out = mix.copy()
    for cut_sec in beat_cut_times:
        start = int(max(0.0, cut_sec - 0.06) * sr)
        end = min(len(out), start + whoosh_len)
        if end > start:
            out[start:end] += sfx[: end - start]
    return out


def generate_ambient_underscore(
    duration_sec: float,
    out_wav: Path,
    seed: int = 42,
    beat_cut_times: Optional[List[float]] = None,
) -> Path:
    """Synthesize a warm, non-intrusive ambient pad + subtle scene-cut SFX in pure NumPy."""
    sr = 44100
    n_samples = max(sr, int(duration_sec * sr))
    t = np.linspace(0.0, duration_sec, n_samples, endpoint=False, dtype=np.float32)

    rng = np.random.default_rng(seed)
    root_freqs = [110.0, 98.0, 123.47, 130.81]
    f0 = float(rng.choice(root_freqs))
    # Gentle minor-9th ambient chord drone with slow breathing envelope
    lfo = 0.72 + 0.28 * np.sin(2.0 * np.pi * 0.14 * t)
    pad = (
        0.45 * np.sin(2.0 * np.pi * f0 * t)
        + 0.25 * np.sin(2.0 * np.pi * (f0 * 1.1892) * t)
        + 0.22 * np.sin(2.0 * np.pi * (f0 * 1.4983) * t)
        + 0.12 * np.sin(2.0 * np.pi * (f0 * 2.2449) * t)
    ) * lfo

    # Subtle rhythmic low pulse every ~1.25s for pacing
    pulse_env = np.exp(-((t % 1.25) * 4.5)).astype(np.float32)
    pulse = 0.16 * np.sin(2.0 * np.pi * (f0 * 0.5) * t) * pulse_env

    mix = _overlay_beat_whooshes((pad + pulse).astype(np.float32), sr, beat_cut_times, seed)

    fade_samples = min(n_samples // 4, int(1.2 * sr))
    if fade_samples > 0:
        fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        mix[:fade_samples] *= fade_in
        mix[-fade_samples:] *= fade_out

    peak = float(np.max(np.abs(mix))) or 1.0
    pcm = np.int16((mix / peak) * 0.25 * 32767.0)

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return out_wav


def prepare_background_music(
    duration_sec: float,
    out_wav: Path,
    seed: int = 42,
    beat_cut_times: Optional[List[float]] = None,
) -> Path:
    """Use user-supplied royalty-free track if present, otherwise synthesize clean ambient pad."""
    user_track = _pick_user_music()
    if user_track:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", str(user_track),
                "-t", f"{duration_sec:.3f}",
                "-ar", "44100", "-ac", "1",
                "-af", f"afade=t=in:d=1.0,afade=t=out:st={max(0.0, duration_sec - 1.2):.3f}:d=1.2",
                str(out_wav),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return out_wav
    return generate_ambient_underscore(duration_sec, out_wav, seed=seed, beat_cut_times=beat_cut_times)
