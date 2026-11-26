"""Script writer and pure-media documentary + illustrated host choreography director."""
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
    CharacterSpec,
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

CHARACTER_POSES = ("explaining", "pointing", "shocked", "thinking", "shrug")
CAMERA_SHOTS = ("wide", "medium", "closeup", "pan_left", "pan_right", "zoom_in", "zoom_out")
HOST_APPEARANCES = ("none", "cameo", "presenter")


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
    speaker_names: Dict[str, str] = {}

    for raw in raw_lines:
        speaker = "narrator"
        speaker_name = "Atlas"
        text = raw
        m = re.match(r"^\[?([A-Za-z][A-Za-z0-9 _-]{0,20})\]?\s*:\s*(.+)$", raw)
        if m:
            raw_label = m.group(1).strip()
            label = raw_label.lower()
            text = m.group(2).strip()
            if label not in speaker_map:
                speaker_map[label] = "primary" if len(speaker_map) == 0 else "secondary"
                speaker_names[label] = raw_label.title()
            speaker = speaker_map[label]
            speaker_name = speaker_names[label]

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        for sent in sentences:
            words = sent.split()
            if len(words) > 20:
                step = 16
                for i in range(0, len(words), step):
                    part = " ".join(words[i:i + step]).strip()
                    if i + step < len(words):
                        part = part.rstrip(",;")
                    if part:
                        beats.append({"speaker": speaker, "speaker_name": speaker_name, "text": part})
            else:
                beats.append({"speaker": speaker, "speaker_name": speaker_name, "text": sent})

    return beats


def _extract_stat_callout(sentence: str) -> str:
    m = re.search(r"\b(\d{4}|\d+(?:\.\d+)?%|\$[\d,.]+[MBK]?|\d+(?:,\d{3})+)\b", sentence)
    return m.group(1) if m else ""


def _infer_pose(text: str, beat_idx: int) -> str:
    lower = text.lower()
    if any(k in lower for k in ("shock", "impossible", "vanish", "died", "dead", "panic", "scream", "explosion", "never", "kill")):
        return "shocked"
    if any(k in lower for k in ("why", "mystery", "unknown", "puzzle", "question", "how", "wonder", "secret")):
        return "thinking"
    if any(k in lower for k in ("actually", "turns out", "strange", "weird", "bizarre", "nobody", "literally")):
        return "shrug"
    if any(k in lower for k in ("warn", "danger", "deadly", "percent", "million", "thousand", "meters", "1")):
        return "pointing"
    return CHARACTER_POSES[beat_idx % len(CHARACTER_POSES)]


_BROLL_STOPWORDS = {
    "what", "seemed", "like", "there", "when", "where", "which", "while", "these", "those",
    "this", "that", "they", "their", "them", "with", "from", "into", "about", "nearly",
    "could", "would", "should", "years", "year", "only", "most", "some", "many", "very",
    "scientists", "researchers", "experts", "estimate", "people", "today", "actually",
    "twelve", "hundred", "thousand", "million", "billion", "official", "officially",
}


def _infer_beat_cues(
    sentence: str,
    topic: str,
    category: str,
    beat_idx: int,
    *,
    speaker: str = "narrator",
    speaker_name: str = "Atlas",
) -> Dict[str, Any]:
    """Deterministic pure-media documentary visual cues when LLM is offline or for custom scripts."""
    clean = re.sub(r"[^A-Za-z0-9\s,'-]", " ", sentence).strip()
    stat = _extract_stat_callout(sentence)
    pose = _infer_pose(clean, beat_idx)

    if beat_idx == 0:
        pref = MediaPreference.AI_IMAGE
        host_app = "presenter"
    elif beat_idx % 3 == 1:
        pref = MediaPreference.BROLL_VIDEO
        host_app = "cameo" if beat_idx % 2 == 1 else "none"
    elif beat_idx % 3 == 2:
        pref = MediaPreference.AI_IMAGE
        host_app = "none" if beat_idx % 2 == 0 else "cameo"
    else:
        pref = MediaPreference.ARCHIVAL
        host_app = "cameo"

    shots = ("zoom_in", "pan_right", "zoom_out", "pan_left", "closeup")
    topic_words = [w for w in re.findall(r"[A-Za-z]{4,}", topic) if w.lower() not in _BROLL_STOPWORDS][:2]
    beat_words = [
        w for w in re.findall(r"[A-Za-z]{4,}", clean)
        if w.lower() not in _BROLL_STOPWORDS and w.lower() not in {t.lower() for t in topic_words}
    ][:3]
    unique_query = " ".join(topic_words + beat_words)
    broll_query = " ".join(beat_words[:3] or topic_words[:2] or [category])

    return {
        "visual_prompt": (
            f"Cinematic documentary visual illustration: {clean}. Story context: {topic}. "
            "Dramatic lighting, detailed foreground subject, atmospheric depth, no text, no watermarks."
        ),
        "broll_query": broll_query,
        "archival_query": unique_query,
        "media_preference": pref.value,
        "characters": [{"name": speaker_name or "Atlas", "role": "narrator", "pose": pose, "facing": "right"}],
        "camera_shot": shots[beat_idx % len(shots)],
        "host_appearance": host_app,
        "callout_stat": stat,
        "callout_title": " ".join(clean.split()[:3]).upper() if stat else "",
    }


