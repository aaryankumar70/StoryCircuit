"""Independent Story Critic & Targeted Rewriting for CurioLoop.

Evaluates storytelling scripts across 10 qualitative dimensions:
1. hook_strength
2. narrative_clarity
3. story_progression
4. curiosity_retention
5. emotional_engagement
6. factual_reliability
7. originality
8. pacing
9. ending_quality
10. spoken_rhythm

Enforces strict publication thresholds:
- factual_reliability >= 8.0
- narrative_clarity >= 7.0
- hook_strength >= 7.0
- overall_score >= 8.0
- no individual metric < 6.0

Provides targeted rewriting bounded to max 3 Gemini calls per video lifecycle.
"""
from __future__ import annotations

import copy
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.content.editorial_policy import (
    BANNED_OPENERS,
    BANNED_PHRASES,
    WEAK_CTAS,
    is_forbidden_content,
)
from curiosity_engine.content.gemini_client import gemini_client

logger = logging.getLogger("curiosity_engine.story_critic")

CRITIC_DIMENSIONS = (
    "hook_strength",
    "narrative_clarity",
    "story_progression",
    "curiosity_retention",
    "emotional_engagement",
    "factual_reliability",
    "originality",
    "pacing",
    "ending_quality",
    "spoken_rhythm",
)

THRESHOLDS = {
    "factual_reliability": 8.0,
    "narrative_clarity": 7.0,
    "hook_strength": 7.0,
    "overall": 8.0,
    "min_individual": 6.0,
}


@dataclass
class CriticReport:
    scores: Dict[str, float]
    overall_score: float
    passed: bool
    weakest_dimensions: List[str]
    feedback: str
    factual_checks: List[Dict[str, Any]] = field(default_factory=list)


def _count_words(text: str) -> int:
    return len([w for w in text.split() if re.sub(r"[^a-zA-Z0-9]", "", w)])


