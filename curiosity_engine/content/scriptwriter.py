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
    CALIBRATED_WORDS_PER_SECOND,
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
from curiosity_engine.content.editorial_policy import (
    get_visual_style_for_category,
    normalize_category_name,
    validate_editorial_category,
)
from curiosity_engine.content.gemini_client import gemini_client
from curiosity_engine.content.narrative_engine import (
    build_documentary_outline,
    generate_draft_script,
    generate_hook_candidates,
    select_best_hook,
)
from curiosity_engine.content.research_dossier import build_research_dossier
from curiosity_engine.content.story_critic import (
    critique_and_rewrite,
    evaluate_script_critique,
    repair_script_emergency,
)
from curiosity_engine.quality.script_validator import validate_script

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
        default_vt = "cosmic_burst" if any(k in low for k in ("space", "sun", "star", "storm", "cosmic", "orbit", "galaxy")) else (
            "ocean_depth" if any(k in low for k in ("ocean", "sea", "ship", "arctic", "shark", "water", "abyss")) else (
                "archive_map" if any(k in low for k in ("map", "city", "expedition", "tomb", "pyramid", "ruins", "island")) else "tension_room"
            )
        )
        mood = "mystery"
        accent = "yellow"
        cue = "whoosh"
    elif idx == total_lines - 1:
        default_vt = "payoff_reveal"
        mood = "calm"
        accent = "green"
        cue = "sparkle"
    elif any(k in low for k in ("map", "city", "egypt", "jungle", "river", "port", "island", "expedition", "voyage", "tomb", "pyramid", "ruins", "caravan", "fortress")):
        default_vt = "archive_map"
        mood = "mystery"
        accent = "yellow"
        cue = "pop"
    elif any(k in low for k in ("century", "year", "eighteen", "nineteen", "two thousand", "day", "hour", "decade", "ago", "timeline", "bc", "ad", "ancient", "dynasty")):
        default_vt = "timeline"
        mood = "wonder"
        accent = "crimson"
        cue = "tock"
    elif any(k in low for k in ("ocean", "sea", "dive", "deep", "ship", "water", "arctic", "shark", "submerged", "abyss")):
        default_vt = "ocean_depth"
        mood = "wonder"
        accent = "cyan"
        cue = "bubbles"
    elif any(k in low for k in ("scan", "signal", "radio", "radar", "x-ray", "search", "frequency", "telescope", "light-year", "pulsar", "antenna", "ping")):
        default_vt = "radar_scan"
        mood = "tense"
        accent = "cyan"
        cue = "whoosh"
    elif any(k in low for k in ("brain", "neuron", "memory", "mind", "decode", "analysis", "equation", "pattern", "carbon", "sample", "microscope", "cipher")):
        default_vt = "neural_pulse"
        mood = "wonder"
        accent = "cyan"
        cue = "sparkle"
    elif any(k in low for k in ("gain", "spike", "surge", "volume", "beat", "percent", "power", "current", "explode", "critical", "maximum", "shattered", "danger")):
        default_vt = "meter_surge"
        mood = "urgent"
        accent = "yellow"
        cue = "slide"
    elif any(k in low for k in ("compare", "instead", "either", "vs", "versus", "conflict", "contradiction", "dispute", "rival", "differ", "opposing")):
        default_vt = "split_compare"
        mood = "mystery"
        accent = "cyan"
        cue = "pop"
    elif any(k in low for k in ("space", "star", "orbit", "galaxy", "black hole", "cosmic", "asteroid", "comet", "nebula", "supernova")):
        default_vt = "cosmic_burst"
        mood = "wonder"
        accent = "yellow"
        cue = "whoosh"
    elif any(k in low for k in ("secret", "chamber", "vault", "document", "artifact", "relic", "hidden", "unsolved", "mystery", "enigma", "classified")):
        default_vt = "vault_mystery"
        mood = "tense"
        accent = "yellow"
        cue = "tock"
    else:
        default_vt = "tension_room"
        mood = "tense"
        accent = "crimson"
        cue = "tock"

    if prev_visual_type == default_vt:
        cycle = ("radar_scan", "timeline", "split_compare", "neural_pulse", "meter_surge", "vault_mystery", "archive_map", "tension_room")
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
    rotation_pool = [
        "radar_scan", "timeline", "split_compare", "neural_pulse",
        "meter_surge", "vault_mystery", "archive_map", "tension_room"
    ]

    for idx, line in enumerate(lines):
        scene = line.get("scene")
        if not isinstance(scene, dict) or scene.get("visual_type") not in VISUAL_TYPES:
            scene = _infer_line_scene(str(line.get("text", "")), idx, total, prev_vt)
            line["scene"] = scene
        elif scene.get("visual_type") == prev_vt:
            scene = dict(scene)
            inferred = _infer_line_scene(str(line.get("text", "")), idx, total, prev_vt)
            new_vt = inferred["visual_type"]
            if new_vt == prev_vt:
                for cand in rotation_pool:
                    if cand != prev_vt:
                        new_vt = cand
                        break
            scene["visual_type"] = new_vt
            line["scene"] = scene

        # Payoff reveal for climax if closing
        if idx == total - 1 and line["scene"].get("visual_type") == prev_vt:
            for cand in ["payoff_reveal", "vault_mystery", "timeline"]:
                if cand != prev_vt:
                    line["scene"]["visual_type"] = cand
                    break

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
    """Generate or retrieve a high-retention storytelling script (42-58s target, <= 60s).

    Executes the viral shorts editorial workflow:
      Topic -> Contextual Category Validation -> Research Dossier ->
      Hook Playbook -> 5-Beat Documentary Outline -> Narrative Draft (Call 1) ->
      Independent Story Critic & Targeted Rewrite (Call 2) ->
      Deterministic Validator -> Emergency Repair (Call 3 if needed) ->
      Verified Script Output (or Curated Fallback on failure).
    """
    raw_topic = _strip_pii_and_links(str(topic_info.get("topic", "")))
    raw_category = str(topic_info.get("category", "") or "MYSTERY")

    # Step 0: Contextual Category Validation
    is_valid_cat, detected_cat, cat_reason = validate_editorial_category(
        raw_topic, declared_category=raw_category
    )
    category = detected_cat or normalize_category_name(raw_category) or "MYSTERY"
    style = get_visual_style_for_category(category)
    voice = VOICE_MAP.get(style, "bm_george" if category == "HISTORY" else "am_michael")
    topic = raw_topic

    # Step 1: Check if this matches a curated high-retention fallback story
    matched_item = None
    for item in CURATED_TOPICS:
        if item["topic"].lower() == topic.lower() or (
            topic_info.get("id") and item.get("id") == topic_info.get("id")
        ):
            matched_item = item
            break

    # If this topic was explicitly flagged as a curated fallback from discovery
    if matched_item is None and topic_info.get("source_mode") == "curated_fallback":
        from curiosity_engine.content.curated_fallback import get_unused_fallback
        matched_item = get_unused_fallback(category)
        logger.warning(
            "Discovery assigned curated fallback; selected unused story '%s' (ID: %s) for category %s.",
            matched_item["topic"], matched_item.get("id"), category,
        )

    if matched_item is not None:
        script_data = copy.deepcopy(matched_item["script"])
        script_data["id"] = matched_item.get("id")
        script_data["sources"] = list(matched_item.get("sources", []))
        script_data["claims"] = list(matched_item.get("claims", []))
        script_data["topic"] = matched_item["topic"]
        script_data["category"] = matched_item["category"]
        script_data["style"] = matched_item["style"]
        script_data["evidence_type"] = matched_item.get("evidence_type", "historical_incident")
        script_data["discovery_origin"] = matched_item.get("discovery_origin", "curated_research")
        script_data["scores"] = matched_item.get("scores", topic_info.get("scores", {}))
        script_data["research_dossier"] = matched_item.get("research_dossier", {})
        script_data["hook"] = matched_item.get("hook", matched_item["script"]["lines"][0]["text"])
        script_data["hook_pattern"] = matched_item.get("hook_pattern", "impossible_claim")
        script_data["loop_line"] = matched_item.get("loop_line", matched_item["script"]["lines"][-1]["text"])
        assign_line_scenes(script_data)
        word_count = count_spoken_words(script_data["lines"])

        if script_data.get("id"):
            try:
                from curiosity_engine.state.db import db
                from datetime import datetime, timezone
                db.record_fallback_used(
                    script_data["id"],
                    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    script_data["topic"],
                )
            except Exception:
                pass

        logger.info(
            "Using verified curated story script for '%s' (%d words, category=%s, ID=%s).",
            matched_item["topic"],
            word_count,
            script_data["category"],
            script_data.get("id"),
        )
        return script_data

    # Step 2: Full Original Editorial Workflow (Gemini Call 1, 2, 3 or Outline Engine)
    if not is_valid_cat:
        logger.warning(
            "Topic '%s' violates editorial policy (%s); falling back to unused curated story.",
            topic,
            cat_reason,
        )
        from curiosity_engine.content.curated_fallback import get_unused_fallback
        fallback = get_unused_fallback(category)
        fallback_script = copy.deepcopy(fallback["script"])
        fallback_script["id"] = fallback.get("id")
        fallback_script["topic"] = fallback.get("topic")
        fallback_script["category"] = fallback.get("category")
        fallback_script["style"] = fallback.get("style")
        fallback_script["research_dossier"] = fallback.get("research_dossier", {})
        if fallback.get("id"):
            try:
                from curiosity_engine.state.db import db
                from datetime import datetime, timezone
                db.record_fallback_used(
                    fallback["id"],
                    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    fallback["topic"],
                )
            except Exception:
                pass
        return fallback_script

    # Build Research Dossier
    raw_sources = topic_info.get("sources", [])
    dossier = build_research_dossier(
        topic=topic,
        category=category,
        source_seeds=raw_sources if isinstance(raw_sources, list) else [],
    )

    # Call 1: Narrative Engine (Hooks, Outline, Initial Draft)
    hook_candidates = generate_hook_candidates(dossier)
    selected_hook = select_best_hook(hook_candidates)
    outline = build_documentary_outline(dossier, selected_hook)
    draft = generate_draft_script(dossier, selected_hook, outline)

    script_candidate = {
        "title": draft.title,
        "voice": draft.voice,
        "speed": 1.0,
        "lead": 0.40,
        "outro": 0.75,
        "gap": 0.26,
        "topic": topic,
        "category": draft.category,
        "niche": draft.niche,
        "style": draft.style,
        "hook": draft.hook,
        "hook_pattern": draft.hook_pattern,
        "hook_candidates": draft.hook_candidates,
        "beats": draft.beats,
        "loop_line": draft.loop_line,
        "claims": draft.claims,
        "sources": dossier.get("sources", []),
        "research_dossier": dossier,
        "lines": draft.lines,
        "est_seconds": draft.est_seconds,
    }

    # Call 2: Independent Story Critic & Targeted Rewrite
    script_candidate, critic_report = critique_and_rewrite(
        script_candidate, dossier=dossier
    )
    script_candidate["critic_evaluation"] = {
        "scores": critic_report.scores,
        "overall_score": critic_report.overall_score,
        "passed": critic_report.passed,
        "weakest_dimensions": critic_report.weakest_dimensions,
        "feedback": critic_report.feedback,
    }

    # Deterministic Script Validator Gate
    val_res = validate_script(script_candidate, wps=CALIBRATED_WORDS_PER_SECOND, dossier=dossier)
    script_candidate["validator_result"] = val_res

    # Call 3: Emergency Repair (only if validator still reports errors)
    if not val_res["ok"]:
        logger.warning(
            "Script failed validator checks (%s). Invoking Call 3 Emergency Repair.",
            val_res["errors"],
        )
        script_candidate = repair_script_emergency(
            script_candidate, validator_errors=val_res["errors"]
        )
        val_res = validate_script(script_candidate, wps=CALIBRATED_WORDS_PER_SECOND, dossier=dossier)
        script_candidate["validator_result"] = val_res

    # Final Gatekeeper
    if val_res["ok"]:
        assign_line_scenes(script_candidate)
        for ln in script_candidate["lines"]:
            if not ln.get("caps"):
                ln["caps"] = format_auto_caps(ln["text"])
        word_count = count_spoken_words(script_candidate["lines"])
        logger.info(
            "Successfully validated original script for '%s' (%d words, ~%.1fs, score=%.2f).",
            topic,
            word_count,
            val_res["est_seconds"],
            critic_report.overall_score,
        )
        return script_candidate

    logger.warning(
        "Script failed final validator gate (%s); falling back cleanly to curated story.",
        val_res["errors"],
    )
    fallback = next(
        (c for c in CURATED_TOPICS if c["category"] == category),
        CURATED_TOPICS[0],
    )
    fallback_script = copy.deepcopy(fallback["script"])
    fallback_script["id"] = fallback.get("id")
    fallback_script["sources"] = list(fallback.get("sources", []))
    fallback_script["claims"] = list(fallback.get("claims", []))
    fallback_script["topic"] = fallback["topic"]
    fallback_script["category"] = fallback["category"]
    fallback_script["style"] = fallback["style"]
    fallback_script["research_dossier"] = fallback.get("research_dossier", {})
    assign_line_scenes(fallback_script)
    return fallback_script


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
