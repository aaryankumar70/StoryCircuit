"""Narration Storytelling Direction Engine for CurioLoop.

Transforms flat text-to-speech delivery into engaging, human-paced storytelling:
1. Dynamic beat classification (hook, exposition, suspense, revelation, climax, ending).
2. Dynamic pacing & speed modulation per narrative beat.
3. Calibrated dramatic pauses before reveals and twists.
4. Text cadence smoothing (punctuation, dramatic breath marks).
5. Full backwards compatibility with standard/default voice settings for easy rollback.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("curiosity_engine.narration_director")

# Narrative beat modes
MODE_HOOK = "hook"
MODE_EXPOSITION = "exposition"
MODE_SUSPENSE = "suspense"
MODE_REVELATION = "revelation"
MODE_CLIMAX = "climax"
MODE_ENDING = "ending"

# Calibrated speed profiles per narrative mode (baseline speed multiplier)
BEAT_SPEED_MAP = {
    MODE_HOOK: 1.03,         # Punchy, energetic opening to capture viewer retention in 0-3s
    MODE_EXPOSITION: 0.98,   # Grounded, authoritative documentary exposition
    MODE_SUSPENSE: 0.94,     # Slower, tensioned, deliberate build-up
    MODE_REVELATION: 0.92,   # Dramatic slowdown for the core discovery / twist
    MODE_CLIMAX: 0.95,       # High-stakes payoff delivery
    MODE_ENDING: 0.96,       # Philosophical, lingering final sentence
}

# Calibrated pause gaps (seconds of silence after the sentence)
BEAT_GAP_MAP = {
    MODE_HOOK: 0.22,         # Tight gap after hook to maintain immediate momentum
    MODE_EXPOSITION: 0.28,   # Standard breath pause
    MODE_SUSPENSE: 0.36,     # Calibrated pause building anticipation
    MODE_REVELATION: 0.48,   # Significant dramatic pause after revelation
    MODE_CLIMAX: 0.40,       # Climax impact pause
    MODE_ENDING: 0.85,       # Lingering outro pause
}

# Calibrated dramatic pre-pause (breath silence inserted BEFORE a twist/reveal)
BEAT_PRE_PAUSE_MAP = {
    MODE_REVELATION: 0.25,   # Breath silence before the reveal
    MODE_CLIMAX: 0.15,
}

# Keywords indicating suspense, revelation, climax, or ending
SUSPENSE_KEYWORDS = {
    "suddenly", "strange", "bizarre", "anomalous", "unexplained", "vanished",
    "impossible", "silence", "shadow", "unknown", "creepy", "dark", "alarm",
    "warning", "whisper", "shivering", "chilling", "eerie", "dread", "frozen"
}

REVELATION_KEYWORDS = {
    "discovered", "revealed", "truth", "found", "shocking", "turned out",
    "realized", "uncovered", "secret", "exposed", "evidence shows", "finally",
    "actually", "instead", "nobody knew", "inside", "origin"
}

CLIMAX_KEYWORDS = {
    "exploded", "surged", "collapsed", "shattered", "never seen again",
    "final", "last stand", "fatal", "erupted", "destruction", "unsealed"
}


def smooth_storytelling_text(text: str) -> str:
    """Prepare raw script text for natural speech synthesis without awkward robotic glitches.
    - Replaces multiple dots / ellipses with a clean pause comma
    - Replaces em-dashes and hyphens with natural breathing punctuation
    - Expands problematic abbreviations
    """
    s = text.strip()
    # Normalize ellipses to comma + space for natural breath
    s = re.sub(r"\.{2,}", ", ", s)
    # Normalize em-dashes / en-dashes
    s = re.sub(r"\s*[—–]\s*", ", ", s)
    # Remove stray quotes that confuse phonemizer
    s = re.sub(r'["“”]', "", s)
    # Smooth common acronyms/abbreviations
    s = re.sub(r"\bBC\b", "B C", s)
    s = re.sub(r"\bAD\b", "A D", s)
    s = re.sub(r"\bkm/h\b", "kilometers per hour", s, flags=re.IGNORECASE)
    s = re.sub(r"\bmph\b", "miles per hour", s, flags=re.IGNORECASE)
    # Clean redundant whitespace
    return re.sub(r"\s+", " ", s).strip()


def classify_sentence_beat(
    sentence_idx: int,
    total_sentences: int,
    text: str,
    scene_descriptor: Optional[Dict[str, Any]] = None,
) -> str:
    """Classify a sentence into its narrative storytelling mode."""
    if sentence_idx == 0:
        return MODE_HOOK

    if sentence_idx == total_sentences - 1:
        return MODE_ENDING

    text_lower = text.lower()
    vt = (scene_descriptor or {}).get("visual_type", "")
    mood = (scene_descriptor or {}).get("mood", "")

    # Check for climax
    if (
        sentence_idx >= total_sentences - 2
        and (vt in ("payoff_reveal", "meter_surge") or any(k in text_lower for k in CLIMAX_KEYWORDS))
    ):
        return MODE_CLIMAX

    # Check for revelation / twist
    if (
        vt in ("payoff_reveal", "vault_mystery")
        or any(k in text_lower for k in REVELATION_KEYWORDS)
        or mood == "wonder"
    ):
        return MODE_REVELATION

    # Check for suspense
    if (
        vt in ("radar_scan", "tension_room")
        or mood in ("tense", "urgent", "mystery")
        or any(k in text_lower for k in SUSPENSE_KEYWORDS)
    ):
        return MODE_SUSPENSE

    # Default middle sentences to exposition
    return MODE_EXPOSITION


def get_storytelling_delivery_plan(
    lines: List[Dict[str, Any]],
    base_speed: float = 1.0,
    enable_storytelling: bool = True,
) -> List[Dict[str, Any]]:
    """Generate per-sentence storytelling modulation parameters.
    
    If enable_storytelling is False, preserves default flat delivery for rollback.
    """
    total = len(lines)
    plan: List[Dict[str, Any]] = []

    for i, ln in enumerate(lines):
        text = str(ln.get("text", "")).strip()
        smoothed = smooth_storytelling_text(text)
        scene = ln.get("scene") or {}

        if not enable_storytelling:
            # Fallback / baseline mode
            plan.append({
                "line_idx": i,
                "mode": "standard",
                "text": text,
                "smoothed_text": smoothed,
                "speed": base_speed,
                "gap_sec": float(ln.get("gap", 0.32)),
                "pre_pause_sec": 0.0,
            })
            continue

        beat_mode = classify_sentence_beat(i, total, text, scene)
        speed_mult = BEAT_SPEED_MAP.get(beat_mode, 1.0)
        target_speed = round(base_speed * speed_mult, 3)
        gap_sec = float(ln.get("gap") or BEAT_GAP_MAP.get(beat_mode, 0.30))
        pre_pause_sec = BEAT_PRE_PAUSE_MAP.get(beat_mode, 0.0)

        plan.append({
            "line_idx": i,
            "mode": beat_mode,
            "text": text,
            "smoothed_text": smoothed,
            "speed": target_speed,
            "gap_sec": gap_sec,
            "pre_pause_sec": pre_pause_sec,
        })

    return plan