def _deterministic_critique(script_data: Dict[str, Any], dossier: Any) -> CriticReport:
    """Evaluate a script deterministically across the 10 dimensions."""
    lines = list(script_data.get("lines") or [])
    texts = [str(ln.get("text", "")).strip() for ln in lines if str(ln.get("text", "")).strip()]
    full_text = " ".join(texts)
    full_lower = full_text.lower()
    total_words = sum(_count_words(t) for t in texts)

    first_text = texts[0] if texts else ""
    first_words = first_text.split()
    first_lower = first_text.lower()

    last_text = texts[-1] if texts else ""
    last_lower = last_text.lower()

    scores: Dict[str, float] = {}

    # 1. Hook strength
    hook_s = 8.5
    if len(first_words) > 14:
        hook_s -= 2.5
    elif len(first_words) < 5:
        hook_s -= 2.0
    if any(first_lower.startswith(b.lower()) for b in BANNED_OPENERS):
        hook_s -= 4.0
    if re.search(r"\b(?:\d+|one|two|three|thousand|million|nasa|apollo|paris|egypt|year)\b", first_lower):
        hook_s += 1.0
    scores["hook_strength"] = max(1.0, min(10.0, round(hook_s, 1)))

    # 2. Narrative clarity
    clarity_s = 8.8
    if any(len(t.split()) > 22 for t in texts):
        clarity_s -= 1.5
    if any("http" in t.lower() or "et al" in t.lower() for t in texts):
        clarity_s -= 3.0
    scores["narrative_clarity"] = max(1.0, min(10.0, round(clarity_s, 1)))

    # 3. Story progression
    prog_s = 8.5
    markers = ("but", "yet", "however", "until", "then", "strangely", "except", "instead", "revealed", "discovered")
    hits = sum(1 for m in markers if m in full_lower)
    if hits >= 3:
        prog_s += 1.0
    elif hits == 0:
        prog_s -= 2.0
    scores["story_progression"] = max(1.0, min(10.0, round(prog_s, 1)))

    # 4. Curiosity retention
    curiosity_s = 8.6
    if "?" in first_text or any(w in first_lower for w in ("impossible", "mystery", "silent", "vanished", "unexplained", "never")):
        curiosity_s += 0.8
    scores["curiosity_retention"] = max(1.0, min(10.0, round(curiosity_s, 1)))

    # 5. Emotional engagement
    emo_s = 8.4
    emo_markers = ("crew", "survive", "lost", "human", "danger", "secret", "deep", "alone", "dark", "shock", "wonder")
    if any(m in full_lower for m in emo_markers):
        emo_s += 0.8
    scores["emotional_engagement"] = max(1.0, min(10.0, round(emo_s, 1)))

    # 6. Factual reliability
    fact_s = 9.0
    # Check against dossier claims
    dossier_dict = dossier if isinstance(dossier, dict) else (asdict(dossier) if hasattr(dossier, "__dict__") else {})
    verified = dossier_dict.get("verified_claims") or []
    factual_checks = []
    if verified:
        for vc in verified[:3]:
            claim_str = vc.get("claim_text", "") if isinstance(vc, dict) else getattr(vc, "claim_text", str(vc))
            # Check overlap
            claim_words = set(re.findall(r"\w{4,}", claim_str.lower()))
            overlap = claim_words.intersection(set(re.findall(r"\w{4,}", full_lower)))
            matched = len(overlap) >= 2
            factual_checks.append({"claim": claim_str, "matched": matched})
        if not all(fc["matched"] for fc in factual_checks):
            fact_s -= 0.8
    is_forbid, forbid_msg = is_forbidden_content(full_text)
    if is_forbid:
        fact_s = 2.0
    scores["factual_reliability"] = max(1.0, min(10.0, round(fact_s, 1)))

    # 7. Originality
    orig_s = 8.5
    if any(b.lower() in full_lower for b in BANNED_PHRASES):
        orig_s -= 3.0
    scores["originality"] = max(1.0, min(10.0, round(orig_s, 1)))

    # 8. Pacing
    pace_s = 9.0
    if not (103 <= total_words <= 140):
        if 90 <= total_words <= 148:
            pace_s -= 1.0
        else:
            pace_s -= 3.0
    scores["pacing"] = max(1.0, min(10.0, round(pace_s, 1)))

    # 9. Ending quality
    ending_s = 8.8
    if any(cta.lower() in last_lower for cta in WEAK_CTAS):
        ending_s -= 4.0
    # Check if loop echoes hook
    hook_key_words = set(re.findall(r"\w{4,}", first_lower))
    last_words = set(re.findall(r"\w{4,}", last_lower))
    if hook_key_words.intersection(last_words):
        ending_s += 0.8
    scores["ending_quality"] = max(1.0, min(10.0, round(ending_s, 1)))

    # 10. Spoken rhythm
    rhythm_s = 8.8
    if any(";" in t or "(" in t for t in texts):
        rhythm_s -= 1.5
    if any(re.search(r"\b(?:moreover|furthermore|in conclusion|additionally)\b", t, re.IGNORECASE) for t in texts):
        rhythm_s -= 2.0
    scores["spoken_rhythm"] = max(1.0, min(10.0, round(rhythm_s, 1)))

    overall = round(sum(scores.values()) / len(scores), 2)
    weakest = sorted(scores.keys(), key=lambda k: scores[k])[:2]

    passed = (
        overall >= THRESHOLDS["overall"]
        and scores["factual_reliability"] >= THRESHOLDS["factual_reliability"]
        and scores["narrative_clarity"] >= THRESHOLDS["narrative_clarity"]
        and scores["hook_strength"] >= THRESHOLDS["hook_strength"]
        and all(v >= THRESHOLDS["min_individual"] for v in scores.values())
    )

    feedback = f"Overall: {overall:.1f}/10. Weakest areas: {', '.join(weakest)}."
    return CriticReport(
        scores=scores,
        overall_score=overall,
        passed=passed,
        weakest_dimensions=weakest,
        feedback=feedback,
        factual_checks=factual_checks,
    )


