"""Intelligent, Link-Free YouTube Shorts Metadata, Titles & Description Generator.

Rules enforced:
- Compelling, natural curiosity titles (avoiding ALL-CAPS hype & keyword stuffing);
  adds `#Shorts` only when fitting (vertical short <= 60s).
- Concise engaging story summary descriptions with viewer engagement prompt and
  a small curated set of `#hashtags` (3-5).
- STRICTLY NO EXTERNAL LINKS in YouTube descriptions (no http/https URLs,
  no Reddit links, no affiliate/social/promotional links).
- Separate `youtube_tags` metadata keyword array distinct from description hashtags.
- Never invents sources or claims unverified stories as proven fact.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from curiosity_engine.content.gemini_client import gemini_client

logger = logging.getLogger("curiosity_engine.description_generator")

KNOWN_SOURCE_TITLES: Dict[str, str] = {
    "ncbi.nlm.nih.gov": "National Center for Biotechnology Information (NIH/NLM)",
    "sciencedirect.com": "Hearing Research Journal (ScienceDirect / Elsevier)",
    "nature.com": "Nature Publishing Group",
    "science.org": "American Association for the Advancement of Science (AAAS)",
    "oxrep.ox.ac.uk": "Oxford Roman Economy Project (Oxford University)",
    "franckgoddio.org": "Franck Goddio / IEASM Underwater Archaeology Excavations",
    "unesco.org": "UNESCO Underwater Cultural Heritage Database",
    "nasa.gov": "NASA Heliophysics & Planetary Science Archives",
    "esa.int": "European Space Agency (ESA) Science Operations",
    "britannica.com": "Encyclopaedia Britannica Academic Edition",
    "smithsonianmag.com": "Smithsonian Magazine Archives",
    "planetary.org": "The Planetary Society",
    "arxiv.org": "arXiv Astrophysics Preprint Archive",
}

BRAND_SIGN_OFF = "CurioLoop • Daily curiosity grounded in real stories, history, and science."

_EXTERNAL_LINK_PATTERN = re.compile(
    r"(?:https?://\S+|www\.\S+|(?:reddit\.com|amzn\.to|bit\.ly|t\.co|linktr\.ee)\S*|(?<!\w)/?[ru]/[A-Za-z0-9_]+)",
    re.IGNORECASE,
)


def infer_source_title(url: str) -> str:
    """Infer an academic or institutional label from an internal reference URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    for key, title in KNOWN_SOURCE_TITLES.items():
        if key in domain:
            return title
    clean_domain = domain.replace("www.", "").capitalize()
    return f"Research Archive ({clean_domain})"


def validate_description_sources(description: str, allowed_sources: List[str]) -> Tuple[bool, List[str]]:
    """Verify any URLs present against allowed internal sources (legacy helper)."""
    found_urls = re.findall(r"https?://[^\s)\]]+", description)
    issues = []
    cleaned_urls = [u.rstrip(".,;!?:") for u in found_urls]
    allowed_set = {s.strip().rstrip("/") for s in allowed_sources if s}
    for url in cleaned_urls:
        if url.strip().rstrip("/") not in allowed_set:
            issues.append(f"Unverified or hallucinated URL detected: {url}")
    return len(issues) == 0, issues


def validate_no_external_links(text: str) -> Tuple[bool, List[str]]:
    """Strictly forbid external URLs, Reddit links, usernames, or promo links inside descriptions."""
    matches = _EXTERNAL_LINK_PATTERN.findall(text or "")
    issues = [f"Disallowed external link or handle in description: {m}" for m in matches]
    return len(issues) == 0, issues


