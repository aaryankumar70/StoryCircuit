"""Script writer and per-beat visual director for ReelForge (StoryCircuit)."""
from __future__ import annotations

import logging
import random
import re
from typing import Any, Dict, List, Optional

from reelforge.brain.llm_client import ZeroCostLLM
from reelforge.brain.metadata import enrich_story_metadata
from reelforge.brain.topic_pool import pick_fresh_topic
from reelforge.models import (
    BeatSpec,
    MediaPreference,
    MotionType,
    SourceMode,
    StoryPlan,
    VisualStyle,
)
from reelforge.storage.db import ReelDatabase

logger = logging.getLogger("reelforge.brain.director")

_MOTIONS = [
    MotionType.ZOOM_IN,
    MotionType.PAN_RIGHT,
    MotionType.ZOOM_OUT,
    MotionType.PAN_LEFT,
    MotionType.PULSE,
]

_STYLES = [
    VisualStyle.EDITORIAL_DARK,
    VisualStyle.VINTAGE_ARCHIVAL,
    VisualStyle.GRAPHIC_NOIR,
    VisualStyle.CINEMATIC_PAINTERLY,
    VisualStyle.BLUEPRINT_TECH,
]


def _pick_style(requested: str, db: Optional[ReelDatabase] = None) -> VisualStyle:
    if requested and requested != "auto":
        try:
            return VisualStyle(requested)
        except ValueError:
            pass
    recent_style = None
    if db is not None:
        jobs = db.list_jobs(limit=1)
        if jobs:
            recent_style = jobs[0].get("style")
    choices = [s for s in _STYLES if s.value != recent_style] or _STYLES
    return random.choice(choices)


def _split_custom_script_lines(script_text: str) -> List[Dict[str, str]]:
    """Split user script into spoken beats while preserving exact words and [Speaker]: tags."""
    raw_lines = [ln.strip() for ln in re.split(r"[\r\n]+", script_text.strip()) if ln.strip()]
    beats: List[Dict[str, str]] = []
    speaker_map: Dict[str, str] = {}

    for raw in raw_lines:
        speaker = "narrator"
        text = raw
        m = re.match(r"^\[?([A-Za-z][A-Za-z0-9 _-]{0,20})\]?\s*:\s*(.+)$", raw)
        if m:
            label = m.group(1).strip().lower()
            text = m.group(2).strip()
            if label not in speaker_map:
                speaker_map[label] = "primary" if len(speaker_map) == 0 else "secondary"
            speaker = speaker_map[label]

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        for sent in sentences:
            words = sent.split()
            if len(words) > 22:
                # Split long sentences cleanly into <= 20-word dynamic visual beats
                step = 18
                for i in range(0, len(words), step):
                    part = " ".join(words[i:i + step]).strip()
                    if i + step < len(words):
                        part = part.rstrip(",;")
                    if part:
                        beats.append({"speaker": speaker, "text": part})
            else:
                beats.append({"speaker": speaker, "text": sent})

    return beats


def _extract_stat_callout(sentence: str) -> str:
    """Pull a concise number/year/percentage badge if naturally present in the beat."""
    m = re.search(r"\b(\d{4}|\d+(?:\.\d+)?%|\$[\d,.]+[MBK]?|\d+(?:,\d{3})+)\b", sentence)
    return m.group(1) if m else ""