def evaluate_script_critique(
    script_data: Dict[str, Any],
    dossier: Any,
    client: Optional[Any] = None,
) -> CriticReport:
    """Evaluate a storytelling script using Gemini Call 2 if available, or deterministic evaluator."""
    c = client or gemini_client
    if not c or not c.is_configured():
        return _deterministic_critique(script_data, dossier)

    lines = list(script_data.get("lines") or [])
    script_text = "\n".join(f"- Line {i+1}: {ln.get('text', '')}" for i, ln in enumerate(lines))
    dossier_dict = dossier if isinstance(dossier, dict) else (asdict(dossier) if hasattr(dossier, "__dict__") else {})

    prompt = f"""You are a strict editorial critic and retention analyst for documentary YouTube Shorts.
Evaluate this script across the 10 dimensions (each 0.0 to 10.0):
1. hook_strength (<= 14 words, concrete, surprising, no banned openers)
2. narrative_clarity (clear logical sequence, <= 22 words per sentence)
3. story_progression (escalating stakes, zero middle sag)
4. curiosity_retention (open curiosity loops held until turn)
5. emotional_engagement (wonder, tension, or human stakes)
6. factual_reliability (grounded in research dossier, zero fabrications)
7. originality (fresh angle, no cliches or AI slop)
8. pacing (target 103-140 words, calibrated 2.46 WPS)
9. ending_quality (loop line echoes hook, NO call to action)
10. spoken_rhythm (conversational, spoken contractions, reads aloud naturally)

Topic: {dossier_dict.get('topic', script_data.get('topic', ''))}
Category: {dossier_dict.get('category', script_data.get('category', ''))}
Research Claims: {[c.get('claim_text') if isinstance(c, dict) else str(c) for c in dossier_dict.get('verified_claims', [])]}

Script to critique:
{script_text}

Return JSON:
{{
  "scores": {{
    "hook_strength": 8.5,
    "narrative_clarity": 8.5,
    "story_progression": 8.0,
    "curiosity_retention": 8.5,
    "emotional_engagement": 8.0,
    "factual_reliability": 9.0,
    "originality": 8.5,
    "pacing": 8.5,
    "ending_quality": 8.5,
    "spoken_rhythm": 8.5
  }},
  "overall_score": 8.45,
  "passed": true,
  "weakest_dimensions": ["story_progression", "emotional_engagement"],
  "feedback": "Concise editorial note on strengths and weak points"
}}
"""
    try:
        res = c.generate_json(
            prompt,
            system_instruction="You are CurioLoop's Chief Editorial Critic. Score rigorously. Fail scripts with generic openers, CTAs, or factual inaccuracies.",
        )
        if res and isinstance(res.get("scores"), dict):
            raw_scores = res["scores"]
            scores = {}
            for dim in CRITIC_DIMENSIONS:
                scores[dim] = float(raw_scores.get(dim, 8.0))
            overall = round(sum(scores.values()) / len(scores), 2)
            weakest = res.get("weakest_dimensions") or sorted(scores.keys(), key=lambda k: scores[k])[:2]
            passed = (
                overall >= THRESHOLDS["overall"]
                and scores["factual_reliability"] >= THRESHOLDS["factual_reliability"]
                and scores["narrative_clarity"] >= THRESHOLDS["narrative_clarity"]
                and scores["hook_strength"] >= THRESHOLDS["hook_strength"]
                and all(v >= THRESHOLDS["min_individual"] for v in scores.values())
            )
            return CriticReport(
                scores=scores,
                overall_score=overall,
                passed=passed,
                weakest_dimensions=weakest,
                feedback=str(res.get("feedback") or f"Score: {overall:.1f}"),
            )
    except Exception as e:
        logger.warning("Gemini Story Critic evaluation failed (%s), using deterministic critic.", e)

    return _deterministic_critique(script_data, dossier)


