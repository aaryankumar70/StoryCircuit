"""Autonomous Topic Discovery across Curiosity Engine Content Pillars.

Evaluates story candidates rigorously on:
- originality
- hook_strength (0-3s opening appeal)
- storytelling_potential
- emotional_curiosity
- visual_novelty
- ending_payoff
- factual_reliability (>= 9.0 strict quality gate)

Combines Gemini research, ethical public Reddit-inspired story seeds (without usernames
or links), and verified curated fallback narratives. Discards weak or generic topics.
"""
from __future__ import annotations

import logging
import os
import random
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.config import CONTENT_PILLARS, STYLE_MAPPINGS
from curiosity_engine.content.curated_fallback import CURATED_TOPICS
from curiosity_engine.content.gemini_client import gemini_client
from curiosity_engine.content.reddit_discovery import reddit_discovery
from curiosity_engine.state.db import db

logger = logging.getLogger("curiosity_engine.topic_discovery")

MIN_COMPOSITE_SCORE = 7.5
MIN_HOOK_SCORE = 7.0
MIN_PAYOFF_SCORE = 7.0


def compute_composite_score(scores: Dict[str, float]) -> float:
    """Compute weighted curiosity, originality, visual, and storytelling score."""
    surprise = float(scores.get("surprise_factor", 8.0))
    curiosity = float(scores.get("emotional_curiosity", 8.0))
    relevance = float(scores.get("audience_relevance", 8.0))
    visual = float(scores.get("visual_novelty", 8.0))
    storytelling = float(scores.get("storytelling_potential", 8.0))
    hook = float(scores.get("hook_strength", surprise))
    originality = float(scores.get("originality", 8.0))
    payoff = float(scores.get("ending_payoff", storytelling))

    return round(
        surprise * 0.18
        + curiosity * 0.18
        + hook * 0.18
        + storytelling * 0.14
        + visual * 0.12
        + originality * 0.10
        + payoff * 0.06
        + relevance * 0.04,
        3,
    )


def evaluate_topic_candidate(candidate: Dict[str, Any]) -> Tuple[bool, str]:
    """Reject weak, generic, clickbait, or poorly substantiated topics."""
    topic = str(candidate.get("topic") or "").strip()
    if len(topic) < 12:
        return False, "Topic too short"

    low = topic.lower()
    if low.startswith("did you know"):
        return False, "Generic 'Did you know' opener discouraged"

    scores = candidate.get("scores") or {}
    fact_score = float(scores.get("factual_reliability", 10.0))
    hook_score = float(scores.get("hook_strength", scores.get("surprise_factor", 8.0)))
    payoff_score = float(scores.get("ending_payoff", scores.get("storytelling_potential", 8.0)))
    composite = compute_composite_score(scores)

    if fact_score < 9.0:
        return False, f"Low factual reliability ({fact_score})"
    if hook_score < MIN_HOOK_SCORE:
        return False, f"Weak hook potential ({hook_score})"
    if payoff_score < MIN_PAYOFF_SCORE:
        return False, f"Weak ending payoff ({payoff_score})"
    if composite < MIN_COMPOSITE_SCORE:
        return False, f"Composite quality score below threshold ({composite:.2f})"
    return True, "accepted"


