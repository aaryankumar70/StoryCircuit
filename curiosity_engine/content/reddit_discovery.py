"""Ethical Reddit-Inspired Story & Discussion Discovery Source.

Reads public subreddits cleanly via read-only JSON feeds to surface intriguing
mysteries, real-life survival stories, psychological puzzles, and unusual historical
discussions.

Strict Safety & Content Rules:
- NEVER stores or exposes Reddit usernames, personal info, or external URLs.
- Strips links and identifying markers before returning story prompts.
- Marks evidence_type explicitly (documented_fact vs unexplained_mystery vs personal_account)
  so downstream scriptwriters never present unverified stories as proven fact.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("curiosity_engine.reddit_discovery")

CURATED_SUBREDDITS: List[Dict[str, str]] = [
    {"subreddit": "UnresolvedMysteries", "category": "Unexplained events", "evidence_type": "unexplained_mystery"},
    {"subreddit": "AskHistorians", "category": "History", "evidence_type": "historical_incident"},
    {"subreddit": "todayilearned", "category": "Interesting discoveries", "evidence_type": "documented_fact"},
    {"subreddit": "Damnthatsinteresting", "category": "Science", "evidence_type": "documented_fact"},
    {"subreddit": "science", "category": "Science", "evidence_type": "scientific_study"},
    {"subreddit": "space", "category": "Space", "evidence_type": "scientific_study"},
    {"subreddit": "psychology", "category": "Psychology", "evidence_type": "scientific_study"},
]

_USERNAME_PATTERN = re.compile(r"(?:/?u/[A-Za-z0-9_-]+|@[A-Za-z0-9_.-]+)", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_TIL_PREFIX_PATTERN = re.compile(r"^\s*TIL\s+(?:that\s+)?", re.IGNORECASE)
_SUB_REF_PATTERN = re.compile(r"/?r/[A-Za-z0-9_]+", re.IGNORECASE)


def sanitize_reddit_text(text: str) -> str:
    """Remove usernames, URLs, subreddit prefixes, and TIL boilerplate."""
    if not text:
        return ""
    cleaned = _URL_PATTERN.sub("", str(text))
    cleaned = _USERNAME_PATTERN.sub("a commenter", cleaned)
    cleaned = _SUB_REF_PATTERN.sub("", cleaned)
    cleaned = _TIL_PREFIX_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;,.")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def is_suitable_reddit_post(post: Dict[str, Any]) -> bool:
    """Filter out NSFW, low-signal, promotional, or deleted Reddit submissions."""
    if not isinstance(post, dict):
        return False
    if post.get("over_18") or post.get("stickied") or post.get("removed_by_category"):
        return False
    title = str(post.get("title") or "").strip()
    if len(title) < 25 or len(title) > 220:
        return False
    low = title.lower()
    blocked_terms = (
        "[meta]",
        "megathread",
        "upvote",
        "ama ",
        "buy ",
        "discount",
        "promo",
        "nsfw",
        "politics",
        "election",
    )
    if any(b in low for b in blocked_terms):
        return False
    ups = int(post.get("ups") or post.get("score") or 0)
    if ups < 150:
        return False
    return True


class RedditDiscoverySource:
    """Non-intrusive public Reddit discussion & curiosity seed fetcher."""

    USER_AGENT = "CurioLoopEditorialResearch/1.0 (+educational-short-script-discovery)"

    def __init__(self, http_get=requests.get, timeout_sec: float = 8.0) -> None:
        self.http_get = http_get
        self.timeout_sec = float(timeout_sec)

    def fetch_story_seeds(
        self,
        subreddits: Optional[List[Dict[str, str]]] = None,
        limit_per_sub: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch sanitized story seeds from curated subreddits; fails gracefully offline."""
        targets = subreddits or CURATED_SUBREDDITS
        seeds: List[Dict[str, Any]] = []

        for meta in targets:
            sub = meta["subreddit"]
            url = f"https://www.reddit.com/r/{sub}/top.json"
            try:
                resp = self.http_get(
                    url,
                    params={"t": "week", "limit": limit_per_sub},
                    headers={"User-Agent": self.USER_AGENT},
                    timeout=self.timeout_sec,
                )
                if getattr(resp, "status_code", 0) != 200:
                    continue
                payload = resp.json()
                children = ((payload or {}).get("data") or {}).get("children") or []
            except Exception as exc:
                logger.debug("Reddit discovery offline/skipped for r/%s: %s", sub, exc)
                continue

            for child in children:
                post = (child or {}).get("data") or {}
                if not is_suitable_reddit_post(post):
                    continue
                topic_clean = sanitize_reddit_text(post.get("title", ""))
                selftext_clean = sanitize_reddit_text(str(post.get("selftext") or "")[:360])
                if not topic_clean or len(topic_clean) < 20:
                    continue

                ups = int(post.get("ups") or 0)
                num_comments = int(post.get("num_comments") or 0)
                seeds.append(
                    {
                        "category": meta["category"],
                        "topic": topic_clean,
                        "angle_note": selftext_clean[:240] if selftext_clean else topic_clean,
                        "evidence_type": meta["evidence_type"],
                        "discovery_origin": "reddit_inspired",
                        "scores": {
                            "surprise_factor": 8.6 if ups > 1000 else 8.0,
                            "emotional_curiosity": 8.8 if num_comments > 100 else 8.2,
                            "audience_relevance": 8.4,
                            "visual_novelty": 8.2,
                            "storytelling_potential": 8.8,
                            "hook_strength": 8.5,
                            "originality": 8.5,
                            "ending_payoff": 8.2,
                            "factual_reliability": 9.2 if meta["evidence_type"] in ("documented_fact", "historical_incident", "scientific_study") else 9.0,
                        },
                        # External links / Reddit post permalinks omitted cleanly from published output
                        "sources": [],
                        "claims": [topic_clean],
                    }
                )
        return seeds


reddit_discovery = RedditDiscoverySource()