def _heuristic_visual_prompt(sentence: str, topic: str, beat_idx: int) -> Dict[str, Any]:
    """Deterministic scene-matched visual prompt when LLM is unavailable or times out."""
    clean = re.sub(r"[^A-Za-z0-9\s,'-]", " ", sentence).strip()
    stat = _extract_stat_callout(sentence)
    lower = clean.lower()

    if beat_idx == 0:
        pref = MediaPreference.AI_IMAGE
    elif stat and beat_idx % 3 == 1:
        pref = MediaPreference.GRAPHIC_CARD
    elif any(k in lower for k in ("18", "19", "ancient", "war", "apollo", "nasa", "ship", "expedition")):
        pref = MediaPreference.ARCHIVAL if beat_idx % 2 == 1 else MediaPreference.AI_IMAGE
    else:
        pref = MediaPreference.AI_IMAGE

    prompt = (
        f"Scene depicting: {clean}. Context: {topic}. "
        "Specific subject in sharp foreground focus, dramatic storytelling composition"
    )
    query_words = [w for w in re.findall(r"[A-Za-z0-9]{4,}", f"{topic} {clean}")][:5]
    return {
        "visual_prompt": prompt,
        "archival_query": " ".join(query_words),
        "media_preference": pref.value,
        "callout_stat": stat,
        "callout_title": " ".join(clean.split()[:5]).upper() if pref == MediaPreference.GRAPHIC_CARD else "",
    }


