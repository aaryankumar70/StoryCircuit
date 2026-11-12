"""Storytelling Scriptwriter for CurioLoop.

Supports 20-60s narration scripts (preferred target 25-45s, ~62-115 spoken words,
strict ceiling <= 145 words). Enforces retention narrative structure:
  - Opening (0-3s): Immediate curiosity hook (never generic "Did you know?")
  - Development: Progressive information reveal with narrative momentum
  - Curiosity & Suspense: Unanswered tension / meaningful turn before payoff
  - Ending: Satisfying, memorable resolution

Also generates narration-matched visual `scene` directives per cut line and
provides `revise_script_for_duration` for targeted QC duration recovery.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from curiosity_engine.config import (
    MAX_DURATION_SEC,
    MAX_WORD_COUNT,
    MIN_DURATION_SEC,
    MIN_WORD_COUNT,
    TARGET_DURATION_MAX_SEC,
    TARGET_DURATION_MIN_SEC,
    TARGET_WORD_COUNT_MAX,
    TARGET_WORD_COUNT_MIN,
    VOICE_MAP,
)
from curiosity_engine.content.curated_fallback import CURATED_TOPICS
from curiosity_engine.content.gemini_client import gemini_client

logger = logging.getLogger("curiosity_engine.scriptwriter")


TRUSTED_DOMAINS = [
    "ncbi.nlm.nih.gov",
    "sciencedirect.com",
    "nature.com",
    "science.org",
    "oxrep.ox.ac.uk",
    "unesco.org",
    "franckgoddio.org",
    "nasa.gov",
    "esa.int",
    "britannica.com",
    "wikipedia.org",
    "si.edu",
    "smithsonianmag.com",
    "nationalgeographic.com",
    "scientificamerican.com",
    "planetary.org",
    "arxiv.org",
]

VISUAL_TYPES = (
    "tension_room",
    "radar_scan",
    "archive_map",
    "timeline",
    "neural_pulse",
    "meter_surge",
    "cosmic_burst",
    "ocean_depth",
    "vault_mystery",
    "split_compare",
    "micro_stream",
    "payoff_reveal",
)


def validate_factual_sources(sources: List[str]) -> Tuple[bool, List[str]]:
    """Validate that internal source URLs are well-formed and from reputable domains."""
    valid_sources: List[str] = []
    for s in sources:
        if not s or not isinstance(s, str):
            continue
        s_clean = s.strip()
        parsed = urlparse(s_clean)
        if not (parsed.scheme in ("http", "https") and parsed.netloc):
            continue

        netloc = parsed.netloc.lower()
        is_trusted = (
            any(td in netloc for td in TRUSTED_DOMAINS)
            or netloc.endswith(".edu")
            or netloc.endswith(".gov")
            or netloc.endswith(".org")
        )
        if is_trusted:
            valid_sources.append(s_clean)

    return len(valid_sources) >= 1, valid_sources


def count_spoken_words(lines: List[Dict[str, Any]]) -> int:
    """Accurately count spoken words across all script lines."""
    total = 0
    for line in lines:
        words = [w for w in str(line.get("text", "")).split() if re.sub(r"[^a-zA-Z0-9]", "", w)]
        total += len(words)
    return total


def format_auto_caps(text: str) -> str:
    """Generate clean uppercase caption chunks with one emphasized (*) word per chunk."""
    words = text.strip().split()
    if not words:
        return ""
    chunks = []
    i = 0
    while i < len(words):
        chunk_len = min(3, len(words) - i)
        chunk_words = words[i:i + chunk_len]
        clean_words = [re.sub(r"[^a-zA-Z0-9]", "", w) for w in chunk_words]
        longest_idx = max(range(len(clean_words)), key=lambda idx: len(clean_words[idx]))

        formatted_words = []
        for idx, w in enumerate(chunk_words):
            upper_w = w.upper()
            if idx == longest_idx and not upper_w.startswith("*"):
                formatted_words.append(f"*{upper_w}")
            else:
                formatted_words.append(upper_w)
        chunks.append(" ".join(formatted_words))
        i += chunk_len
    return " | ".join(chunks)


def _infer_line_scene(
    text: str,
    idx: int,
    total_lines: int,
    prev_visual_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Derive a narration-matched non-repetitive visual scene descriptor from line semantics."""
    low = text.lower()
    if idx == 0:
        default_vt = "cosmic_burst" if any(k in low for k in ("space", "sun", "star", "storm", "plane", "signal")) else (
            "ocean_depth" if any(k in low for k in ("ocean", "sea", "ship", "arctic", "shark", "water")) else "tension_room"
        )
        mood = "mystery"
        accent = "yellow"
        cue = "whoosh"
    elif idx == total_lines - 1:
        default_vt = "payoff_reveal"
        mood = "calm"
        accent = "green"
        cue = "sparkle"
    elif any(k in low for k in ("map", "city", "egypt", "jungle", "river", "port", "island", "portugal", "mile")):
        default_vt = "archive_map"
        mood = "mystery"
        accent = "yellow"
        cue = "pop"
    elif any(k in low for k in ("century", "year", "eighteen", "nineteen", "two thousand", "day", "hour", "decade", "ago", "time")):
        default_vt = "timeline"
        mood = "wonder"
        accent = "crimson"
        cue = "tock"
    elif any(k in low for k in ("ocean", "sea", "dive", "deep", "ship", "water", "arctic", "shark")):
        default_vt = "ocean_depth"
        mood = "wonder"
        accent = "cyan"
        cue = "bubbles"
    elif any(k in low for k in ("scan", "signal", "radio", "radar", "x-ray", "search", "helicopter", "frequency", "ring")):
        default_vt = "radar_scan"
        mood = "tense"
        accent = "cyan"
        cue = "whoosh"
    elif any(k in low for k in ("brain", "neuron", "amygdala", "memory", "mind", "gear", "compute")):
        default_vt = "neural_pulse"
        mood = "wonder"
        accent = "cyan"
        cue = "sparkle"
    elif any(k in low for k in ("gain", "spike", "surge", "volume", "beat", "percent", "times", "power", "current")):
        default_vt = "meter_surge"
        mood = "urgent"
        accent = "yellow"
        cue = "slide"
    elif any(k in low for k in ("compare", "instead", "either", "vs", "switched", "same", "neither", "off", "disconnected")):
        default_vt = "split_compare"
        mood = "mystery"
        accent = "cyan"
        cue = "pop"
    elif any(k in low for k in ("blood", "cell", "stream", "flow", "ripple", "fume")):
        default_vt = "micro_stream"
        mood = "tense"
        accent = "crimson"
        cue = "bubbles"
    else:
        default_vt = "vault_mystery"
        mood = "tense"
        accent = "yellow"
        cue = "tock"

    if prev_visual_type == default_vt:
        cycle = ("radar_scan", "split_compare", "timeline", "neural_pulse", "meter_surge", "tension_room", "vault_mystery")
        for alt in cycle:
            if alt != prev_visual_type:
                default_vt = alt
                break

    words = [re.sub(r"[^A-Za-z0-9'-]", "", w).upper() for w in text.split()]
    words = [w for w in words if len(w) >= 2]
    headline = " ".join(words[:4])[:28] or f"CHAPTER {idx + 1}"
    sublabel = " ".join(words[4:8])[:28] or (f"BEAT {idx + 1} OF {total_lines}")

    return {
        "visual_type": default_vt,
        "headline": headline,
        "sublabel": sublabel,
        "mood": mood,
        "accent": accent,
        "cue": cue,
    }