class StoryDirector:
    """Builds StoryPlans for pure-media documentary + illustrated Signature Host videos."""

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
            "You are a cinematic YouTube documentary director. Every single beat is backed by real visual media: "
            "either dramatic AI editorial illustrations ('ai_image'), real 1080p stock video B-roll ('broll_video'), "
            "or real historical/science archival photos ('archival')—never plain text cards or code boxes. "
            "An illustrated documentary host appears periodically ('presenter' on hook/reveal, 'cameo' reacting on select beats, 'none' for pure cinema). "
            "Write gripping, accurate 45-65s scripts split into 10 to 13 beats (3-5s each). Beat 0 must be a strong hook (never 'Did you know'). "
            "Respond strictly in valid JSON."
        )
        avoid_str = "; ".join(avoid_titles[:15]) if avoid_titles else "none"
        user_prompt = (
            f"Topic: {topic}\n"
            f"Category: {category}\n"
            f"Background facts: {facts or 'Use verifiable real-world details.'}\n"
            f"Avoid repeating these past topics: {avoid_str}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "title": "high-CTR curiosity title under 70 chars",\n'
            '  "hook": "first spoken line under 13 words",\n'
            '  "description": "engaging 2-3 sentence summary",\n'
            '  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6"],\n'
            '  "beats": [\n'
            "    {\n"
            '      "text": "1 punchy spoken sentence (9-17 words)",\n'
            '      "media_preference": "ai_image | broll_video | archival",\n'
            '      "visual_prompt": "vivid 1-sentence scene or visual metaphor illustrating this exact line (no text in image)",\n'
            '      "broll_query": "2-3 concrete filmable nouns for stock video (e.g. ocean storm waves)",\n'
            '      "archival_query": "unique 3-4 word real photo query or empty",\n'
            '      "host_appearance": "presenter | cameo | none",\n'
            '      "pose": "explaining | pointing | shocked | thinking | shrug",\n'
            '      "camera_shot": "zoom_in | zoom_out | pan_left | pan_right | closeup",\n'
            '      "callout_stat": "short crisp number/year ONLY when a dramatic stat helps (e.g. 1859 or 17.6 HRS) else empty",\n'
            '      "callout_title": "2-3 word label ONLY if callout_stat is set else empty"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Total spoken words: 120 to 165 words.\n"
            "- Mix media_preference across beats: ~6 ai_image (including visual metaphors for scientific/historical events), ~4 broll_video, ~2 archival.\n"
            "- Use host_appearance='presenter' on Beat 0 and 1 twist/ending beat; 'cameo' on ~3-4 beats; 'none' on ~5-6 full-screen cinematic beats.\n"
        )

        data = self.llm.generate_json(system_prompt, user_prompt, temperature=0.65)
        if data and isinstance(data.get("beats"), list) and len(data["beats"]) >= 5:
            beats = self._parse_beats(data["beats"], topic, category)
            if beats:
                return StoryPlan(
                    title=str(data.get("title") or topic)[:85],
                    hook=str(data.get("hook") or beats[0].text),
                    category=category,
                    style=style,
                    beats=beats,
                    description=str(data.get("description") or f"{topic} — documentary breakdown."),
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
        cue_by_idx: Dict[int, Dict[str, Any]] = {}
        first_llm_meta: Dict[str, Any] = {}
        batch_size = 16

        for start_i in range(0, len(raw_beats), batch_size):
            batch = raw_beats[start_i:start_i + batch_size]
            indexed_lines = "\n".join(f"{start_i + offset}: {b['text']}" for offset, b in enumerate(batch))
            system_prompt = (
                "You are a documentary visual director. For EVERY numbered line, return a concrete visual_prompt "
                "(no text in image), 2-3 word broll_query, media_preference ('ai_image'|'broll_video'|'archival'), "
                "host_appearance ('presenter'|'cameo'|'none'), pose, and optional crisp callout_stat. "
                "Do NOT rewrite spoken lines. Respond in valid JSON."
            )
            user_prompt = (
                f"Title: {inferred_title}\n"
                f"Lines:\n{indexed_lines}\n\n"
                'Return JSON: {"title": "...", "description": "...", "tags": [...], '
                '"visuals": [{"index": 0, "media_preference": "ai_image|broll_video|archival", '
                '"visual_prompt": "...", "broll_query": "...", "archival_query": "...", '
                '"host_appearance": "presenter|cameo|none", "pose": "explaining|pointing|shocked|thinking|shrug", '
                '"callout_stat": "...", "callout_title": "..."}]}'
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
            fallback_cue = _infer_beat_cues(
                rb["text"],
                inferred_title,
                category,
                idx,
                speaker=rb["speaker"],
                speaker_name=rb.get("speaker_name", "Atlas"),
            )
            cue = dict(fallback_cue)
            llm_cue = cue_by_idx.get(idx)
            if llm_cue:
                for k, v in llm_cue.items():
                    if v not in (None, "", []):
                        cue[k] = v
            beats.append(self._make_beat(idx, rb["speaker"], rb["text"], cue, inferred_title, category))

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
            self._make_beat(i, "narrator", sent, _infer_beat_cues(sent, topic, category, i), topic, category)
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

    def _parse_beats(self, raw_beats: List[Any], topic: str, category: str) -> List[BeatSpec]:
        parsed: List[BeatSpec] = []
        for idx, item in enumerate(raw_beats):
            if not isinstance(item, dict):
                continue
            txt = str(item.get("text", "")).strip()
            if not txt:
                continue
            parsed.append(self._make_beat(idx, "narrator", txt, item, topic, category))
        return parsed

    @staticmethod
    def _make_beat(
        idx: int,
        speaker: str,
        text: str,
        cue: Dict[str, Any],
        topic: str,
        category: str = "story",
    ) -> BeatSpec:
        defaults = _infer_beat_cues(text, topic, category, idx, speaker=speaker)

        pref_raw = str(cue.get("media_preference", defaults["media_preference"])).strip().lower()
        try:
            pref = MediaPreference(pref_raw)
        except ValueError:
            pref = MediaPreference.AI_IMAGE

        shot = str(cue.get("camera_shot") or defaults["camera_shot"]).strip().lower()
        if shot not in CAMERA_SHOTS:
            shot = defaults["camera_shot"]

        host_app = str(cue.get("host_appearance") or defaults["host_appearance"]).strip().lower()
        if host_app not in HOST_APPEARANCES:
            host_app = defaults["host_appearance"]

        pose = str(cue.get("pose") or defaults["characters"][0]["pose"]).strip().lower()
        if pose not in CHARACTER_POSES:
            pose = defaults["characters"][0]["pose"]

        characters = [CharacterSpec(name="Atlas", role="narrator", pose=pose, facing="right")]
        vprompt = str(cue.get("visual_prompt") or defaults["visual_prompt"]).strip()
        broll_query = str(cue.get("broll_query") or defaults["broll_query"]).strip()

        return BeatSpec(
            index=idx,
            speaker=speaker,
            text=text,
            visual_prompt=vprompt,
            broll_query=broll_query,
            archival_query=str(cue.get("archival_query") or "").strip(),
            media_preference=pref,
            motion=_MOTIONS[idx % len(_MOTIONS)],
            characters=characters,
            camera_shot=shot,
            host_appearance=host_app,
            callout_title=str(cue.get("callout_title") or "").strip()[:48],
            callout_stat=str(cue.get("callout_stat") or "").strip()[:20],
        )
