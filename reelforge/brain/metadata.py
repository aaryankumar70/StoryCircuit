"""SEO-rich YouTube titles, descriptions, chapters, and compliant tags for Shorts & Long videos."""
from __future__ import annotations

import re
from typing import Iterable, List

from reelforge.models import StoryPlan, VideoFormat
from reelforge.storage.dedup import content_tokens

_CATEGORY_TAGS = {
    "history": ["history", "historical facts", "untold history", "true story", "documentary"],
    "mystery": ["mystery", "unexplained", "unsolved mystery", "strange history", "true mystery"],
    "space": ["space", "astronomy", "nasa", "cosmos", "space documentary"],
    "science": ["science", "science facts", "discovery", "engineering", "curiosity"],
    "story": ["storytelling", "true story", "mini documentary", "facts", "interesting stories"],
    "nature": ["nature", "earth", "wildlife", "natural wonders", "science"],
    "tech": ["technology", "engineering", "innovation", "computing history", "science"],
}

_CATEGORY_HASHTAGS = {
    "history": "#History #UntoldHistory #Documentary",
    "mystery": "#Mystery #Unsolved #TrueStory",
    "space": "#Space #Astronomy #Cosmos",
    "science": "#Science #Facts #Discovery",
    "nature": "#Nature #Science #Earth",
    "tech": "#Technology #Engineering #History",
    "story": "#Storytime #TrueStory #Documentary",
}


def _fmt_chapter_ts(sec: float) -> str:
    total = max(0, int(sec))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def clean_youtube_title(raw_title: str, *, is_long: bool) -> str:
    """Clean forbidden characters and enforce YouTube title bounds."""
    clean = re.sub(r"[<>]+", "", re.sub(r"https?://\S+", "", raw_title or "")).strip()
    clean = re.sub(r"\s*#[A-Za-z0-9_]+\b", "", clean).strip(" -|:")
    if not clean:
        clean = "The Untold Story"
    if is_long:
        return clean[:98].rstrip()
    return f"{clean[:86].rstrip()} #Shorts"


def fit_tags_within_budget(candidates: Iterable[str], max_chars: int = 470, max_count: int = 15) -> List[str]:
    """Normalize tags, deduplicate case-insensitively, and stay safely under YouTube's 500-char limit."""
    out: List[str] = []
    seen = set()
    used_chars = 0

    for raw in candidates:
        tag = re.sub(r"[<>#\"']+", "", str(raw or "")).strip()
        tag = re.sub(r"\s+", " ", tag)
        if not tag or len(tag) < 2 or len(tag) > 40:
            continue
        key = tag.lower()
        if key in seen:
            continue
        # YouTube counts multi-word tags as quoted in its internal 500-char budget
        cost = len(tag) + (2 if " " in tag else 0) + (1 if out else 0)
        if used_chars + cost > max_chars:
            continue
        seen.add(key)
        out.append(tag)
        used_chars += cost
        if len(out) >= max_count:
            break
    return out


def build_youtube_tags(
    *,
    title: str,
    category: str,
    script: str,
    extra_tags: Iterable[str] = (),
    is_long: bool = False,
) -> List[str]:
    """Assemble 10-15 high-relevance discovery tags from topic, script keywords, and niche."""
    cat_key = (category or "story").strip().lower()
    cat_defaults = _CATEGORY_TAGS.get(cat_key, _CATEGORY_TAGS["story"])

    tokens = content_tokens(f"{title} {script}")
    freq: dict[str, int] = {}
    for tok in tokens:
        if len(tok) >= 4 and not tok.isdigit():
            freq[tok] = freq.get(tok, 0) + 1
    top_keywords = [k for k, _ in sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))[:6]]

    clean_title = re.sub(r"\s*#[A-Za-z0-9_]+\b", "", title or "").strip()
    format_tags = (
        ["deep dive", "full documentary", "video essay"]
        if is_long
        else ["shorts", "youtube shorts", "did you know"]
    )
    candidates: List[str] = [
        clean_title[:38],
        *list(extra_tags),
        *cat_defaults,
        *top_keywords,
        *format_tags,
        "StoryCircuit",
    ]
    return fit_tags_within_budget(candidates, max_chars=470, max_count=15)


def build_youtube_description(plan: StoryPlan, *, is_long: bool = False) -> str:
    """Create a rich, engagement-ready YouTube description with chapters on long videos."""
    base_desc = re.sub(r"[<>]+", "", re.sub(r"https?://\S+", "", plan.description or "")).strip()
    hook = plan.hook.strip() if plan.hook else (plan.beats[0].text.strip() if plan.beats else plan.title)

    lines: List[str] = []
    if base_desc and base_desc.lower() not in hook.lower():
        lines.append(base_desc)
    else:
        lines.append(hook)

    if len(plan.beats) >= 2 and hook not in lines[0]:
        lines.append("")
        lines.append(hook)

    if is_long and len(plan.beats) >= 4:
        lines.append("")
        lines.append("Chapters:")
        # Emit well-spaced chapters (>= 15s apart, starting at 00:00)
        last_ts = -999.0
        for idx, b in enumerate(plan.beats):
            if idx == 0 or (b.start_sec - last_ts >= 18.0):
                label = " ".join(b.text.split()[:7]).rstrip(".,!?;:")
                ts = 0.0 if idx == 0 else b.start_sec
                lines.append(f"{_fmt_chapter_ts(ts)} - {label}")
                last_ts = ts
    elif len(plan.beats) >= 3:
        highlights = [
            " ".join(b.text.split()[:12]).rstrip(".,;:")
            for b in (plan.beats[0], plan.beats[len(plan.beats) // 2], plan.beats[-1])
        ]
        lines.append("")
        lines.append("Inside this story:")
        for h in highlights:
            lines.append(f"• {h}")

    lines.append("")
    lines.append("What stood out most to you in this story? Drop your thoughts in the comments and subscribe for new episodes.")

    cat_hashtags = _CATEGORY_HASHTAGS.get(plan.category.lower(), _CATEGORY_HASHTAGS["story"])
    if is_long:
        lines.append("")
        lines.append(f"{cat_hashtags} #StoryCircuit")
    else:
        lines.append("")
        lines.append(f"{cat_hashtags} #Shorts")

    return "\n".join(lines)[:4900].strip()


def enrich_story_metadata(plan: StoryPlan, *, is_long: bool | None = None) -> StoryPlan:
    """Populate clean SEO title, rich description, and compliant tags on a StoryPlan."""
    long_mode = (plan.video_format == VideoFormat.LONG) if is_long is None else is_long
    plan.description = build_youtube_description(plan, is_long=long_mode)
    plan.tags = build_youtube_tags(
        title=plan.title,
        category=plan.category,
        script=plan.full_script,
        extra_tags=plan.tags,
        is_long=long_mode,
    )
    return plan