def assign_line_scenes(script_data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure every narration line carries a structured, non-repetitive scene descriptor."""
    lines = script_data.get("lines") or []
    total = len(lines)
    prev_vt: Optional[str] = None
    for idx, line in enumerate(lines):
        scene = line.get("scene")
        if not isinstance(scene, dict) or scene.get("visual_type") not in VISUAL_TYPES:
            scene = _infer_line_scene(str(line.get("text", "")), idx, total, prev_vt)
            line["scene"] = scene
        elif scene.get("visual_type") == prev_vt and idx not in (0, total - 1):
            scene = dict(scene)
            scene["visual_type"] = _infer_line_scene(str(line.get("text", "")), idx, total, prev_vt)["visual_type"]
            line["scene"] = scene
        prev_vt = line["scene"].get("visual_type")
    return script_data


def _strip_pii_and_links(text: str) -> str:
    cleaned = re.sub(r"https?://\S+|www\.\S+", "", text or "")
    cleaned = re.sub(r"(?:/?u/[A-Za-z0-9_-]+|/?r/[A-Za-z0-9_]+)", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def validate_script_quality(script_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate storytelling structure, hook quality, duration range words, and PII safety."""
    issues: List[str] = []
    lines = script_data.get("lines") or []
    if len(lines) < 4:
        issues.append("Script has fewer than 4 narrative beats.")
        return False, issues

    first_text = str(lines[0].get("text", "")).strip().lower()
    if first_text.startswith("did you know"):
        issues.append("Opening line uses prohibited generic 'Did you know?' cliché.")

    word_count = count_spoken_words(lines)
    if word_count < MIN_WORD_COUNT or word_count > MAX_WORD_COUNT + 5:
        issues.append(f"Word count {word_count} outside safe bounds [{MIN_WORD_COUNT}, {MAX_WORD_COUNT}].")

    full_text = " ".join(str(ln.get("text", "")) for ln in lines)
    if re.search(r"https?://|/?u/[A-Za-z0-9_-]+|/?r/[A-Za-z0-9_]+", full_text, re.IGNORECASE):
        issues.append("Script text contains disallowed URL or Reddit username/subreddit reference.")

    return len(issues) == 0, issues


def score_script_quality(script_data: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a narration script across 8 storytelling & retention metrics (0-10 scale)."""
    lines = list((script_data or {}).get("lines") or [])
    if not lines:
        metrics = {
            "opening_hook_strength": 0.0,
            "pacing": 0.0,
            "clarity": 0.0,
            "curiosity_tension": 0.0,
            "emotional_engagement": 0.0,
            "ending_payoff": 0.0,
            "natural_spoken_rhythm": 0.0,
            "visual_cut_compatibility": 0.0,
        }
        return {"metrics": metrics, "overall_score": 0.0, "weak_areas": list(metrics.keys()), "passed": False}

    texts = [str(ln.get("text", "")).strip() for ln in lines if str(ln.get("text", "")).strip()]
    word_count = count_spoken_words(lines)
    first = texts[0] if texts else ""
    last = texts[-1] if texts else ""
    first_low = first.lower()

    # 1. Opening hook (0-3s)
    hook_score = 8.5
    if first_low.startswith("did you know"):
        hook_score -= 5.0
    if len(first.split()) > 26:
        hook_score -= 2.0
    if "?" in first or any(w in first_low for w in ("within", "seconds", "nobody", "vanished", "mile", "silent", "impossible", "imagine", "never")):
        hook_score += 1.0
    hook_score = max(0.0, min(10.0, hook_score))

    # 2. Pacing (beat distribution + word count fit)
    beat_lengths = [len(t.split()) for t in texts]
    avg_beat = sum(beat_lengths) / max(1, len(beat_lengths))
    pacing = 9.0 if (MIN_WORD_COUNT <= word_count <= MAX_WORD_COUNT and 5 <= len(texts) <= 10) else 6.0
    if any(bl > 32 for bl in beat_lengths):
        pacing -= 2.0
    if avg_beat < 6 or avg_beat > 25:
        pacing -= 1.0
    pacing = max(0.0, min(10.0, pacing))

    # 3. Clarity & spoken readability
    clarity = 8.8
    if any("http" in t.lower() or "et al." in t.lower() for t in texts):
        clarity -= 3.0
    if any(len(t) > 220 for t in texts):
        clarity -= 2.0
    clarity = max(0.0, min(10.0, clarity))

    # 4. Curiosity & tension progression
    joined_low = " ".join(texts).lower()
    tension_markers = ("but", "yet", "however", "until", "then", "strangely", "except", "turned out", "instead", "without")
    tension_hits = sum(1 for m in tension_markers if m in joined_low)
    curiosity_tension = max(0.0, min(10.0, 6.5 + min(3.5, tension_hits * 1.1)))

    # 5. Emotional engagement
    emo_markers = ("brain", "heart", "surviv", "alone", "lost", "secret", "fear", "shock", "wonder", "miracle", "human", "silent", "deep", "dark")
    emo_hits = sum(1 for m in emo_markers if m in joined_low)
    emotional_engagement = max(0.0, min(10.0, 6.2 + min(3.8, emo_hits * 0.9)))

    # 6. Ending payoff
    ending_payoff = 8.6
    last_low = last.lower()
    if len(last.split()) < 6 or any(p in last_low for p in ("subscribe", "like and follow", "part 2")):
        ending_payoff -= 3.5
    if any(m in last_low for m in ("because", "proved", "instead", "showed", "remained", "survived", "actually", "means", "never", "still")):
        ending_payoff += 0.9
    ending_payoff = max(0.0, min(10.0, ending_payoff))

    # 7. Natural spoken rhythm
    gaps = [float(ln.get("gap", 0.28)) for ln in lines]
    rhythm = 9.0 if all(0.15 <= g <= 0.55 for g in gaps) else 6.5
    if first_low.startswith("did you know") or "furthermore" in joined_low or "moreover" in joined_low:
        rhythm -= 2.0
    rhythm = max(0.0, min(10.0, rhythm))

    # 8. Visual cut compatibility
    vts = [str((ln.get("scene") or {}).get("visual_type") or "") for ln in lines]
    distinct_vts = len({v for v in vts if v})
    repeats = sum(1 for i in range(1, len(vts)) if vts[i] and vts[i] == vts[i - 1])
    visual_fit = 8.8 if distinct_vts >= max(3, len(lines) // 2) else 6.0
    visual_fit = max(0.0, min(10.0, visual_fit - repeats * 1.5))

    metrics = {
        "opening_hook_strength": round(hook_score, 2),
        "pacing": round(pacing, 2),
        "clarity": round(clarity, 2),
        "curiosity_tension": round(curiosity_tension, 2),
        "emotional_engagement": round(emotional_engagement, 2),
        "ending_payoff": round(ending_payoff, 2),
        "natural_spoken_rhythm": round(rhythm, 2),
        "visual_cut_compatibility": round(visual_fit, 2),
    }
    overall = round(sum(metrics.values()) / len(metrics), 2)
    weak_areas = [k for k, v in metrics.items() if v < 6.5]
    return {
        "metrics": metrics,
        "overall_score": overall,
        "weak_areas": weak_areas,
        "word_count": word_count,
        "passed": overall >= 6.8 and not weak_areas,
    }


def improve_script_quality(script_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Automatically strengthen weak script hooks, repeated visuals, or robotic phrasing."""
    updated = copy.deepcopy(script_data)
    lines = list(updated.get("lines") or [])
    if not lines:
        return updated, score_script_quality(updated)

    # Fix generic "Did you know" opener
    first_txt = str(lines[0].get("text", "")).strip()
    if first_txt.lower().startswith("did you know"):
        stripped = re.sub(r"^did you know(?:\s+that)?\s+", "", first_txt, flags=re.IGNORECASE).strip()
        if stripped:
            stripped = stripped[0].upper() + stripped[1:]
            lines[0]["text"] = stripped
            lines[0]["caps"] = format_auto_caps(stripped)

    # Split overly long single narration beat cleanly for tighter retention cuts (if within ceiling)
    normalized_lines: List[Dict[str, Any]] = []
    for ln in lines:
        txt = _strip_pii_and_links(str(ln.get("text", "")))
        words = txt.split()
        if len(words) > 28 and len(lines) < 9:
            mid = len(words) // 2
            p1 = " ".join(words[:mid]).rstrip(",;") + "."
            p2 = " ".join(words[mid:])
            if p2:
                p2 = p2[0].upper() + p2[1:]
            normalized_lines.append({**ln, "text": p1, "caps": format_auto_caps(p1), "gap": 0.24})
            normalized_lines.append({**ln, "text": p2, "caps": format_auto_caps(p2), "gap": float(ln.get("gap", 0.26))})
        else:
            ln_copy = dict(ln)
            ln_copy["text"] = txt
            if not ln_copy.get("caps"):
                ln_copy["caps"] = format_auto_caps(txt)
            normalized_lines.append(ln_copy)

    updated["lines"] = normalized_lines
    assign_line_scenes(updated)
    eval_report = score_script_quality(updated)
    updated["quality_evaluation"] = eval_report
    return updated, eval_report


def write_video_script(topic_info: Dict[str, Any]) -> Dict[str, Any]:
    """Generate or retrieve a high-retention storytelling script (25-45s target, <= 60s)."""
    topic = _strip_pii_and_links(str(topic_info.get("topic", "")))
    category = topic_info.get("category", "Science")
    style = topic_info.get("style", "inside-out")
    voice = VOICE_MAP.get(style, "am_michael")
    evidence_type = topic_info.get("evidence_type", "documented_fact")
    discovery_origin = topic_info.get("discovery_origin", "curated_research")
    angle_note = _strip_pii_and_links(str(topic_info.get("angle_note", "")))

    # 1. Match exact or same-category curated high-retention story when Gemini isn't used
    matched_item = None
    for item in CURATED_TOPICS:
        if item["topic"].lower() == topic.lower() or (
            topic_info.get("id") and item.get("id") == topic_info.get("id")
        ):
            matched_item = item
            break
    if matched_item is None and not gemini_client.is_configured():
        for item in CURATED_TOPICS:
            if item["category"].lower() == category.lower() and item.get("style") == style:
                matched_item = item
                break
        if matched_item is None:
            for item in CURATED_TOPICS:
                if item["style"] == style:
                    matched_item = item
                    break

    if matched_item is not None:
        script_data = copy.deepcopy(matched_item["script"])
        script_data["id"] = matched_item.get("id")
        script_data["sources"] = list(matched_item.get("sources", []))
        script_data["claims"] = list(matched_item.get("claims", []))
        script_data["topic"] = matched_item["topic"]
        script_data["category"] = matched_item["category"]
        script_data["style"] = matched_item["style"]
        script_data["evidence_type"] = matched_item.get("evidence_type", "documented_fact")
        script_data["discovery_origin"] = matched_item.get("discovery_origin", "curated_research")
        script_data["scores"] = matched_item.get("scores", topic_info.get("scores", {}))
        assign_line_scenes(script_data)
        script_data, _q_rep = improve_script_quality(script_data)
        word_count = count_spoken_words(script_data["lines"])
        logger.info("Using verified curated story script for '%s' (%d words, score=%.2f).", matched_item["topic"], word_count, _q_rep.get("overall_score", 0.0))
        return script_data

    # 2. Generate high-retention original storytelling script via Gemini
    evidence_guidance = {
        "unexplained_mystery": "Frame documented evidence honestly as an unresolved mystery and label hypotheses as hypotheses rather than settled fact.",
        "personal_account": "Frame clearly as a documented account without asserting unproven supernatural/fictional claims as scientific fact.",
        "historical_incident": "Anchor to documented dates, archives, or recorded physical evidence.",
        "scientific_study": "Anchor clearly to observed mechanisms or peer-reviewed research.",
        "documented_fact": "Present verifiable mechanisms and concrete evidence clearly.",
    }.get(evidence_type, "Be strictly factual.")

    extra_context = f"\nBackground context note (transform into original narrative, zero usernames/URLs): {angle_note}" if angle_note else ""
    visual_choices = ", ".join(VISUAL_TYPES)
    prompt = f"""
Write an original short-form storytelling narration script on: "{topic}" (Category: {category}).
Target length: approximately {int(TARGET_DURATION_MIN_SEC)}-{int(TARGET_DURATION_MAX_SEC)} seconds ({TARGET_WORD_COUNT_MIN}-{TARGET_WORD_COUNT_MAX} spoken words ideal; strictly within {MIN_WORD_COUNT}-{MAX_WORD_COUNT} words, max 60 seconds).
Storytelling origin: {discovery_origin} | Evidence framing: {evidence_type} ({evidence_guidance}){extra_context}

STORYTELLING & RETENTION RULES:
1. Opening Hook (0-3s): Line 1 MUST hook immediately with an unusual situation, striking tension, or gripping question. NEVER start with "Did you know?".
2. Development: Establish the situation quickly, reveal clues progressively, eliminate encyclopedic filler.
3. Curiosity & Suspense: Introduce an unanswered question or meaningful narrative twist before revealing the answer.
4. Natural Spoken Cadence: Sound conversational, vivid, and human—never robotic textbook prose.
5. Ending Payoff: Deliver a crisp, memorable resolution that resolves the curiosity gap without artificial cliffhangers.
6. Honesty & Privacy: NEVER invent fake facts/dates, NEVER copy posts verbatim, NEVER include URLs, usernames, or personal info.
7. Visual Scene Matching: Structure into 6 to 9 natural cut lines; pair each line with a matching `scene` visual type from [{visual_choices}] (avoid repeating consecutive `visual_type`!), concise visual `headline` (2-5 words), `sublabel`, `mood` (mystery/tense/urgent/wonder/calm), `accent` (yellow/cyan/crimson/green), and `cue` (whoosh/pop/tock/slide/bubbles/slam/sparkle).

Return valid JSON:
{{
  "title": "Curiosity-Sparking Natural Title (not all-caps, no clickbait)",
  "sources": ["https://..."],
  "claims": ["Verified factual claim 1", "Verified factual claim 2"],
  "lines": [
     {{
       "text": "Hook sentence...",
       "caps": "THREE WORD *CAPS | SECOND *CHUNK",
       "gap": 0.28,
       "scene": {{
         "visual_type": "tension_room",
         "headline": "SHORT VISUAL LABEL",
         "sublabel": "CONTEXT DETAIL",
         "mood": "mystery",
         "accent": "yellow",
         "cue": "whoosh"
       }}
     }}
  ]
}}
"""
    system_instruction = (
        f"You are lead story writer for CurioLoop. Target {TARGET_WORD_COUNT_MIN}-{TARGET_WORD_COUNT_MAX} words "
        f"(strict max {MAX_WORD_COUNT} words for <={int(MAX_DURATION_SEC)}s runtime). Never fabricate claims or leak usernames/URLs."
    )
    response = gemini_client.generate_json(prompt, system_instruction=system_instruction)

    if response and "lines" in response and len(response["lines"]) >= 4:
        lines = []
        for raw_ln in response["lines"]:
            clean_txt = _strip_pii_and_links(str(raw_ln.get("text", "")))
            if not clean_txt:
                continue
            caps = str(raw_ln.get("caps") or "").strip() or format_auto_caps(clean_txt)
            try:
                gap = min(0.45, max(0.18, float(raw_ln.get("gap", 0.28))))
            except (TypeError, ValueError):
                gap = 0.28
            lines.append({
                "text": clean_txt,
                "caps": caps,
                "gap": gap,
                "scene": raw_ln.get("scene"),
            })

        word_count = count_spoken_words(lines)
        raw_sources = response.get("sources", []) or topic_info.get("sources", [])
        is_valid_src, validated_sources = validate_factual_sources(raw_sources)
        if not validated_sources and topic_info.get("sources"):
            validated_sources = list(topic_info.get("sources", []))

        script_candidate: Dict[str, Any] = {
            "title": _strip_pii_and_links(str(response.get("title") or topic)),
            "voice": voice,
            "speed": 1.0,
            "lead": 0.40,
            "outro": 0.75,
            "gap": 0.28,
            "topic": topic,
            "category": category,
            "style": style,
            "evidence_type": evidence_type,
            "discovery_origin": discovery_origin,
            "scores": topic_info.get("scores", {}),
            "sources": validated_sources if is_valid_src else list(topic_info.get("sources", [])),
            "claims": response.get("claims") or topic_info.get("claims") or [topic],
            "lines": lines,
        }
        assign_line_scenes(script_candidate)
        script_candidate, q_eval = improve_script_quality(script_candidate)
        q_ok, q_issues = validate_script_quality(script_candidate)
        if q_ok and q_eval.get("overall_score", 0.0) >= 6.5 and (is_valid_src or evidence_type in ("unexplained_mystery", "personal_account")):
            logger.info("Generated high-retention Gemini script for '%s' (%d words, score=%.2f).", topic, word_count, q_eval.get("overall_score", 0.0))
            return script_candidate
        logger.warning("Gemini script failed quality/source check (%s; score=%.2f); falling back to curated story.", q_issues, q_eval.get("overall_score", 0.0))

    # 3. Robust curated fallback (pick by matching category/style before default)
    fallback = CURATED_TOPICS[0]
    for cand in CURATED_TOPICS:
        if cand["category"].lower() == category.lower() or cand["style"] == style:
            fallback = cand
            break
    script_data = copy.deepcopy(fallback["script"])
    script_data["id"] = fallback.get("id")
    script_data["sources"] = list(fallback.get("sources", []))
    script_data["claims"] = list(fallback.get("claims", []))
    script_data["topic"] = fallback["topic"]
    script_data["category"] = fallback["category"]
    script_data["style"] = fallback["style"]
    script_data["evidence_type"] = fallback.get("evidence_type", "documented_fact")
    script_data["discovery_origin"] = fallback.get("discovery_origin", "curated_research")
    script_data["scores"] = fallback["scores"]
    assign_line_scenes(script_data)
    return script_data


def revise_script_for_duration(
    script_data: Dict[str, Any],
    current_duration_sec: float,
    target_min_sec: float = TARGET_DURATION_MIN_SEC,
    target_max_sec: float = TARGET_DURATION_MAX_SEC,
) -> Tuple[Dict[str, Any], str]:
    """Revise a script for QC duration recovery without cutting off the ending or distorting pacing.

    Returns `(updated_script, revision_summary)`.
    """
    revised = copy.deepcopy(script_data)
    lines = list(revised.get("lines") or [])
    if not lines:
        return revised, "No lines to revise"

    # Case A: Exceeded MAX_DURATION_SEC (> 60s) -> condense via Gemini or drop filler clauses while preserving hook & ending
    if current_duration_sec > MAX_DURATION_SEC:
        if gemini_client.is_configured():
            existing_text = "\n".join(f"{i+1}. {ln['text']}" for i, ln in enumerate(lines))
            prompt = f"""
Revise the following narration script cleanly because it rendered to {current_duration_sec:.1f}s, exceeding the 60s hard maximum.
Target ~{int(target_max_sec)}s (~{TARGET_WORD_COUNT_MIN}-{TARGET_WORD_COUNT_MAX} spoken words total) across 6-8 cut lines.
CRITICAL RULES:
- Preserve the opening curiosity hook AND the final satisfying ending payoff.
- Tighten middle explanations and remove filler phrases WITHOUT chopping off sentences mid-thought.
- Keep spoken flow natural.

Original lines:
{existing_text}

Return strict JSON: {{"lines": [{{"text": "...", "gap": 0.25}}]}}
"""
            ai_res = gemini_client.generate_json(prompt)
            if ai_res and isinstance(ai_res.get("lines"), list) and len(ai_res["lines"]) >= 4:
                new_lines = []
                for idx, raw_ln in enumerate(ai_res["lines"]):
                    txt = _strip_pii_and_links(str(raw_ln.get("text", "")))
                    if not txt:
                        continue
                    old_scene = lines[min(idx, len(lines) - 1)].get("scene")
                    new_lines.append({
                        "text": txt,
                        "caps": format_auto_caps(txt),
                        "gap": min(0.30, max(0.18, float(raw_ln.get("gap", 0.24)))),
                        "scene": old_scene,
                    })
                if MIN_WORD_COUNT <= count_spoken_words(new_lines) <= MAX_WORD_COUNT:
                    revised["lines"] = new_lines
                    revised["lead"] = min(float(revised.get("lead", 0.4)), 0.35)
                    revised["outro"] = min(float(revised.get("outro", 0.7)), 0.55)
                    assign_line_scenes(revised)
                    return revised, f"Condensed script via AI from {current_duration_sec:.1f}s to {count_spoken_words(new_lines)} words"

        # Deterministic clean condensation: shrink gaps & lead/outro slightly first, and condense verbose middle lines
        scale_ratio = min(0.82, (target_max_sec / max(current_duration_sec, 61.0)))
        revised["lead"] = 0.30
        revised["outro"] = 0.50
        revised["gap"] = 0.22
        condensed_lines: List[Dict[str, Any]] = []
        # Keep Hook (0) and Ending (-1) intact; condense or merge excess middle lines when >6 lines
        for idx, ln in enumerate(lines):
            ln_copy = copy.deepcopy(ln)
            ln_copy["gap"] = 0.20
            txt = str(ln_copy.get("text", "")).strip()
            # Drop optional parenthetical/aside filler clauses only inside middle lines if way over length
            if 0 < idx < len(lines) - 1 and current_duration_sec > MAX_DURATION_SEC:
                txt = re.sub(r"\s*[—–-]\s*[^.;!?]+$", ".", txt)
                txt = re.sub(r",\s*(?:which|while|though|because)[^,.;!?]+", "", txt, count=1, flags=re.IGNORECASE).strip()
                if txt and not txt[-1] in ".!?":
                    txt += "."
                ln_copy["text"] = txt
                ln_copy["caps"] = format_auto_caps(txt)
            condensed_lines.append(ln_copy)

        # If still likely >60s (>125 words) and many middle lines exist, trim lowest-priority redundant middle beat cleanly
        while len(condensed_lines) > 5 and count_spoken_words(condensed_lines) > int(TARGET_WORD_COUNT_MAX * max(0.85, scale_ratio)):
            drop_idx = len(condensed_lines) // 2
            condensed_lines.pop(drop_idx)

        revised["lines"] = condensed_lines
        revised["revision_applied"] = "condensed_for_60s_limit"
        assign_line_scenes(revised)
        return revised, (
            f"Condensed script deterministically ({len(lines)} -> {len(condensed_lines)} beats, "
            f"{count_spoken_words(condensed_lines)} words) preserving hook & ending"
        )

    # Case B: Too short (< MIN_DURATION_SEC 20s)
    if current_duration_sec < MIN_DURATION_SEC:
        revised["lead"] = max(float(revised.get("lead", 0.4)), 0.55)
        revised["outro"] = max(float(revised.get("outro", 0.7)), 1.0)
        for ln in lines:
            ln["gap"] = min(0.45, max(float(ln.get("gap", 0.3)), 0.36))
        if len(lines) >= 2 and count_spoken_words(lines) < MIN_WORD_COUNT:
            claims = [str(c).strip() for c in (revised.get("claims") or []) if len(str(c).strip()) > 15]
            existing_txt = " ".join(ln["text"].lower() for ln in lines)
            for c in claims:
                if c.lower()[:25] not in existing_txt:
                    insert_line = {
                        "text": c if c.endswith((".", "!", "?")) else f"{c}.",
                        "caps": format_auto_caps(c),
                        "gap": 0.32,
                    }
                    lines.insert(-1, insert_line)
                    break
        revised["lines"] = lines
        revised["revision_applied"] = "expanded_for_min_20s"
        assign_line_scenes(revised)
        return revised, f"Expanded story beat spacing/claim depth from {current_duration_sec:.1f}s cleanly"

    assign_line_scenes(revised)
    return revised, "Refreshed script scene timing"
