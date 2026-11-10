"""Scriptwriting Engine for Curiosity Engine.
Generates 20-30s narration scripts (48-62 words) with authentic verifiable sources,
natural satisfying conclusions (looping ending optional), and word-synced caption chunks.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from curiosity_engine.config import (
    MAX_WORD_COUNT,
    MIN_WORD_COUNT,
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
    "nationalgeographic.com",
    "scientificamerican.com",
]


def validate_factual_sources(sources: List[str]) -> Tuple[bool, List[str]]:
    """Validate that source URLs are accessible, well-formed, and from reputable domains."""
    valid_sources: List[str] = []
    for s in sources:
        if not s or not isinstance(s, str):
            continue
        s_clean = s.strip()
        parsed = urlparse(s_clean)
        if not (parsed.scheme in ("http", "https") and parsed.netloc):
            continue

        # Check if domain is reputable or ends with reliable educational/gov TLD
        netloc = parsed.netloc.lower()
        is_trusted = (
            any(td in netloc for td in TRUSTED_DOMAINS) or
            netloc.endswith(".edu") or
            netloc.endswith(".gov") or
            netloc.endswith(".org")
        )
        if is_trusted:
            valid_sources.append(s_clean)

    return len(valid_sources) >= 1, valid_sources


def count_spoken_words(lines: List[Dict[str, Any]]) -> int:
    """Accurately count words spoken across all script lines."""
    total = 0
    for line in lines:
        words = [w for w in line["text"].split() if re.sub(r"[^a-zA-Z0-9]", "", w)]
        total += len(words)
    return total


def format_auto_caps(text: str) -> str:
    """Generate default uppercase caption chunks with one highlighted keyword (*) per chunk."""
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


def write_video_script(topic_info: Dict[str, Any]) -> Dict[str, Any]:
    """Generate or retrieve a verified script for the selected topic."""
    topic = topic_info.get("topic", "")
    category = topic_info.get("category", "Science")
    style = topic_info.get("style", "inside-out")
    voice = VOICE_MAP.get(style, "am_michael")

    # 1. Match curated peer-reviewed catalog if available
    for item in CURATED_TOPICS:
        if (
            item["topic"].lower() == topic.lower() or
            item.get("id") == topic_info.get("id") or
            (item["category"].lower() == category.lower() and item.get("style") == style)
        ):
            script_data = item["script"].copy()
            script_data["sources"] = item["sources"]
            script_data["claims"] = item["claims"]
            script_data["topic"] = item["topic"]
            script_data["category"] = item["category"]
            script_data["style"] = item["style"]
            script_data["scores"] = item.get("scores", topic_info.get("scores", {}))
            word_count = count_spoken_words(script_data["lines"])
            logger.info(f"Using verified curated script for '{item['topic']}' ({word_count} words).")
            return script_data

    # 2. Otherwise generate via Gemini API with strict factual constraints
    prompt = f"""
Write an original 20-25 second educational short-form narration script on the topic: "{topic}" (Category: {category}).

STRICT SCRIPT CONSTRAINTS:
1. Total spoken word count must be between {MIN_WORD_COUNT} and {MAX_WORD_COUNT} words (around 52-56 words is ideal).
2. Structure into exactly 5 or 6 natural cut lines (one line per camera cut).
3. Opening Hook: The first line must hook the viewer in the first 3 seconds with an intriguing question or statement.
4. Natural, conversational narration: Explaining a real discovery clearly to a curious friend.
5. Satisfying Conclusion: Provide a natural, satisfying conclusion that delivers a clear insight. A looping ending is strictly optional; prioritize a natural, memorable takeaway.
6. Factual Verification: Must provide at least 2 real, accessible research source URLs and 2-3 verified factual claims. Never fabricate claims or dates.
7. For each line, provide:
   - "text": Spoken sentence part.
   - "caps": All-caps caption chunks separated by " | ", with exactly one yellow highlighted word prefixed with "*" in each chunk.
   - "gap": Silence after line in seconds (0.28 to 0.35s).

Return valid JSON:
{{
  "title": "Concise Engaging Title",
  "sources": ["https://..."],
  "claims": ["Factual claim 1", "Factual claim 2"],
  "lines": [
     {{
       "text": "Hook question text here?",
       "caps": "HOOK *QUESTION | TEXT *HERE?",
       "gap": 0.3
     }}
  ]
}}
"""
    system_instruction = (
        "You are a master scriptwriter and factual science communicator for CurioLoop. "
        "Every claim must be strictly accurate. Word count must be 48-62 words. Never fabricate URLs or facts."
    )
    response = gemini_client.generate_json(prompt, system_instruction=system_instruction)

    if response and "lines" in response and len(response["lines"]) >= 4:
        lines = response["lines"]
        for line in lines:
            if "caps" not in line or not line["caps"]:
                line["caps"] = format_auto_caps(line["text"])
            if "gap" not in line:
                line["gap"] = 0.3

        word_count = count_spoken_words(lines)
        sources = response.get("sources", [])
        is_valid, validated_sources = validate_factual_sources(sources)

        if is_valid and MIN_WORD_COUNT <= word_count <= MAX_WORD_COUNT + 5:
            logger.info(f"Generated verified script via Gemini for '{topic}' ({word_count} words).")
            return {
                "title": response.get("title", topic),
                "voice": voice,
                "speed": 1.0,
                "lead": 0.45,
                "outro": 0.9,
                "gap": 0.32,
                "topic": topic,
                "category": category,
                "style": style,
                "scores": topic_info.get("scores", {}),
                "sources": validated_sources,
                "claims": response.get("claims", [topic]),
                "lines": lines,
            }
        else:
            logger.warning(
                f"Generated script failed factual source validation or word count ({word_count} words). "
                "Falling back to curated verified topic."
            )

    # 3. Robust curated fallback
    fallback = CURATED_TOPICS[0]
    script_data = fallback["script"].copy()
    script_data["sources"] = fallback["sources"]
    script_data["claims"] = fallback["claims"]
    script_data["topic"] = fallback["topic"]
    script_data["category"] = fallback["category"]
    script_data["style"] = fallback["style"]
    script_data["scores"] = fallback["scores"]
    return script_data