def strip_external_links(text: str) -> str:
    """Remove any external URLs or social handles cleanly from text."""
    cleaned = _EXTERNAL_LINK_PATTERN.sub("", text or "")
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def generate_youtube_title(
    topic: str,
    script_data: Optional[Dict[str, Any]] = None,
    duration_sec: Optional[float] = None,
) -> str:
    """Produce a compelling, natural YouTube title without all-caps hype or stray hashtag stuffing."""
    raw_title = str((script_data or {}).get("title") or topic or "CurioLoop Story").strip()
    raw_title = strip_external_links(raw_title)
    # Strip ALL hashtags from the title text cleanly so only one optional trailing #Shorts can be placed
    raw_title = re.sub(r"\s*#[A-Za-z0-9_]+\b", "", raw_title, flags=re.IGNORECASE).strip(" -|")

    # Convert shouting ALL CAPS words cleanly while preserving standard acronyms (NASA, DNA, BC, AD, fMRI)
    acronyms = {"NASA", "ESA", "DNA", "BC", "AD", "GIC", "FMRI", "WOW", "AI", "HZ", "DB", "LANSA", "IEASM", "ETH"}
    words = raw_title.split()
    fixed_words = []
    for idx, w in enumerate(words):
        bare = re.sub(r"[^A-Za-z0-9]", "", w)
        if len(bare) >= 3 and bare.isupper() and bare.upper() not in acronyms:
            fixed_words.append(w.capitalize() if idx == 0 else w.lower())
        else:
            fixed_words.append(w)
    title_clean = " ".join(fixed_words)
    if title_clean:
        title_clean = title_clean[0].upper() + title_clean[1:]

    # Include #Shorts only when duration <= 58s (and stays clean within 95 chars)
    is_short = duration_sec is None or float(duration_sec) <= 58.0
    if is_short and len(title_clean) <= 82:
        return f"{title_clean} #Shorts"
    return title_clean[:95].rstrip()


def recommend_hashtags(
    topic: str,
    category: str,
    script_data: Optional[Dict[str, Any]] = None,
    trend_signals: Optional[Dict[str, Any]] = None,
    recent_hashtags: Optional[List[List[str]]] = None,
) -> Dict[str, Any]:
    """Select 3-5 relevant hashtags, distinguishing verified trend evidence from recommendations."""
    cat_clean = re.sub(r"[^A-Za-z0-9]", "", category or "Science") or "Science"
    topic_words = [
        w.capitalize()
        for w in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", f"{topic} {(script_data or {}).get('title', '')}")
        if w.lower() not in {"what", "when", "where", "which", "while", "with", "into", "from", "that", "this", "your", "their", "about", "could", "would", "after", "never", "shorts", "almost"}
    ]
    topic_tag = f"#{topic_words[0]}" if topic_words else "#TrueStory"

    chosen: List[str] = []
    trend_used: List[str] = []
    signals = trend_signals or {}
    observed = bool(signals.get("observed") and signals.get("trending_tags"))
    topic_tokens_low = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", f"{topic} {category}")}

    if observed:
        for raw_tag in signals.get("trending_tags") or []:
            clean = "#" + re.sub(r"[^A-Za-z0-9]", "", str(raw_tag).lstrip("#"))
            if len(clean) < 3:
                continue
            stem = clean[1:].lower()
            if stem in topic_tokens_low or cat_clean.lower() in stem or stem in {"shorts", "truestory", "sciencefacts", "historyfacts"}:
                if clean not in chosen:
                    chosen.append(clean)
                    trend_used.append(clean)
            if len(chosen) >= 3:
                break

    cat_secondary = {
        "History": "#AncientHistory",
        "Survival": "#TrueSurvival",
        "Psychology": "#HumanBehavior",
        "Biology": "#HumanBody",
        "Space": "#Astronomy",
        "Mysteries": "#UnsolvedMystery",
        "Unexplained events": "#TrueMystery",
        "Technology": "#ScienceFacts",
        "Science": "#RealScience",
    }.get(category, "#Storytelling")

    candidates = [topic_tag, f"#{cat_clean}", cat_secondary, "#CurioLoop", "#Shorts", "#CuriousMinds"]
    for cand in candidates:
        if len(chosen) >= 5:
            break
        if cand.lower() not in {c.lower() for c in chosen}:
            chosen.append(cand)

    # Rotate 5th optional tag if exact hashtag list was used recently
    recent_sets = [tuple(x) for x in (recent_hashtags or [])]
    if tuple(chosen) in recent_sets and "#DidYouKnow" not in chosen and len(chosen) >= 4:
        chosen = chosen[:3] + ["#TrueFacts", "#Shorts"]

    chosen = chosen[:5]
    if "#Shorts" not in chosen and len(chosen) < 5:
        chosen.append("#Shorts")

    return {
        "hashtags": chosen[:5],
        "trend_evidence_available": observed and len(trend_used) > 0,
        "evidence_mode": "trend_informed" if (observed and len(trend_used) > 0) else "recommended_no_trend_data",
        "trend_matched_tags": trend_used,
    }


