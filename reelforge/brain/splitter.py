"""Smart long-script analyzer and balanced 1-to-2-minute Shorts splitter."""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Tuple

from reelforge.brain.metadata import build_youtube_tags, clean_youtube_title

# Calibrated to Edge-TTS (en-US-AndrewNeural, +4% rate) + 0.16s inter-beat gap + 0.45s tail
WORDS_PER_SECOND = 2.55
BEAT_GAP_SEC = 0.16
TAIL_PAD_SEC = 0.45

MIN_SHORT_SPLIT_SEC = 62.0
MAX_SHORT_SPLIT_SEC = 114.0
TARGET_SHORT_SPLIT_SEC = 86.0


def _split_paragraphs_and_units(script_text: str) -> List[Dict[str, Any]]:
    """Parse script into sentence units while preserving [Speaker]: tags and paragraph breaks."""
    paragraphs = [p.strip() for p in re.split(r"\r?\n\s*\r?\n+", (script_text or "").strip()) if p.strip()]
    units: List[Dict[str, Any]] = []

    for p_idx, para in enumerate(paragraphs):
        lines = [ln.strip() for ln in re.split(r"[\r\n]+", para) if ln.strip()]
        for l_idx, line in enumerate(lines):
            speaker_prefix = ""
            body = line
            m = re.match(r"^(\[?[A-Za-z][A-Za-z0-9 _-]{0,20}\]?\s*:)\s*(.+)$", line)
            if m:
                speaker_prefix = m.group(1).strip() + " "
                body = m.group(2).strip()

            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
            if not sentences:
                sentences = [body]

            for s_idx, sent in enumerate(sentences):
                words = sent.split()
                # If a single sentence has no punctuation and > 60 words, split gently at commas/clauses
                if len(words) > 60:
                    clauses = [c.strip() for c in re.split(r"(?<=[,;])\s+", sent) if c.strip()]
                    sub_chunks: List[str] = []
                    cur_w: List[str] = []
                    for cl in clauses:
                        cw = cl.split()
                        if cur_w and len(cur_w) + len(cw) > 35:
                            sub_chunks.append(" ".join(cur_w))
                            cur_w = cw
                        else:
                            cur_w.extend(cw)
                    if cur_w:
                        sub_chunks.append(" ".join(cur_w))
                    sub_sents = sub_chunks or [sent]
                else:
                    sub_sents = [sent]

                for ss_idx, sub in enumerate(sub_sents):
                    rendered = f"{speaker_prefix}{sub}" if (speaker_prefix and s_idx == 0 and ss_idx == 0) else (
                        f"{speaker_prefix}{sub}" if speaker_prefix else sub
                    )
                    w_count = len(sub.split())
                    is_para_end = (l_idx == len(lines) - 1) and (s_idx == len(sentences) - 1) and (ss_idx == len(sub_sents) - 1)
                    units.append({
                        "raw": rendered,
                        "spoken": sub,
                        "words": w_count,
                        "para_index": p_idx,
                        "ends_paragraph": is_para_end,
                    })
    return units


def estimate_spoken_duration_sec(script_text: str, beat_count: int | None = None) -> float:
    """Estimate realistic Edge-TTS spoken duration in seconds."""
    units = _split_paragraphs_and_units(script_text) if beat_count is None else []
    words = sum(u["words"] for u in units) if units else len(re.findall(r"\S+", script_text or ""))
    beats = beat_count if beat_count is not None else max(1, len(units))
    if words <= 0:
        return 0.0
    return round((words / WORDS_PER_SECOND) + max(0, beats - 1) * BEAT_GAP_SEC + TAIL_PAD_SEC, 2)


def _chunk_duration(units: List[Dict[str, Any]], start: int, end: int) -> float:
    w = sum(units[i]["words"] for i in range(start, end))
    b = max(1, end - start)
    return (w / WORDS_PER_SECOND) + max(0, b - 1) * BEAT_GAP_SEC + TAIL_PAD_SEC


