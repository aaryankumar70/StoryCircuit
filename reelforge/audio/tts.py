"""Per-beat TTS synthesis using Edge-TTS with exact WordBoundary timestamps."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Tuple

import edge_tts

from reelforge import config
from reelforge.models import StoryPlan, WordTiming

logger = logging.getLogger("reelforge.audio.tts")

BEAT_GAP_SEC = 0.16


def _probe_duration(audio_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
    return max(0.2, float((res.stdout or "0").strip() or 0.2))


async def _synth_beat_edge(
    text: str,
    voice: str,
    rate: str,
    out_mp3: Path,
) -> List[WordTiming]:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, boundary="WordBoundary")
    timings: List[WordTiming] = []
    with open(out_mp3, "wb") as f:
        async for chunk in communicate.stream():
            ctype = chunk.get("type")
            if ctype == "audio":
                f.write(chunk["data"])
            elif ctype == "WordBoundary":
                # Edge-TTS offset and duration are in 100-nanosecond ticks
                start_s = float(chunk.get("offset", 0)) / 10_000_000.0
                dur_s = max(0.06, float(chunk.get("duration", 0)) / 10_000_000.0)
                word_txt = str(chunk.get("text", "")).strip()
                if word_txt:
                    timings.append(WordTiming(word=word_txt, start_sec=start_s, end_sec=start_s + dur_s))
    return timings


def _fallback_proportional_timings(text: str, start_offset: float, duration: float, speaker: str) -> List[WordTiming]:
    words = [w for w in text.split() if w.strip()]
    if not words:
        return []
    weights = [max(2, len(w.strip(".,!?;:\"'"))) for w in words]
    total_w = sum(weights)
    cursor = start_offset
    usable = max(0.2, duration - 0.04)
    out: List[WordTiming] = []
    for w, wt in zip(words, weights):
        seg = usable * (wt / total_w)
        out.append(WordTiming(word=w, start_sec=round(cursor, 3), end_sec=round(cursor + seg, 3), speaker=speaker))
        cursor += seg
    return out


def _synth_beat_espeak(text: str, out_wav: Path) -> None:
    subprocess.run(
        ["espeak-ng", "-s", "155", "-w", str(out_wav), text],
        check=True,
        capture_output=True,
        timeout=30,
    )


def synthesize_story_audio(
    plan: StoryPlan,
    work_dir: Path,
) -> Tuple[Path, List[WordTiming], float]:
    """Synthesize every beat individually so beat visuals lock 1:1 to spoken audio.

    Returns (narration_wav_path, word_timings, total_duration_sec).
    """
    audio_dir = work_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    beat_wavs: List[Path] = []
    all_words: List[WordTiming] = []
    cursor_sec = 0.0

    # Generate short silence gap wav once
    gap_wav = audio_dir / "gap.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{BEAT_GAP_SEC:.3f}",
            str(gap_wav),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )

    for idx, beat in enumerate(plan.beats):
        voice = config.TTS_VOICE_SECONDARY if beat.speaker == "secondary" else config.TTS_VOICE_PRIMARY
        raw_mp3 = audio_dir / f"beat_{idx:02d}.mp3"
        beat_wav = audio_dir / f"beat_{idx:02d}.wav"

        raw_words: List[WordTiming] = []
        used_edge = False
        if config.TTS_ENGINE == "edge":
            try:
                raw_words = asyncio.run(_synth_beat_edge(beat.text, voice, config.TTS_RATE, raw_mp3))
                if raw_mp3.exists() and raw_mp3.stat().st_size > 500:
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", str(raw_mp3), "-ar", "44100", "-ac", "1", str(beat_wav)],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    used_edge = True
            except Exception as exc:
                logger.warning("Edge-TTS failed on beat %s (%s); trying espeak-ng fallback.", idx, exc)

        if not used_edge:
            _synth_beat_espeak(beat.text, beat_wav)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(beat_wav), "-ar", "44100", "-ac", "1", str(beat_wav.with_suffix(".norm.wav"))],
                check=True,
                capture_output=True,
                timeout=30,
            )
            beat_wav.with_suffix(".norm.wav").replace(beat_wav)

        dur = _probe_duration(beat_wav)
        beat.start_sec = round(cursor_sec, 3)

        if raw_words:
            for wt in raw_words:
                s = round(cursor_sec + min(wt.start_sec, max(0.0, dur - 0.05)), 3)
                e = round(cursor_sec + min(wt.end_sec, dur), 3)
                if e <= s:
                    e = round(s + 0.08, 3)
                all_words.append(WordTiming(word=wt.word, start_sec=s, end_sec=e, speaker=beat.speaker))
        else:
            all_words.extend(_fallback_proportional_timings(beat.text, cursor_sec, dur, beat.speaker))

        beat_wavs.append(beat_wav)
        cursor_sec += dur
        if idx < len(plan.beats) - 1:
            beat_wavs.append(gap_wav)
            cursor_sec += BEAT_GAP_SEC
        beat.end_sec = round(cursor_sec, 3)

    # Pad tail slightly for clean ending breath
    tail_wav = audio_dir / "tail.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.45", str(tail_wav)],
        check=True,
        capture_output=True,
        timeout=20,
    )
    beat_wavs.append(tail_wav)
    cursor_sec += 0.45
    if plan.beats:
        plan.beats[-1].end_sec = round(cursor_sec, 3)

    concat_txt = audio_dir / "concat.txt"
    concat_txt.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in beat_wavs),
        encoding="utf-8",
    )
    narration_wav = audio_dir / "narration.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c:a", "pcm_s16le", str(narration_wav)],
        check=True,
        capture_output=True,
        timeout=60,
    )

    total_dur = _probe_duration(narration_wav)
    if plan.beats:
        plan.beats[-1].end_sec = round(total_dur, 3)

    words_json = work_dir / "words.json"
    words_json.write_text(
        json.dumps([w.model_dump() for w in all_words], indent=2),
        encoding="utf-8",
    )
    return narration_wav, all_words, total_dur