class StoryDirector:
    """Builds StoryPlans with dialogue-matched visual beats for all 3 workflow modes."""

    def __init__(self, llm: Optional[ZeroCostLLM] = None):
        self.llm = llm or ZeroCostLLM()

    def build_story(
        self,
        db: ReelDatabase,
        *,
        mode: SourceMode = SourceMode.RANDOM,
        topic: str = "",
        category: str = "auto",
        style: str = "auto",
        custom_script: str = "",
        facts: str = "",
    ) -> StoryPlan:
        chosen_style = _pick_style(style, db)

        if mode == SourceMode.CUSTOM_SCRIPT:
            if not custom_script.strip():
                raise ValueError("Custom script mode requires non-empty script text.")
            return self._build_from_custom_script(
                script_text=custom_script.strip(),
                title=topic.strip(),
                category=category if category != "auto" else "story",
                style=chosen_style,
            )

        recent_titles = [h["title"] for h in db.list_history(limit=35)]
        avoid_tried: List[str] = []

        if mode == SourceMode.RANDOM or not topic.strip():
            for attempt in range(3):
                candidate = pick_fresh_topic(db, category=category, llm=self.llm, avoid_extra=avoid_tried)
                cand_topic = candidate["topic"]
                cand_cat = candidate.get("category", "story")
                cand_facts = facts or candidate.get("facts", "")
                plan = self._generate_topic_storyboard(
                    topic=cand_topic,
                    category=cand_cat,
                    style=_pick_style(style, db) if attempt > 0 else chosen_style,
                    facts=cand_facts,
                    avoid_titles=recent_titles + avoid_tried,
                    source_mode=mode,
                )
                is_dup, reason = db.check_duplicate_topic(plan.title, plan.full_script)
                if not is_dup:
                    return enrich_story_metadata(plan)
                logger.warning("Generated topic collided with history (%s); retrying (%d/3).", reason, attempt + 1)
                avoid_tried.extend([cand_topic, plan.title])
            return enrich_story_metadata(plan)

        if category == "auto":
            category = "story"
        plan = self._generate_topic_storyboard(
            topic=topic,
            category=category,
            style=chosen_style,
            facts=facts,
            avoid_titles=recent_titles,
            source_mode=mode,
        )
        return enrich_story_metadata(plan)

    def _generate_topic_storyboard(
        self,
        *,
        topic: str,
        category: str,
        style: VisualStyle,
        facts: str,
        avoid_titles: List[str],
        source_mode: SourceMode,
    ) -> StoryPlan:
        system_prompt = (
            "You are a viral documentary YouTube Shorts director. "
            "Write gripping, accurate, non-generic 50-75 second scripts split into 9 to 12 beats. "
            "Each beat MUST have a concrete visual_prompt describing the exact physical scene, subject, "
            "and action matching that beat's spoken line (never abstract metaphors or repeated templates). "
            "Respond strictly in valid JSON."
        )
        avoid_str = "; ".join(avoid_titles[:15]) if avoid_titles else "none"
        user_prompt = (
            f"Topic: {topic}\n"
            f"Category: {category}\n"
            f"Background facts: {facts or 'Use verifiable real-world details.'}\n"
            f"Avoid repeating these past topics: {avoid_str}\n\n"
            "Return JSON with this exact schema:\n"
            "{\n"
            '  "title": "high-CTR curiosity title under 75 chars",\n'
            '  "hook": "first spoken line under 14 words",\n'
            '  "description": "engaging 2-3 sentence YouTube summary",\n'
            '  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6"],\n'
            '  "beats": [\n'
            "    {\n"
            '      "text": "1 punchy spoken sentence (10-20 words)",\n'
            '      "visual_prompt": "concrete scene matching exact spoken sentence",\n'
            '      "archival_query": "2-4 word search query for real historical/science photo or empty",\n'
            '      "media_preference": "ai_image | archival | graphic_card",\n'
            '      "callout_stat": "short stat/year like 1914 or empty",\n'
            '      "callout_title": "3-5 word card title if graphic_card else empty"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Never start with 'Did you know'.\n"
            "- Total spoken words across all beats: 125 to 180 words.\n"
            "- Use 'graphic_card' on 1 or 2 stat/twist beats, 'archival' on 1-2 real photo beats, and 'ai_image' on the rest.\n"
        )

        data = self.llm.generate_json(system_prompt, user_prompt, temperature=0.7)
        if data and isinstance(data.get("beats"), list) and len(data["beats"]) >= 5:
            beats = self._parse_beats(data["beats"], topic)
            if beats:
                return StoryPlan(
                    title=str(data.get("title") or topic)[:85],
                    hook=str(data.get("hook") or beats[0].text),
                    category=category,
                    style=style,
                    beats=beats,
                    description=str(data.get("description") or f"{topic} — short documentary breakdown."),
                    tags=[str(t) for t in (data.get("tags") or [category, "shorts", "story"])][:10],
                    source_mode=source_mode,
                    source_ref=topic,
                )

        return self._fallback_story_from_facts(topic, category, style, facts, source_mode)

    def _build_from_custom_script(
        self,
        *,
        script_text: str,
        title: str,
        category: str,
        style: VisualStyle,
    ) -> StoryPlan:
        raw_beats = _split_custom_script_lines(script_text)
        if not raw_beats:
            raise ValueError("Could not parse any spoken lines from custom script.")

        inferred_title = title or " ".join(raw_beats[0]["text"].split()[:7]).rstrip(".,!?")

        # Ask LLM in batches of 16 beats ONLY for visual cues while strictly locking spoken text
        cue_by_idx: Dict[int, Dict[str, Any]] = {}
        first_llm_meta: Dict[str, Any] = {}
        batch_size = 16
        for start_i in range(0, len(raw_beats), batch_size):
            batch = raw_beats[start_i:start_i + batch_size]
            indexed_lines = "\n".join(f"{start_i + offset}: {b['text']}" for offset, b in enumerate(batch))
            system_prompt = (
                "You are a visual storyboard director. Given numbered spoken lines, return a matching "
                "visual_prompt for EVERY index so the image matches what the speaker says word-for-word. "
                "Do NOT rewrite the spoken lines. Respond in valid JSON."
            )
            user_prompt = (
                f"Title: {inferred_title}\n"
                f"Lines:\n{indexed_lines}\n\n"
                'Return JSON: {"title": "...", "description": "...", "tags": [...], '
                '"visuals": [{"index": 0, "visual_prompt": "...", "archival_query": "...", '
                '"media_preference": "ai_image|archival|graphic_card", "callout_stat": "...", "callout_title": "..."}]}'
            )
            llm_data = self.llm.generate_json(system_prompt, user_prompt, temperature=0.45)
            if start_i == 0 and isinstance(llm_data, dict):
                first_llm_meta = llm_data
            if llm_data and isinstance(llm_data.get("visuals"), list):
                for item in llm_data["visuals"]:
                    if isinstance(item, dict) and "index" in item:
                        try:
                            cue_by_idx[int(item["index"])] = item
                        except (TypeError, ValueError):
                            pass

        beats: List[BeatSpec] = []
        for idx, rb in enumerate(raw_beats):
            cue = cue_by_idx.get(idx) or _heuristic_visual_prompt(rb["text"], inferred_title, idx)
            beats.append(self._make_beat(idx, rb["speaker"], rb["text"], cue, inferred_title))

        final_title = title or str(first_llm_meta.get("title") or inferred_title)[:85]
        plan = StoryPlan(
            title=final_title,
            hook=beats[0].text,
            category=category,
            style=style,
            beats=beats,
            description=str(first_llm_meta.get("description") or f"{final_title}"),
            tags=[str(t) for t in (first_llm_meta.get("tags") or [category, "story"])][:10],
            source_mode=SourceMode.CUSTOM_SCRIPT,
            source_ref="custom_script",
        )
        return enrich_story_metadata(plan)

    def _fallback_story_from_facts(
        self,
        topic: str,
        category: str,
        style: VisualStyle,
        facts: str,
        source_mode: SourceMode,
    ) -> StoryPlan:
        seed_text = facts.strip() if facts.strip() else (
            f"Most people overlook the strangest detail about {topic}. "
            f"At first glance, records made it seem like an ordinary event. "
            f"But closer investigation uncovered evidence nobody could easily explain. "
            f"Even experts looking at the original timeline noticed glaring contradictions. "
            f"Years later, that single turning point still changes how we view {topic}."
        )
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", seed_text) if len(s.strip().split()) >= 4]
        if len(sentences) < 4:
            sentences = [
                f"Here is the real story behind {topic}.",
                *sentences,
                f"That single detail still makes {topic} unforgettable today.",
            ]
        beats = [
            self._make_beat(i, "narrator", sent, _heuristic_visual_prompt(sent, topic, i), topic)
            for i, sent in enumerate(sentences[:12])
        ]
        plan = StoryPlan(
            title=topic[:85],
            hook=beats[0].text,
            category=category,
            style=style,
            beats=beats,
            description=f"The real story behind {topic}.",
            tags=[category, "history" if category == "history" else "story", "shorts"],
            source_mode=source_mode,
            source_ref=topic,
        )
        return enrich_story_metadata(plan)

    def _parse_beats(self, raw_beats: List[Any], topic: str) -> List[BeatSpec]:
        parsed: List[BeatSpec] = []
        for idx, item in enumerate(raw_beats):
            if not isinstance(item, dict):
                continue
            txt = str(item.get("text", "")).strip()
            if not txt:
                continue
            parsed.append(self._make_beat(idx, "narrator", txt, item, topic))
        return parsed

    @staticmethod
    def _make_beat(
        idx: int,
        speaker: str,
        text: str,
        cue: Dict[str, Any],
        topic: str,
    ) -> BeatSpec:
        pref_raw = str(cue.get("media_preference", "ai_image")).strip().lower()
        try:
            pref = MediaPreference(pref_raw)
        except ValueError:
            pref = MediaPreference.AI_IMAGE
        vprompt = str(cue.get("visual_prompt") or "").strip()
        if not vprompt:
            vprompt = f"Dramatic scene showing: {text}. Topic: {topic}."
        return BeatSpec(
            index=idx,
            speaker=speaker,
            text=text,
            visual_prompt=vprompt,
            archival_query=str(cue.get("archival_query") or "").strip(),
            media_preference=pref,
            motion=_MOTIONS[idx % len(_MOTIONS)],
            callout_title=str(cue.get("callout_title") or "").strip()[:60],
            callout_stat=str(cue.get("callout_stat") or "").strip()[:24],
        )