def _partition_units_dp(
    units: List[Dict[str, Any]],
    k: int,
    target_sec: float,
    min_sec: float,
    max_sec: float,
) -> Tuple[float, List[Tuple[int, int]]]:
    """Find the lowest-cost balanced split of `units` into `k` contiguous parts."""
    n = len(units)
    if k <= 1 or n <= 1:
        return 0.0, [(0, n)]

    prefix_words = [0] * (n + 1)
    for i, u in enumerate(units):
        prefix_words[i + 1] = prefix_words[i] + u["words"]

    def seg_dur(i: int, j: int) -> float:
        w = prefix_words[j] - prefix_words[i]
        b = max(1, j - i)
        return (w / WORDS_PER_SECOND) + max(0, b - 1) * BEAT_GAP_SEC + TAIL_PAD_SEC

    inf = 1e15
    dp = [[inf] * (n + 1) for _ in range(k + 1)]
    parent = [[-1] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0.0

    for p in range(1, k + 1):
        for j in range(p, n - (k - p) + 1):
            for i in range(p - 1, j):
                if dp[p - 1][i] >= inf:
                    continue
                dur = seg_dur(i, j)
                # Penalize parts outside [min_sec, max_sec] heavily, prefer paragraph breaks
                penalty = (dur - target_sec) ** 2
                if dur < min_sec:
                    penalty += 5000.0 + (min_sec - dur) * 400.0
                if dur > max_sec:
                    penalty += 8000.0 + (dur - max_sec) * 500.0
                if p < k and not units[j - 1]["ends_paragraph"]:
                    penalty += 18.0
                cost = dp[p - 1][i] + penalty
                if cost < dp[p][j]:
                    dp[p][j] = cost
                    parent[p][j] = i

    if dp[k][n] >= inf:
        return inf, [(0, n)]

    bounds: List[Tuple[int, int]] = []
    cur = n
    for p in range(k, 0, -1):
        prev = parent[p][cur]
        bounds.append((prev, cur))
        cur = prev
    bounds.reverse()
    return dp[k][n], bounds


def analyze_and_split_script(
    script_text: str,
    *,
    base_title: str = "",
    category: str = "story",
    min_part_sec: float = MIN_SHORT_SPLIT_SEC,
    max_part_sec: float = MAX_SHORT_SPLIT_SEC,
    target_part_sec: float = TARGET_SHORT_SPLIT_SEC,
) -> Dict[str, Any]:
    """Analyze a script and split long scripts into balanced 1-to-2-minute YouTube Shorts parts."""
    clean_text = (script_text or "").strip()
    units = _split_paragraphs_and_units(clean_text)
    total_words = sum(u["words"] for u in units)
    total_est_sec = round(_chunk_duration(units, 0, len(units)), 1) if units else 0.0

    if not units or total_words == 0:
        return {
            "total_words": 0,
            "estimated_total_sec": 0.0,
            "possible_videos": 0,
            "exceeds_short_limit": False,
            "recommended_format": "short",
            "parts": [],
        }

    exceeds_short = total_est_sec > 120.0
    inferred_base = (base_title or "").strip() or " ".join(units[0]["spoken"].split()[:7]).rstrip(".,!?;:")

    if total_est_sec <= max_part_sec or len(units) == 1:
        bounds = [(0, len(units))]
    else:
        min_k = max(2, math.ceil(total_est_sec / max_part_sec))
        max_k = max(min_k, min(len(units), math.floor(total_est_sec / min_part_sec)))
        best_cost = 1e18
        best_bounds = [(0, len(units))]
        for k in range(min_k, max_k + 1):
            cost, cand_bounds = _partition_units_dp(units, k, target_part_sec, min_part_sec, max_part_sec)
            if cost < best_cost:
                best_cost = cost
                best_bounds = cand_bounds
        bounds = best_bounds

    parts: List[Dict[str, Any]] = []
    total_parts = len(bounds)
    for idx, (s_i, e_i) in enumerate(bounds, start=1):
        chunk_units = units[s_i:e_i]
        chunk_script = "\n".join(u["raw"] for u in chunk_units)
        chunk_spoken = " ".join(u["spoken"] for u in chunk_units)
        chunk_words = sum(u["words"] for u in chunk_units)
        est_sec = round(_chunk_duration(units, s_i, e_i), 1)

        if total_parts > 1:
            part_title = f"{inferred_base[:66].rstrip()} (Part {idx}/{total_parts})"
        else:
            part_title = inferred_base[:84].rstrip()

        hook_line = chunk_units[0]["spoken"]
        desc_lines = [
            f"{part_title} — {hook_line}",
            "",
            f"Part {idx} of {total_parts} in this series." if total_parts > 1 else "Watch till the end for the full story.",
            "Subscribe and drop your thoughts in the comments!",
            "",
            "#Shorts #StoryCircuit",
        ]
        tags = build_youtube_tags(
            title=part_title,
            category=category,
            script=chunk_spoken,
            extra_tags=[f"part {idx}"] if total_parts > 1 else [],
            is_long=False,
        )
        parts.append({
            "part_number": idx,
            "total_parts": total_parts,
            "title": clean_youtube_title(part_title, is_long=False).replace(" #Shorts", ""),
            "script": chunk_script,
            "word_count": chunk_words,
            "estimated_duration_sec": est_sec,
            "preview": hook_line[:130],
            "description": "\n".join(desc_lines),
            "tags": tags,
        })

    return {
        "total_words": total_words,
        "estimated_total_sec": total_est_sec,
        "possible_videos": len(parts),
        "exceeds_short_limit": exceeds_short,
        "recommended_format": "long" if exceeds_short else "short",
        "parts": parts,
    }