def build_youtube_tags(
    topic: str,
    category: str,
    script_data: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Generate separate YouTube API `tags` keywords (no `#` prefixes, distinct from hashtags)."""
    base_tags: List[str] = ["CurioLoop", category.strip(), "Shorts", "Storytelling"]
    stopwords = {
        "what", "when", "where", "which", "while", "with", "into", "from", "that", "this",
        "your", "their", "about", "there", "could", "would", "after", "before", "only", "alone",
        "almost", "turns", "still", "because", "under", "found", "never",
    }
    raw_phrase = f"{topic} {(script_data or {}).get('title', '')}"
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", raw_phrase):
        low = tok.lower()
        if low in stopwords:
            continue
        clean_kw = tok.capitalize() if tok.islower() else tok
        if clean_kw not in base_tags:
            base_tags.append(clean_kw)
        if len(base_tags) >= 12:
            break

    cat_map = {
        "History": ["AncientHistory", "TrueHistory", "Archaeology"],
        "Survival": ["SurvivalStory", "TrueSurvival"],
        "Mysteries": ["UnsolvedMystery", "TrueMystery"],
        "Unexplained events": ["UnexplainedHistory", "MysteryCase"],
        "Psychology": ["HumanBehavior", "PsychologyFacts"],
        "Biology": ["HumanBody", "Neuroscience"],
        "Space": ["Astronomy", "SpaceDiscovery"],
        "Technology": ["SolarStorm", "Infrastructure"],
        "Science": ["ScienceStory", "RealScience"],
        "Nature": ["DeepSea", "Wildlife"],
    }
    for kw in cat_map.get(category, ["CuriousStories"]):
        if kw not in base_tags:
            base_tags.append(kw)
    return base_tags[:15]


class DescriptionGenerator:
    """Generates clean, link-free YouTube Shorts descriptions and separated metadata tags."""

    def __init__(self):
        self.brand_sign_off = BRAND_SIGN_OFF

    def generate(
        self,
        topic: str,
        category: str,
        script_data: Dict[str, Any],
        sources: Optional[List[str]] = None,
        claims: Optional[List[str]] = None,
        trend_signals: Optional[Dict[str, Any]] = None,
        recent_hashtags: Optional[List[List[str]]] = None,
    ) -> Dict[str, Any]:
        """Generate natural description with zero external links plus separate API tags and hashtags."""
        verified_sources = [s.strip() for s in (sources or script_data.get("sources", [])) if s]
        verified_claims = claims or script_data.get("claims", [])
        title = generate_youtube_title(topic, script_data)
        youtube_tags = build_youtube_tags(topic, category, script_data)
        hash_meta = recommend_hashtags(
            topic=topic,
            category=category,
            script_data=script_data,
            trend_signals=trend_signals,
            recent_hashtags=recent_hashtags,
        )

        if gemini_client.is_configured():
            try:
                ai_desc = self._generate_with_ai(
                    topic=topic,
                    category=category,
                    title=title,
                    script_data=script_data,
                    claims=verified_claims,
                    youtube_tags=youtube_tags,
                    hashtags=hash_meta["hashtags"],
                )
                if ai_desc and ai_desc.get("full_description"):
                    ok_links, link_issues = validate_no_external_links(ai_desc["full_description"])
                    if ok_links and self._description_matches_topic(ai_desc["full_description"], topic, category, script_data):
                        ai_desc["topic"] = topic
                        ai_desc["recommended_title"] = title
                        ai_desc["youtube_tags"] = youtube_tags
                        ai_desc["hashtags"] = hash_meta["hashtags"]
                        ai_desc["hashtag_metadata"] = hash_meta
                        ai_desc["further_reading"] = []
                        ai_desc["sources_recorded_internally"] = len(verified_sources)
                        return ai_desc
                    logger.warning("AI description failed safety/topic-alignment (%s); using structured generator.", link_issues)
            except Exception as e:
                logger.warning("Gemini description generation failed (%s); using structured fallback.", e)

        return self._generate_structured(
            topic=topic,
            category=category,
            title=title,
            script_data=script_data,
            verified_sources=verified_sources,
            claims=verified_claims,
            youtube_tags=youtube_tags,
            hash_meta=hash_meta,
        )

    @staticmethod
    def _description_matches_topic(
        description: str,
        topic: str,
        category: str,
        script_data: Dict[str, Any],
    ) -> bool:
        """Guard against stale/off-topic AI description hallucinations."""
        desc_low = str(description or "").lower()
        ref = f"{topic} {(script_data or {}).get('title', '')}".lower()
        keywords = [
            w for w in re.findall(r"[a-z]{4,}", ref)
            if w not in {"what", "when", "where", "which", "while", "with", "into", "from", "that", "this", "your", "their", "about", "could", "would", "today", "story"}
        ]
        if not keywords:
            return True
        hits = sum(1 for kw in set(keywords) if kw in desc_low)
        return hits >= 1

    def _generate_structured(
        self,
        topic: str,
        category: str,
        title: str,
        script_data: Dict[str, Any],
        verified_sources: List[str],
        claims: List[str],
        youtube_tags: List[str],
        hash_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        lines = script_data.get("lines") or []
        evidence_type = script_data.get("evidence_type", "documented_fact")

        if lines:
            hook = strip_external_links(str(lines[0].get("text", "")))
        else:
            hook = f"What happened inside this story behind {topic.lower().rstrip('?')}?"

        if claims:
            summary_sentences = [strip_external_links(str(c).rstrip(".") + ".") for c in claims[:2]]
            body = " ".join(summary_sentences)
        elif len(lines) >= 3:
            body = " ".join(strip_external_links(str(ln.get("text", ""))) for ln in lines[1:3])
        else:
            body = f"A concise look at the real details behind {topic.lower().rstrip('?')}."

        if evidence_type == "unexplained_mystery":
            body += " Key evidence remains documented, while final conclusions stay open to investigation."
        elif evidence_type == "personal_account":
            body += " Presented carefully to separate eyewitness details from proven record."

        engagement_by_cat = {
            "History": "Which forgotten historical detail in this story surprised you most?",
            "Mysteries": "What explanation fits the physical evidence best in your view?",
            "Unexplained events": "How would you weigh the documented evidence in this case?",
            "Survival": "Would you have remembered that rule under extreme pressure?",
            "Psychology": "Notice how quickly your mind filled in what wasn't actually there?",
            "Biology": "What other strange instinct of the human body puzzles you?",
            "Space": "Do you think this signal points to rare astrophysics or something deeper?",
        }
        engagement = engagement_by_cat.get(
            category,
            "What stood out most to you in the final reveal of this story?",
        )

        resolved_hash_meta = hash_meta or recommend_hashtags(topic, category, script_data)
        hashtags = resolved_hash_meta["hashtags"][:5]

        parts = [
            hook,
            "",
            body,
            "",
            engagement,
            "",
            self.brand_sign_off,
            "",
            " ".join(hashtags),
        ]
        full_description = strip_external_links("\n".join(parts)).strip()

        return {
            "topic": topic,
            "recommended_title": title,
            "hook": hook,
            "body": body,
            "further_reading": [],
            "sources_recorded_internally": len(verified_sources),
            "sign_off": self.brand_sign_off,
            "engagement_question": engagement,
            "hashtags": hashtags,
            "hashtag_metadata": resolved_hash_meta,
            "youtube_tags": youtube_tags,
            "full_description": full_description,
            "char_count": len(full_description),
            "validated": True,
        }

    def _generate_with_ai(
        self,
        topic: str,
        category: str,
        title: str,
        script_data: Dict[str, Any],
        claims: List[str],
        youtube_tags: List[str],
        hashtags: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        claims_str = "\n".join(f"- {c}" for c in claims) if claims else "Stick strictly to the script summary."
        evidence_type = script_data.get("evidence_type", "documented_fact")
        tag_str = " ".join(hashtags or ["#CurioLoop", "#Shorts"])
        prompt = f"""
Create a concise, engaging YouTube Shorts description (250-650 chars).

Topic: {topic}
Category: {category}
Evidence classification: {evidence_type}
Title: {title}
Key Points:
{claims_str}

STRICT RULES:
1. Hook: 1 crisp sentence sparking curiosity without "Did you know?".
2. Summary: 2 engaging sentences summarizing the story honestly (never assert unverified mysteries as settled fact).
3. Engagement: 1 thoughtful question inviting comments.
4. End cleanly with "{self.brand_sign_off}" and these concise hashtags: {tag_str}.
5. ABSOLUTELY NO URLs, NO links, NO reddit/social handles anywhere in the text.

Return JSON:
{{
  "hook": "...",
  "body": "...",
  "engagement_question": "...",
  "hashtags": ["#CurioLoop", ...],
  "full_description": "..."
}}
"""
        res = gemini_client.generate_json(prompt)
        if res and isinstance(res, dict) and res.get("full_description"):
            cleaned_desc = strip_external_links(str(res["full_description"]))
            res["full_description"] = cleaned_desc
            res["char_count"] = len(cleaned_desc)
            res["validated"] = True
            return res
        return None


description_generator = DescriptionGenerator()