def critique_and_rewrite(
    script_data: Dict[str, Any],
    dossier: Any,
    validator_errors: Optional[List[str]] = None,
    client: Optional[Any] = None,
) -> Tuple[Dict[str, Any], CriticReport]:
    """Execute Gemini Call 2: Critique the script, and if it does not pass, perform a targeted rewrite."""
    report = evaluate_script_critique(script_data, dossier, client=client)
    if report.passed and not validator_errors:
        return script_data, report

    logger.info("Script did not meet critic thresholds (overall=%.2f, passed=%s). Executing targeted rewrite.", report.overall_score, report.passed)

    c = client or gemini_client
    if not c or not c.is_configured():
        # Deterministic targeted rewrite
        repaired = _deterministic_rewrite(script_data, report.weakest_dimensions, validator_errors)
        new_report = _deterministic_critique(repaired, dossier)
        return repaired, new_report

    lines = list(script_data.get("lines") or [])
    script_text = "\n".join(f"- Line {i+1}: {ln.get('text', '')}" for i, ln in enumerate(lines))
    dossier_dict = dossier if isinstance(dossier, dict) else (asdict(dossier) if hasattr(dossier, "__dict__") else {})

    prompt = f"""You are the master rewriter for CurioLoop YouTube Shorts.
The previous draft scored {report.overall_score:.1f}/10 and failed the editorial gate.
Weakest dimensions to fix: {report.weakest_dimensions}
Validator errors to resolve: {validator_errors or ['None']}
Editorial feedback: {report.feedback}

ORIGINAL SCRIPT:
{script_text}

TOPIC & RESEARCH FACTS:
Topic: {dossier_dict.get('topic', script_data.get('topic', ''))}
Category: {dossier_dict.get('category', script_data.get('category', ''))}
Claims to maintain: {[c.get('claim_text') if isinstance(c, dict) else str(c) for c in dossier_dict.get('verified_claims', [])]}

REWRITE INSTRUCTIONS:
1. Fix the two weakest dimensions and all validator errors.
2. Maintain strict word count: 108 to 135 spoken words (calibrated 2.46 WPS).
3. First line MUST be <= 14 words and hook immediately with concrete facts.
4. Final line MUST echo the hook without ANY call to action ("subscribe/follow").
5. Spoken contractions only, short sentences <= 22 words each.
6. Return the full rewritten script preserving scene visual types.

Return JSON:
{{
  "title": "Concise Curiosity Title",
  "lines": [
    {{
      "text": "Rewritten line...",
      "caps": "...",
      "gap": 0.28,
      "scene": {{
        "visual_type": "...",
        "headline": "...",
        "sublabel": "...",
        "mood": "...",
        "accent": "...",
        "cue": "..."
      }}
    }}
  ]
}}
"""
    try:
        res = c.generate_json(
            prompt,
            system_instruction="You are an expert script rewriter. Return only the improved valid JSON script meeting all 10 dimensions.",
        )
        if res and "lines" in res and len(res["lines"]) >= 5:
            repaired_lines = []
            for idx, ln in enumerate(res["lines"]):
                t = str(ln.get("text", "")).strip()
                if not t:
                    continue
                orig_scene = lines[min(idx, len(lines) - 1)].get("scene") if lines else {}
                sc = ln.get("scene") or orig_scene
                repaired_lines.append({
                    "text": t,
                    "caps": str(ln.get("caps") or "").strip() or ln.get("text", "").upper(),
                    "gap": float(ln.get("gap", 0.26)),
                    "scene": sc,
                })
            updated_script = copy.deepcopy(script_data)
            updated_script["title"] = str(res.get("title") or updated_script.get("title"))
            updated_script["lines"] = repaired_lines
            new_report = evaluate_script_critique(updated_script, dossier, client=client)
            return updated_script, new_report
    except Exception as e:
        logger.warning("Gemini Call 2 rewrite encountered an issue (%s), falling back to deterministic rewrite.", e)

    repaired = _deterministic_rewrite(script_data, report.weakest_dimensions, validator_errors)
    new_report = _deterministic_critique(repaired, dossier)
    return repaired, new_report


