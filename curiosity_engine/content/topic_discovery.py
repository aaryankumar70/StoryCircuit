"""Autonomous Topic Discovery across Curiosity Engine Content Pillars.
Evaluates topics on:
1. surprise_factor (1-10)
2. emotional_curiosity (1-10)
3. audience_relevance (1-10)
4. visual_novelty (1-10)
5. storytelling_potential (1-10)
Strict gate: factual_reliability (must be >= 9/10). Discards unverified claims.
Filters against 90-day cooldown and selects 2 top distinct topics.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Tuple

from curiosity_engine.config import CONTENT_PILLARS, STYLE_MAPPINGS
from curiosity_engine.content.curated_fallback import CURATED_TOPICS
from curiosity_engine.content.gemini_client import gemini_client
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.topic_discovery")


def compute_composite_score(scores: Dict[str, float]) -> float:
    """Compute weighted engagement & curiosity score across 5 core dimensions."""
    surprise = scores.get("surprise_factor", 8.0)
    curiosity = scores.get("emotional_curiosity", 8.0)
    relevance = scores.get("audience_relevance", 8.0)
    visual = scores.get("visual_novelty", 8.0)
    storytelling = scores.get("storytelling_potential", 8.0)

    return (
        surprise * 0.25 +
        curiosity * 0.20 +
        relevance * 0.20 +
        visual * 0.20 +
        storytelling * 0.15
    )


def generate_candidate_topics(count: int = 12) -> List[Dict[str, Any]]:
    """Generate 10+ candidate topics across distinct pillars with 5-factor scoring."""
    selected_pillars = random.sample(CONTENT_PILLARS, min(count, len(CONTENT_PILLARS)))

    prompt = f"""
You are the head researcher for CurioLoop, a high-quality curiosity-driven educational entertainment short-form video studio.
Discover exactly {count} fascinating, factual, and visually compelling candidate video topics across these pillars:
{', '.join(selected_pillars)}.

Evaluate each topic rigorously on 6 dimensions (scores from 1 to 10):
1. "surprise_factor": How unexpected, counter-intuitive or mind-bending is this fact?
2. "emotional_curiosity": How intensely does it make someone wonder "why" or "how"?
3. "audience_relevance": How relatable is it to human experience or modern understanding?
4. "visual_novelty": How dynamic, rich, and visually unique can the animation be?
5. "storytelling_potential": Can it sustain a 3-part micro-narrative in 25 seconds?
6. "factual_reliability": STRICT criteria. Must be backed by peer-reviewed science, verified archaeological records, or museum archives.

Also supply 2 real, accessible research source domains/URLs and 2 verified factual claims.