def generate_candidate_topics(
    count: int = 12,
    include_reddit: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Generate 10+ candidate storytelling topics across pillars, combining Gemini + Reddit seeds + curated catalog."""
    selected_pillars = random.sample(CONTENT_PILLARS, min(count, len(CONTENT_PILLARS)))

    reddit_seeds: List[Dict[str, Any]] = []
    use_reddit = ("PYTEST_CURRENT_TEST" not in os.environ) if include_reddit is None else bool(include_reddit)
    if use_reddit:
        try:
            reddit_seeds = reddit_discovery.fetch_story_seeds(limit_per_sub=3)
            if reddit_seeds:
                logger.info("Discovered %d sanitized Reddit-inspired story seeds.", len(reddit_seeds))
        except Exception as exc:
            logger.debug("Reddit discovery unavailable: %s", exc)

    reddit_hint_block = ""
    if reddit_seeds:
        seed_lines = [
            f"- [{s['category']} | {s['evidence_type']}] {s['topic']}"
            for s in reddit_seeds[:6]
        ]
        reddit_hint_block = (
            "\nPUBLIC DISCUSSION ANGLES TO INSPIRE ORIGINAL RESEARCH (never copy verbatim, never mention usernames or Reddit links):\n"
            + "\n".join(seed_lines)
            + "\n"
        )

    prompt = f"""
You are the head editorial director for CurioLoop, an engaging short-form storytelling studio (25-45s vertical videos).
Discover exactly {count} compelling, factual, visually rich story candidates across these pillars:
{', '.join(selected_pillars)}.

Prioritize:
- Fascinating real-life experiences and human survival stories
- Unusual historical incidents and strange discoveries
- Unexplained events with credible evidence (clearly distinguishing documented facts vs hypotheses)
- Psychological/behavioral phenomena and breakthroughs in science/space/technology
{reddit_hint_block}
Evaluate each candidate from 1-10 on:
1. "originality": Fresh narrative angle, never a generic trivia cliché.
2. "hook_strength": Can line 1 stop a viewer in 0-3 seconds WITHOUT "Did you know?"
3. "surprise_factor": Counter-intuitive turn or unexpected detail.
4. "emotional_curiosity": Stakes, tension, or wonder that keeps viewers watching.
5. "audience_relevance": Relatable human angle.
6. "visual_novelty": Clear visual sequence potential across cuts.
7. "storytelling_potential": Supports a 25-45s narrative arc (hook -> tension -> payoff).
8. "ending_payoff": Satisfying, memorable resolution (no hollow cliffhangers).
9. "factual_reliability": STRICT >= 9/10 for documented stories; distinguish evidence from open hypotheses honestly.

Include "evidence_type" (one of: "documented_fact", "historical_incident", "scientific_study", "unexplained_mystery", "personal_account"),
at least 1-2 reputable research URLs for internal fact verification, and 2-3 verified factual claims.

Return JSON:
{{
  "candidates": [
     {{
        "category": "Survival",
        "topic": "...",
        "evidence_type": "historical_incident",
        "discovery_origin": "gemini_research",
        "originality": 9,
        "hook_strength": 9.5,
        "surprise_factor": 9,
        "emotional_curiosity": 9.5,
        "audience_relevance": 9,
        "visual_novelty": 9,
        "storytelling_potential": 9.5,
        "ending_payoff": 9.2,
        "factual_reliability": 9.5,
        "sources": ["https://www.britannica.com/..."],
        "claims": ["Verified fact 1", "Verified fact 2"],
        "hook_question": "Compelling 0-3s hook sentence..."
     }}
  ]
}}
"""
    system_instruction = (
        "You are an editorial story producer for CurioLoop. Reject bland trivia. "
        "Never fabricate facts, URLs, or pretend unverified accounts are proven scientific fact."
    )

    response = gemini_client.generate_json(prompt, system_instruction=system_instruction)
    candidates: List[Dict[str, Any]] = []

    if response and "candidates" in response and len(response["candidates"]) >= 4:
        for c in response["candidates"]:
            scores = {
                "surprise_factor": float(c.get("surprise_factor", 8)),
                "emotional_curiosity": float(c.get("emotional_curiosity", 8)),
                "audience_relevance": float(c.get("audience_relevance", 8)),
                "visual_novelty": float(c.get("visual_novelty", 8)),
                "storytelling_potential": float(c.get("storytelling_potential", 8)),
                "hook_strength": float(c.get("hook_strength", c.get("surprise_factor", 8))),
                "originality": float(c.get("originality", 8)),
                "ending_payoff": float(c.get("ending_payoff", c.get("storytelling_potential", 8))),
                "factual_reliability": float(c.get("factual_reliability", 9.5)),
            }
            c["scores"] = scores
            c["evidence_type"] = c.get("evidence_type") or "documented_fact"
            c["discovery_origin"] = c.get("discovery_origin") or "gemini_research"
            c["source_mode"] = "gemini"
            candidates.append(c)
        logger.info("Gemini discovered %d candidate story topics.", len(candidates))
    else:
        if reddit_seeds and gemini_client.is_configured():
            candidates.extend(reddit_seeds)
        logger.warning(
            "[FALLBACK] Using upgraded curated story catalog (0 paid API calls)."
        )
        for item in CURATED_TOPICS:
            candidates.append({
                "id": item.get("id"),
                "category": item["category"],
                "topic": item["topic"],
                "scores": item["scores"],
                "evidence_type": item.get("evidence_type", "documented_fact"),
                "discovery_origin": item.get("discovery_origin", "curated_research"),
                "sources": item.get("sources", []),
                "claims": item.get("claims", []),
                "hook_question": item["script"]["lines"][0]["text"],
                "source_mode": "curated_fallback",
            })

    verified_candidates: List[Dict[str, Any]] = []
    for c in candidates:
        accepted, reason = evaluate_topic_candidate(c)
        if not accepted:
            logger.warning("Discarded weak/unverified topic '%s': %s", c.get("topic"), reason)
            continue

        cat = c.get("category", "Science")
        c["style"] = c.get("style") or STYLE_MAPPINGS.get(cat, "inside-out")
        c["composite_score"] = compute_composite_score(c["scores"])
        verified_candidates.append(c)

    return verified_candidates


def select_daily_topics(
    date_str: str,
    exclude_topics: set | None = None,
    record_usage: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Discover candidate topics, prioritize fresh compelling stories, and select 2 distinct topics."""
    candidates = generate_candidate_topics(count=12)
    excluded = {t.strip().lower() for t in (exclude_topics or set()) if t}

    if excluded:
        filtered = [c for c in candidates if c["topic"].strip().lower() not in excluded]
        if len(filtered) >= 2:
            candidates = filtered

    fresh_candidates = [
        c for c in candidates
        if not db.is_topic_recent(c["topic"], days_threshold=90)
    ]
    recent_candidates = [
        c for c in candidates
        if db.is_topic_recent(c["topic"], days_threshold=90)
    ]

    fresh_candidates.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
    recent_candidates.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    ordered_pool = fresh_candidates + recent_candidates
    if len(fresh_candidates) < 2:
        logger.warning(
            "Low fresh candidates count (%d); prioritizing fresh topics first and backfilling.",
            len(fresh_candidates),
        )

    topic_1 = ordered_pool[0]

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
        "Selected Topic 1: [%s] %s (%s, %s, evidence=%s) - Score: %.2f",
        topic_1.get("category"),
        topic_1.get("topic"),
        topic_1.get("style"),
        topic_1.get("source_mode", "curated"),
        topic_1.get("evidence_type", "documented_fact"),
        topic_1.get("composite_score", 0),
    )
    logger.info(
        "Selected Topic 2: [%s] %s (%s, %s, evidence=%s) - Score: %.2f",
        topic_2.get("category"),
        topic_2.get("topic"),
        topic_2.get("style"),
        topic_2.get("source_mode", "curated"),
        topic_2.get("evidence_type", "documented_fact"),
        topic_2.get("composite_score", 0),
    )

    if record_usage:
        db.record_topic(topic_1["topic"], topic_1["category"], date_str)
        db.record_topic(topic_2["topic"], topic_2["category"], date_str)

    return topic_1, topic_2