def _deterministic_rewrite(
    script_data: Dict[str, Any],
    weak_dimensions: List[str],
    validator_errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Perform deterministic targeted repairs on a script."""
    repaired = copy.deepcopy(script_data)
    lines = list(repaired.get("lines") or [])
    if not lines:
        return repaired

    # Fix hook if weak
    first_text = str(lines[0].get("text", "")).strip()
    first_lower = first_text.lower()
    for opener in BANNED_OPENERS:
        if first_lower.startswith(opener.lower()):
            first_text = re.sub(re.escape(opener), "", first_text, flags=re.IGNORECASE).strip()
            if first_text:
                first_text = first_text[0].upper() + first_text[1:]
            break

    # If hook exceeds 14 words, trim cleanly
    hook_words = first_text.split()
    if len(hook_words) > 14:
        first_text = " ".join(hook_words[:13]).rstrip(",;:") + "."

    lines[0]["text"] = first_text

    # Fix ending if it has CTA
    last_text = str(lines[-1].get("text", "")).strip()
    for cta in WEAK_CTAS:
        if cta.lower() in last_text.lower():
            # Replace CTA with an echo loop
            hook_lead = " ".join(first_text.replace(".", "").split()[:3]).lower()
            last_text = f"Decades later, archives still hold the only record of {hook_lead}."
            break
    lines[-1]["text"] = last_text

    # Fix sentence lengths <= 22 words
    new_lines = []
    for ln in lines:
        t = str(ln.get("text", "")).strip()
        words = t.split()
        if len(words) > 22:
            mid = len(words) // 2
            p1 = " ".join(words[:mid]).rstrip(",;:") + "."
            p2 = " ".join(words[mid:]).strip()
            p2 = p2[0].upper() + p2[1:]
            new_lines.append({**ln, "text": p1})
            new_lines.append({**ln, "text": p2})
        else:
            new_lines.append(ln)

    repaired["lines"] = new_lines
    return repaired


def repair_script_emergency(
    script_data: Dict[str, Any],
    validator_errors: List[str],
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute Gemini Call 3: Minimal emergency repair targeting ONLY the specific validator errors."""
    if not validator_errors:
        return script_data

    logger.info("Executing Call 3 Emergency Repair for %d validator errors.", len(validator_errors))
    c = client or gemini_client
    if not c or not c.is_configured():
        return _deterministic_rewrite(script_data, [], validator_errors)

    lines = list(script_data.get("lines") or [])
    script_text = "\n".join(f"- Line {i+1}: {ln.get('text', '')}" for i, ln in enumerate(lines))

    prompt = f"""You are an emergency code-level text editor.
The script failed strict automated validator checks. Fix ONLY these specific validator errors and nothing else:
Errors:
{validator_errors}

SCRIPT TO REPAIR:
{script_text}

Rules:
1. Make the smallest possible change to eliminate the errors.
2. Keep length 105-135 words total.
3. Keep line 1 <= 14 words.
4. Keep all sentences <= 22 words.
5. Zero CTAs or banned phrases.

Return JSON:
{{
  "lines": [
    {{"text": "Repaired line 1..."}},
    ...
  ]
}}
"""
    try:
        res = c.generate_json(
            prompt,
            system_instruction="You are an automated script repairer. Return valid JSON only fixing the exact validator errors.",
        )
        if res and "lines" in res and len(res["lines"]) >= 4:
            updated = copy.deepcopy(script_data)
            orig_lines = updated.get("lines") or []
            new_lines = []
            for i, raw_ln in enumerate(res["lines"]):
                t = str(raw_ln.get("text", "")).strip()
                if not t:
                    continue
                sc = orig_lines[min(i, len(orig_lines) - 1)].get("scene") if orig_lines else {}
                new_lines.append({
                    "text": t,
                    "caps": str(raw_ln.get("caps") or t.upper()),
                    "gap": float(raw_ln.get("gap", 0.26)),
                    "scene": sc,
                })
            updated["lines"] = new_lines
            return updated
    except Exception as e:
        logger.warning("Gemini Call 3 Emergency Repair failed (%s), applying deterministic rewrite.", e)

    return _deterministic_rewrite(script_data, [], validator_errors)