Return JSON in this exact structure:
{{
  "candidates": [
     {{
        "category": "Biology",
        "topic": "Why do your ears ring in absolute silence?",
        "surprise_factor": 9,
        "emotional_curiosity": 10,
        "audience_relevance": 10,
        "visual_novelty": 9,
        "storytelling_potential": 9,
        "factual_reliability": 10,
        "sources": ["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/"],
        "claims": ["Over 90% of people perceive phantom sound in anechoic chambers."],
        "hook_question": "If you step into complete silence, why does a loud ring fill your ears?"
     }}
  ]
}}
"""
    system_instruction = (
        "You are a rigorous scientific researcher creating verified educational content. "
        "Factual reliability is mandatory. Discard pseudoscience, myths, or unbacked folklore."
    )

    response = gemini_client.generate_json(prompt, system_instruction=system_instruction)
    candidates: List[Dict[str, Any]] = []

    if response and "candidates" in response and len(response["candidates"]) >= 5:
        for c in response["candidates"]:
            scores = {
                "surprise_factor": float(c.get("surprise_factor", 8)),
                "emotional_curiosity": float(c.get("emotional_curiosity", 8)),
                "audience_relevance": float(c.get("audience_relevance", 8)),
                "visual_novelty": float(c.get("visual_novelty", 8)),
                "storytelling_potential": float(c.get("storytelling_potential", 8)),
                "factual_reliability": float(c.get("factual_reliability", 10)),
            }
            c["scores"] = scores
            c["source_mode"] = "gemini"
            candidates.append(c)
        logger.info(f"Gemini discovered {len(candidates)} candidate topics.")
    else:
        logger.warning(
            "[FALLBACK] Gemini API unavailable; using curated topic catalog (0 paid API calls)."
        )
        for item in CURATED_TOPICS:
            candidates.append({
                "id": item.get("id"),
                "category": item["category"],
                "topic": item["topic"],
                "scores": item["scores"],
                "sources": item.get("sources", []),
                "claims": item.get("claims", []),
                "hook_question": item["script"]["lines"][0]["text"],
                "source_mode": "curated_fallback",
            })

    # Strict Factual Reliability Filter: Discard any topic with factual_reliability < 9.0
    verified_candidates = []
    for c in candidates:
        scores = c.get("scores", {})
        fact_score = scores.get("factual_reliability", 10.0)
        if fact_score < 9.0:
            logger.warning(f"Discarded topic '{c.get('topic')}' due to low factual reliability ({fact_score}).")
            continue

        cat = c.get("category", "Science")
        c["style"] = STYLE_MAPPINGS.get(cat, "inside-out")
        c["composite_score"] = compute_composite_score(scores)
        verified_candidates.append(c)

    return verified_candidates


def select_daily_topics(
    date_str: str,
    exclude_topics: set | None = None,
    record_usage: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Discover candidate topics, prioritize unused topics, and select 2 distinct topics."""
    candidates = generate_candidate_topics(count=12)
    excluded = {t.strip().lower() for t in (exclude_topics or set()) if t}

    if excluded:
        filtered = [c for c in candidates if c["topic"].strip().lower() not in excluded]
        if len(filtered) >= 2:
            candidates = filtered

    # Partition into fresh (not used within 90 days) vs recently used
    fresh_candidates = [
        c for c in candidates
        if not db.is_topic_recent(c["topic"], days_threshold=90)
    ]
    recent_candidates = [
        c for c in candidates
        if db.is_topic_recent(c["topic"], days_threshold=90)
    ]

    # Sort fresh by composite curiosity score descending
    fresh_candidates.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
    # Sort recent fallback by composite score descending (or keep distinctness)
    recent_candidates.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    ordered_pool = fresh_candidates + recent_candidates
    if len(fresh_candidates) < 2:
        logger.warning(
            f"Low fresh candidates count ({len(fresh_candidates)}); prioritizing fresh topics first and backfilling."
        )

    # Pick top candidate
    topic_1 = ordered_pool[0]

    # Pick second candidate with a DIFFERENT category and DIFFERENT visual style (preferring fresh)
    topic_2 = None
    for cand in ordered_pool[1:]:
        if (
            cand.get("topic") != topic_1.get("topic")
            and cand.get("category") != topic_1.get("category")
            and cand.get("style") != topic_1.get("style")
        ):
            topic_2 = cand
            break

    if not topic_2:
        for cand in ordered_pool[1:]:
            if cand.get("topic") != topic_1.get("topic"):
                topic_2 = cand
                break

    if not topic_2:
        topic_2 = ordered_pool[-1]

    logger.info(
        f"Selected Topic 1: [{topic_1.get('category')}] {topic_1.get('topic')} "
        f"({topic_1.get('style')}, {topic_1.get('source_mode', 'curated')}) - Score: {topic_1.get('composite_score', 0):.2f}"
    )
    logger.info(
        f"Selected Topic 2: [{topic_2.get('category')}] {topic_2.get('topic')} "
        f"({topic_2.get('style')}, {topic_2.get('source_mode', 'curated')}) - Score: {topic_2.get('composite_score', 0):.2f}"
    )

    if record_usage:
        db.record_topic(topic_1["topic"], topic_1["category"], date_str)
        db.record_topic(topic_2["topic"], topic_2["category"], date_str)

    return topic_1, topic_2
