"""Dynamic Production-Plan Recommendations and Three.js Visual Storyboard Engine.

Part of CurioLoop Creator Studio (Steps 3 & 4):
1. Dynamic Production-Plan Recommendations:
   - Generates multiple distinct production plans (1m, 1.5m, 3m, or custom seconds).
   - Segments story based on natural narrative stopping points (chapter transitions,
     temporal jumps, cliffhanger triggers, dialogue revelations).
   - NEVER forces arbitrary episode counts or mechanical splits (outputs 1 standalone,
     2, 4, 6, etc. episodes depending on the story's actual narrative structure).
   - Calculates plan title, target duration, actual episode count, runtime, trade-off analysis,
     and episode summaries with hooks and cliffhangers.
2. Episode Storyboard & Editing:
   - Generates Three.js narrative visual engine storyboards (compatible with templates/cartoon-3d/).
   - Provides granular single-episode editing with cascading invalidation (STALE_INVALIDATED).
   - Storyboard approval gate (is_approved flag).
"""
from __future__ import annotations

import logging
import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.creator_series.series_db import SeriesDatabase, series_db
from curiosity_engine.production.visual_director import assign_narrative_scenes
from curiosity_engine.production.visual_style_selector import select_visual_style

logger = logging.getLogger("curiosity_engine.production_planner")

WPM_STANDARD = 135.0  # Suspenseful, deliberate narrative pace (~2.25 words per second)
WPS_STANDARD = WPM_STANDARD / 60.0

TEMPORAL_MARKERS = [
    r"\byears?\s+later\b",
    r"\bdecades?\s+passed\b",
    r"\bmonths?\s+later\b",
    r"\bdays?\s+later\b",
    r"\bhours?\s+later\b",
    r"\bminutes?\s+later\b",
    r"\bthe\s+next\s+morning\b",
    r"\bthe\s+next\s+day\b",
    r"\bthe\s+following\s+day\b",
    r"\bat\s+midnight\b",
    r"\bthat\s+night\b",
    r"\bby\s+dawn\b",
    r"\bmeanwhile\b",
    r"\bafterwards?\b",
    r"\bin\s+the\s+end\b",
]

SUSPENSE_MARKERS = [
    r"\bthen\b",
    r"\bsuddenly\b",
    r"\bwhispered\b",
    r"\bscreamed\b",
    r"\brealized\b",
    r"\bsilence\b",
    r"\bshattered\b",
    r"\bcurse\b",
    r"\bcursed\b",
    r"\bdeath\b",
    r"\bdied\b",
    r"\bfrozen\b",
    r"\bblood\b",
    r"\bsecret\b",
    r"\bvanished\b",
    r"\bparalyzed\b",
    r"\bnever\s+heard\b",
    r"\bnever\s+spoke\b",
    r"\btoo\s+late\b",
    r"\bstared\b",
    r"\bdoor\s+opened\b",
    r"\bshadow\b",
    r"\bterrifying\b",
]


def split_into_sentences(text: str) -> List[str]:
    """Splits prose into distinct sentences preserving punctuation and dialogue."""
    cleaned = re.sub(r"\r\n|\r", "\n", text.strip())
    raw_sentences = re.split(r"(?<=[.!?…])\s+", cleaned.replace("\n", " "))
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    return sentences if sentences else [cleaned.strip()]


def estimate_duration_seconds(text: str, wpm: float = WPM_STANDARD) -> float:
    """Calculates speech duration in seconds at specified WPM."""
    words = len(text.split())
    if words == 0:
        return 0.0
    sentences = len(split_into_sentences(text))
    speech_time = (words / wpm) * 60.0
    pause_time = max(0.0, (sentences - 1) * 0.20)
    return round(speech_time + pause_time, 1)


@dataclass
class EpisodeSummary:
    episode_number: int
    title: str
    target_duration_sec: float
    estimated_duration_sec: float
    word_count: int
    hook: str
    cliffhanger: str
    summary: str
    raw_text: str
    beats: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeOffAnalysis:
    pacing: str
    retention_pros: List[str]
    retention_cons: List[str]
    audience_fit: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionPlan:
    plan_id: str
    plan_title: str
    format_preset: str
    target_duration_sec: float
    episode_count: int
    total_runtime_sec: float
    avg_episode_duration_sec: float
    trade_off_analysis: TradeOffAnalysis
    episodes: List[EpisodeSummary]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["formatted_total_runtime"] = (
            f"{int(self.total_runtime_sec // 60)}m {int(self.total_runtime_sec % 60):02d}s"
            if self.total_runtime_sec >= 60
            else f"{int(self.total_runtime_sec)}s"
        )
        return d


class ProductionPlanner:
    """Generates dynamic multi-plan production recommendations and Three.js storyboards."""

    def __init__(self, db_instance: Optional[SeriesDatabase] = None):
        self.series_db = db_instance or series_db

    # ──────────────────────────────────────────────────────────────────────────
    # Step 3: Dynamic Production-Plan Recommendations
    # ──────────────────────────────────────────────────────────────────────────

    def score_sentence_boundary(
        self,
        sentence_before: str,
        sentence_after: str,
        raw_text: str = "",
        analysis: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Evaluates whether a sentence boundary is a natural narrative stopping point."""
        score = 1.0

        # Paragraph break check
        if raw_text:
            pair_nl = f"{sentence_before}\n"
            if pair_nl in raw_text or f"{sentence_before}\r\n" in raw_text:
                score += 3.0

        # Temporal jump or major transition at start of next sentence
        for pat in TEMPORAL_MARKERS:
            if re.search(pat, sentence_after, re.IGNORECASE):
                score += 2.5
                break

        # Dramatic punch, reveal, or cliffhanger word at end of current sentence
        for pat in SUSPENSE_MARKERS:
            if re.search(pat, sentence_before, re.IGNORECASE):
                score += 2.0
                break

        # Intelligent analysis turning points & natural boundaries alignment
        if analysis:
            for b in analysis.get("natural_boundaries", []):
                snippet = b.get("trigger_sentence") or b.get("lead_in") or b.get("trigger_text") or ""
                if snippet and snippet.lower() in sentence_before.lower():
                    score += 3.0
                    break
            for tp in analysis.get("turning_points", []):
                tp_text = tp.get("event") or tp.get("text") or tp.get("description") or ""
                if tp_text and tp_text.lower() in sentence_before.lower():
                    score += 2.5
                    break

        # Punctuation emphasis
        if sentence_before.endswith("!") or sentence_before.endswith("?"):
            score += 1.5
        elif sentence_before.endswith("...") or sentence_before.endswith("…"):
            score += 1.8
        elif sentence_before.endswith('"') or sentence_before.endswith("'"):
            score += 1.0

        return score

    def segment_narrative_organically(
        self,
        sentences: List[str],
        target_duration_sec: float,
        raw_text: str = "",
        series_title: str = "Creator Series",
        analysis: Optional[Dict[str, Any]] = None,
    ) -> List[EpisodeSummary]:
        """Segments narrative into natural episodes based strictly on narrative stopping points.
        NEVER forces fixed episode counts or mechanical cuts mid-sentence or mid-idea.
        Can result in 1 standalone, 2, 3, 4, 6 episodes.
        """
        if not sentences:
            return []

        total_words = sum(len(s.split()) for s in sentences)
        target_words = max(20, int(target_duration_sec * WPS_STANDARD))

        # Standalone check: If total words fit comfortably in one episode (~125% of target),
        # keep as 1 standalone complete episode.
        if total_words <= int(target_words * 1.25):
            full_text = " ".join(sentences)
            est_dur = estimate_duration_seconds(full_text)
            hook = sentences[0] if sentences else ""
            cliff = sentences[-1] if sentences else ""
            beats = [s[:90] for s in sentences[:4]]
            return [
                EpisodeSummary(
                    episode_number=1,
                    title=f"{series_title} (Standalone Feature)",
                    target_duration_sec=target_duration_sec,
                    estimated_duration_sec=est_dur,
                    word_count=total_words,
                    hook=hook,
                    cliffhanger=cliff,
                    summary=f"Complete narrative unfolding in a single cinematic release ({len(sentences)} sentences).",
                    raw_text=full_text,
                    beats=beats,
                )
            ]

        # Multi-episode dynamic boundary search
        episodes: List[EpisodeSummary] = []
        cur_sentences: List[str] = []
        cur_words = 0
        ep_index = 1

        min_words = int(target_words * 0.70)
        max_words = int(target_words * 1.30)

        i = 0
        n = len(sentences)
        while i < n:
            sent = sentences[i]
            cur_sentences.append(sent)
            cur_words += len(sent.split())
            is_last_sentence = (i == n - 1)

            if not is_last_sentence and cur_words >= min_words:
                next_sent = sentences[i + 1]
                b_score = self.score_sentence_boundary(sent, next_sent, raw_text, analysis=analysis)

                # Lookahead: Check remaining words in story
                remaining_words_after_cut = sum(len(sentences[k].split()) for k in range(i + 1, n))

                # If remaining words are too few to form another episode (< 35% of target),
                # do not cut now; continue accumulating into this episode.
                should_not_orphan = (remaining_words_after_cut < int(target_words * 0.35))

                # Cut condition: Strong narrative stopping point (score >= 2.5) or reached max bound
                is_natural_stop = (b_score >= 2.5)
                reached_max = (cur_words >= max_words)

                if (is_natural_stop or reached_max) and not should_not_orphan:
                    ep_text = " ".join(cur_sentences)
                    dur = estimate_duration_seconds(ep_text)
                    hook = cur_sentences[0]
                    cliff = cur_sentences[-1]
                    beats = [s[:90] for s in cur_sentences[:4]]

                    episodes.append(
                        EpisodeSummary(
                            episode_number=ep_index,
                            title=f"{series_title} - Part {ep_index}",
                            target_duration_sec=target_duration_sec,
                            estimated_duration_sec=dur,
                            word_count=cur_words,
                            hook=hook,
                            cliffhanger=cliff,
                            summary=f"Part {ep_index} containing {len(cur_sentences)} sentences building towards dramatic beat: '{cliff[:60]}...'",
                            raw_text=ep_text,
                            beats=beats,
                        )
                    )
                    ep_index += 1
                    cur_sentences = []
                    cur_words = 0

            i += 1

        # Final episode for remaining sentences
        if cur_sentences:
            ep_text = " ".join(cur_sentences)
            dur = estimate_duration_seconds(ep_text)
            hook = cur_sentences[0]
            cliff = cur_sentences[-1]
            beats = [s[:90] for s in cur_sentences[:4]]
            title = (
                f"{series_title} - Part {ep_index} (Finale)"
                if ep_index > 1
                else f"{series_title} (Standalone Feature)"
            )
            episodes.append(
                EpisodeSummary(
                    episode_number=ep_index,
                    title=title,
                    target_duration_sec=target_duration_sec,
                    estimated_duration_sec=dur,
                    word_count=cur_words,
                    hook=hook,
                    cliffhanger=cliff,
                    summary=f"Final resolution concluding the story ({len(cur_sentences)} sentences).",
                    raw_text=ep_text,
                    beats=beats,
                )
            )

        return episodes

    def generate_production_plans(
        self,
        raw_text: str,
        title: Optional[str] = None,
        analysis: Optional[Dict[str, Any]] = None,
        custom_seconds: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Generates 2-3 distinct production plans comparing pacing, episode counts, and trade-offs."""
        story_title = title or (analysis.get("title") if analysis else None) or "Creator Series"
        sentences = split_into_sentences(raw_text)
        total_words = sum(len(s.split()) for s in sentences)

        # Plan 1: 1m (~60s) Viral Shorts Plan
        plan_1m_episodes = self.segment_narrative_organically(
            sentences=sentences,
            target_duration_sec=60.0,
            raw_text=raw_text,
            series_title=story_title,
            analysis=analysis,
        )
        plan_1m_runtime = sum(e.estimated_duration_sec for e in plan_1m_episodes)
        plan_1m = ProductionPlan(
            plan_id="plan_1m",
            plan_title="Bite-Sized Short-Form Story (~60s)",
            format_preset="1m",
            target_duration_sec=60.0,
            episode_count=len(plan_1m_episodes),
            total_runtime_sec=round(plan_1m_runtime, 1),
            avg_episode_duration_sec=round(plan_1m_runtime / max(1, len(plan_1m_episodes)), 1),
            trade_off_analysis=TradeOffAnalysis(
                pacing="High-velocity, dopamine-optimized pacing tailored for vertical mobile feeds (Shorts/Reels).",
                retention_pros=[
                    "Designed for a concise beginning-to-end viewing experience.",
                    "A natural story boundary near the end can support a clear continuation when one exists.",
                    "Supports frequent publishing when production and review capacity allow.",
                ],
                retention_cons=[
                    "Requires strict brevity; minimal room for ambient world-building.",
                    "Episodic churn risk if viewers don't click to the next part.",
                ],
                audience_fit="Broad vertical feed viewers, mystery/thriller fans who consume quick hook-driven stories.",
            ),
            episodes=plan_1m_episodes,
        )

        # Plan 2: 1.5m (~90s) Dramatic Narrative Mini-Series Plan
        plan_15m_episodes = self.segment_narrative_organically(
            sentences=sentences,
            target_duration_sec=90.0,
            raw_text=raw_text,
            series_title=story_title,
            analysis=analysis,
        )
        plan_15m_runtime = sum(e.estimated_duration_sec for e in plan_15m_episodes)
        plan_15m = ProductionPlan(
            plan_id="plan_1_5m",
            plan_title="Dramatic Narrative Mini-Series (~90s)",
            format_preset="1.5m",
            target_duration_sec=90.0,
            episode_count=len(plan_15m_episodes),
            total_runtime_sec=round(plan_15m_runtime, 1),
            avg_episode_duration_sec=round(plan_15m_runtime / max(1, len(plan_15m_episodes)), 1),
            trade_off_analysis=TradeOffAnalysis(
                pacing="Atmospheric, calibrated tension curve with breathing room for character dread and mystery layering.",
                retention_pros=[
                    "Deeper psychological immersion and character connection.",
                    "Accommodates subtle clue layering and richer Three.js 3D visual environments.",
                    "Offers more room for character development and layered clues.",
                ],
                retention_cons=[
                    "Benefits from a clear midpoint beat before the climax.",
                    "Asks viewers for a longer time commitment than the 60-second option.",
                ],
                audience_fit="True crime, psychological horror, and lore-focused audiences seeking cinematic depth.",
            ),
            episodes=plan_15m_episodes,
        )

        # Plan 3: 3m (~180s) Cinematic Featurette Plan
        plan_3m_episodes = self.segment_narrative_organically(
            sentences=sentences,
            target_duration_sec=180.0,
            raw_text=raw_text,
            series_title=story_title,
            analysis=analysis,
        )
        plan_3m_runtime = sum(e.estimated_duration_sec for e in plan_3m_episodes)
        plan_3m = ProductionPlan(
            plan_id="plan_3m",
            plan_title="Cinematic Featurette / Extended Story (~180s)",
            format_preset="3m",
            target_duration_sec=180.0,
            episode_count=len(plan_3m_episodes),
            total_runtime_sec=round(plan_3m_runtime, 1),
            avg_episode_duration_sec=round(plan_3m_runtime / max(1, len(plan_3m_episodes)), 1),
            trade_off_analysis=TradeOffAnalysis(
                pacing="Theatrical three-act narrative progression with complete exposition, rising dread, and definitive resolution.",
                retention_pros=[
                    "Zero episodic friction or cliffhanger churn—complete story experience in one view.",
                    "May suit creators seeking a complete-story viewing experience when platform duration rules allow.",
                    "Deepest audience satisfaction and emotional payoff.",
                ],
                retention_cons=[
                    "Needs sustained visual variety and clear story beats beyond two minutes.",
                    "Produces fewer individual published assets from a single narrative script.",
                ],
                audience_fit="Cinephiles, documentary lovers, and audiences looking for complete self-contained stories.",
            ),
            episodes=plan_3m_episodes,
        )

        plans = [plan_1m, plan_15m, plan_3m]

        # Include a server-planned custom option whenever the creator requests one.
        if custom_seconds is not None:
            custom_episodes = self.segment_narrative_organically(
                sentences=sentences,
                target_duration_sec=custom_seconds,
                raw_text=raw_text,
                series_title=story_title,
                analysis=analysis,
            )
            c_runtime = sum(e.estimated_duration_sec for e in custom_episodes)
            custom_plan = ProductionPlan(
                plan_id="plan_custom",
                plan_title=f"Custom Duration Plan ({custom_seconds:.0f}s)",
                format_preset="custom",
                target_duration_sec=custom_seconds,
                episode_count=len(custom_episodes),
                total_runtime_sec=round(c_runtime, 1),
                avg_episode_duration_sec=round(c_runtime / max(1, len(custom_episodes)), 1),
                trade_off_analysis=TradeOffAnalysis(
                    pacing=f"Tailored custom pacing targeting {custom_seconds:.0f} seconds per episode.",
                    retention_pros=[f"Exact alignment with creator's custom duration goal of {custom_seconds:.0f}s."],
                    retention_cons=["Requires custom monitoring of audience retention thresholds."],
                    audience_fit="Creator-specific custom content strategy.",
                ),
                episodes=custom_episodes,
            )
            plans.append(custom_plan)

        return [p.to_dict() for p in plans]

    # ──────────────────────────────────────────────────────────────────────────
    # Step 4: Three.js Narrative Visual Storyboard Engine
    # ──────────────────────────────────────────────────────────────────────────

    def generate_threejs_storyboard(
        self,
        series_id: str,
        episode_num: int,
        episode_title: str,
        narration: str,
        visual_profile: str = "psychological_horror",
        total_duration_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate story-specific storyboard shots for the Cartoon 3D renderer."""
        sentences = split_into_sentences(narration)
        if not sentences:
            sentences = [narration.strip()]
        if not narration.strip():
            raise ValueError("A Creator storyboard requires narration.")

        dur_s = float(total_duration_sec or estimate_duration_seconds(narration))
        num_scenes = max(1, min(6, len(sentences)))
        sentence_groups: List[List[str]] = [[] for _ in range(num_scenes)]
        for idx, sentence in enumerate(sentences):
            sentence_groups[min(idx * num_scenes // len(sentences), num_scenes - 1)].append(sentence)
        profile_key = visual_profile.casefold()
        category = (
            "History" if "histor" in profile_key
            else "Space" if "space" in profile_key
            else "Science" if "science" in profile_key
            else "Mysteries" if any(token in profile_key for token in ("mystery", "horror"))
            else "Fiction"
        )
        directed = assign_narrative_scenes({
            "title": episode_title,
            "topic": f"{episode_title} {visual_profile}",
            "category": category,
            "content_lane": "creator_series",
            "words_per_second": WPS_STANDARD,
            "lead": 0,
            "gap": 0,
            "lines": [{
                "text": " ".join(group),
                "scene": {"scene_id": f"ep{episode_num:02d}_s{index + 1:02d}"},
            } for index, group in enumerate(sentence_groups) if group],
        })

        scenes: List[Dict[str, Any]] = []
        profile = directed.get("visual_profile") or {}
        for s_idx, line in enumerate(directed["lines"]):
            shot = line["scene"]
            s_text = line["text"]
            start_t = float(shot["estimated_start_sec"])
            end_t = float(shot["estimated_end_sec"])
            characters = shot.get("characters") or []
            props = shot.get("props") or []
            subject_name = characters[0] if characters else (props[0] if props else shot["environment"])
            camera_desc = shot["camera"]
            lowered_camera = camera_desc.casefold()
            shot_type = (
                "close_up" if any(term in lowered_camera for term in ("close", "detail", "focus"))
                else "wide" if "wide" in lowered_camera
                else "low_angle" if "low" in lowered_camera
                else "tracking" if "tracking" in lowered_camera
                else "medium"
            )
            movement = (
                "rack_focus" if "rack focus" in lowered_camera
                else "tracking" if "tracking" in lowered_camera
                else "dolly_out" if "pullback" in lowered_camera
                else "dolly_in" if any(term in lowered_camera for term in ("push", "dolly"))
                else "hold"
            )
            env_digest = hashlib.sha256(shot["environment"].casefold().encode("utf-8")).hexdigest()[:10]
            subject_digest = hashlib.sha256(str(subject_name).casefold().encode("utf-8")).hexdigest()[:10]
            tension = min(10, 4 + int((s_idx / max(1, len(directed["lines"]) - 1)) * 5))
            scenes.append({
                "scene_id": str(shot["scene_id"]), "beat_index": s_idx,
                "narration": {"text": s_text, "start_s": round(start_t, 2), "end_s": round(end_t, 2),
                              "duration_sec": round(max(0.1, end_t - start_t), 2)},
                "story_event": s_text, "visual_objective": shot["visual_description"],
                "primary_subject": {"name": str(subject_name), "action": shot["animation"],
                                    "character_id": f"char_{subject_digest}" if characters else None,
                                    "presence": "grounded" if characters else "focal_object_or_environment"},
                "characters": characters,
                "environment": {"name": shot["environment"], "era": "story-specific",
                                "time_of_day": shot["lighting"], "setting_id": f"env_{env_digest}"},
                "important_objects": props,
                "three_js_scene": f"cartoon3d_{profile.get('environment', 'interior')}",
                "rendering_method": "CARTOON_3D_THREEJS",
                "composition_type": shot_type.upper(),
                "camera": {"shot_type": shot_type, "movement": movement,
                           "motivation": shot["visual_type"], "description": camera_desc},
                "lighting_and_atmosphere": {"style": shot["lighting"], "contrast": "cinematic",
                                             "mood": profile.get("profile", "fiction"), "key_source": shot["lighting"]},
                "animation": shot["animation"], "tension_level": tension,
                "transition_out": {"type": shot["transition"], "duration_ms": 300},
                "continuity_requirements": [shot["continuity"]],
                "visual_match_explanation": shot["visual_description"],
            })

        storyboard = {
            "series_id": series_id,
            "episode_number": episode_num,
            "title": episode_title,
            "total_scenes": len(scenes),
            "total_duration_sec": dur_s,
            "visual_profile": profile.get("profile", "fiction"),
            "rendering_engine": "CurioLoop Cartoon 3D renderer (Three.js/WebGL + Chromium/FFmpeg)",
            "approval_status": "PENDING_REVIEW",
            "is_approved": False,
            "approved_by": None,
            "approval_date": None,
            "scenes": scenes,
        }
        return storyboard

    # ──────────────────────────────────────────────────────────────────────────
    # Step 4: Breakdown Generation, Granular Edit & Approval Gate
    # ──────────────────────────────────────────────────────────────────────────

    def generate_episode_breakdown_and_storyboards(
        self,
        raw_text: str,
        series_id: Optional[str] = None,
        title: Optional[str] = None,
        selected_plan: Optional[Dict[str, Any]] = None,
        duration_preset: str = "1m",
        custom_seconds: Optional[float] = None,
        rights_status: str = "UNVERIFIED_EVALUATION_ONLY",
        author: Optional[str] = "Creator",
        source_url: Optional[str] = None,
        attribution: Optional[str] = None,
        analysis: Optional[Dict[str, Any]] = None,
    ) -> Tuple[SeriesRecord, List[EpisodeRecord]]:
        """Generates full episode breakdowns, scripts, and Three.js visual scene storyboards
        for the selected production plan, persisting them to series_db.
        """
        sid = series_id or f"series_{int(datetime.now().timestamp() * 1000)}"
        stitle = title or "Creator Series"
        category_hint = str((analysis or {}).get("genre") or (analysis or {}).get("category") or "")
        series_visual_profile = select_visual_style({
            "topic": stitle,
            "title": stitle,
            "category": category_hint,
            "content_lane": "creator_series",
            "lines": [{"text": raw_text}],
        })["profile"]

        # Determine episodes from selected_plan or generate plan dynamically
        plan_episodes_data = []
        target_sec = 60.0
        if selected_plan and "episodes" in selected_plan:
            plan_episodes_data = selected_plan["episodes"]
            target_sec = float(selected_plan.get("target_duration_sec", 60.0))
        else:
            preset_map = {"1m": 60.0, "1.5m": 90.0, "3m": 180.0}
            target_sec = preset_map.get(duration_preset, custom_seconds or 60.0)
            plans = self.generate_production_plans(
                raw_text=raw_text,
                title=stitle,
                custom_seconds=custom_seconds if duration_preset == "custom" else None,
            )
            # Find matching plan
            chosen = plans[0]
            for p in plans:
                if p["format_preset"] == duration_preset:
                    chosen = p
                    break
            plan_episodes_data = chosen["episodes"]

        ep_records: List[EpisodeRecord] = []
        ep_ids: List[str] = []

        for ep_data in plan_episodes_data:
            ep_num = int(ep_data.get("episode_number", len(ep_records) + 1))
            ep_id = f"{sid}_ep{ep_num:02d}"
            ep_title = ep_data.get("title", f"{stitle} - Part {ep_num}")
            narration = ep_data.get("raw_text") or ep_data.get("adapted_narration") or ""
            hook = ep_data.get("hook", "")
            cliff = ep_data.get("cliffhanger", "")
            est_dur = float(ep_data.get("estimated_duration_sec", target_sec))
            beats = ep_data.get("beats", [])

            # Generate Three.js Visual Scene Storyboard
            sb = self.generate_threejs_storyboard(
                series_id=sid,
                episode_num=ep_num,
                episode_title=ep_title,
                narration=narration,
                visual_profile=series_visual_profile,
                total_duration_sec=est_dur,
            )

            ep_rec = EpisodeRecord(
                episode_id=ep_id,
                series_id=sid,
                episode_num=ep_num,
                title=ep_title,
                adapted_narration=narration,
                source_segment={"text_excerpt": narration[:150]},
                hook=hook,
                beats=beats,
                cliffhanger=cliff,
                estimated_duration=est_dur,
                status=EpisodeStatus.ADAPTED,
                is_approved=False,
                version=1,
                storyboard=sb,
            )
            self.series_db.save_episode(ep_rec)
            ep_records.append(ep_rec)
            ep_ids.append(ep_id)

        # Rights enum resolution
        r_status = RightsStatus.UNVERIFIED_EVALUATION_ONLY
        if rights_status in ["VERIFIED", "LICENSED"]:
            r_status = RightsStatus.LICENSED
        elif rights_status == "PUBLIC_DOMAIN":
            r_status = RightsStatus.PUBLIC_DOMAIN
        elif rights_status == "OWNED":
            r_status = RightsStatus.OWNED

        series_rec = SeriesRecord(
            series_id=sid,
            title=stitle,
            full_script=raw_text,
            creator_info={"name": author, "source": source_url, "attribution": attribution or author},
            content_type="creator_story",
            visual_profile=series_visual_profile,
            rights_status=r_status,
            target_duration=target_sec,
            planned_episodes=len(ep_records),
            episode_ids=ep_ids,
            status=SeriesStatus.READY,
        )
        self.series_db.save_series(series_rec)
        logger.info(f"Generated breakdown for series '{sid}': {len(ep_records)} episodes with Three.js storyboards.")
        return series_rec, ep_records

    def edit_single_episode_with_invalidation(
        self,
        episode_id: str,
        title: Optional[str] = None,
        adapted_narration: Optional[str] = None,
        hook: Optional[str] = None,
        cliffhanger: Optional[str] = None,
        visual_notes: Optional[str] = None,
    ) -> EpisodeRecord:
        """Applies granular edits to a single episode and triggers cascading invalidation (STALE_INVALIDATED).
        Leaves all untouched episodes in the series completely unaffected!
        """
        ep = self.series_db.get_episode(episode_id)
        if not ep:
            raise KeyError(f"Episode '{episode_id}' not found.")

        # Update text/fields
        if title is not None:
            ep.title = title
        if hook is not None:
            ep.hook = hook
        if cliffhanger is not None:
            ep.cliffhanger = cliffhanger

        narration_changed = False
        if adapted_narration is not None and adapted_narration.strip() != ep.adapted_narration.strip():
            ep.adapted_narration = adapted_narration.strip()
            ep.estimated_duration = estimate_duration_seconds(ep.adapted_narration)
            narration_changed = True

        # Cascading invalidation: Mark modified episode as STALE_INVALIDATED
        ep.status = EpisodeStatus.STALE_INVALIDATED
        ep.is_approved = False  # Requires visual re-approval
        ep.approval_date = None
        ep.version = (ep.version or 1) + 1
        ep.audio_path = None
        ep.rendered_video_path = None
        ep.qc_result = None

        # Regenerate visual scene storyboard for this single episode
        new_sb = self.generate_threejs_storyboard(
            series_id=ep.series_id,
            episode_num=ep.episode_num,
            episode_title=ep.title,
            narration=ep.adapted_narration,
            visual_profile="psychological_horror",
            total_duration_sec=ep.estimated_duration,
        )
        if visual_notes:
            new_sb["creator_notes"] = visual_notes
        ep.storyboard = new_sb

        self.series_db.save_episode(ep)
        logger.info(
            f"Episode '{episode_id}' edited (version {ep.version}) and marked STALE_INVALIDATED. Untouched episodes preserved."
        )
        return ep

    def set_storyboard_approval(
        self,
        episode_id: str,
        approved: bool = True,
        reviewer: str = "Creator",
        notes: Optional[str] = None,
    ) -> EpisodeRecord:
        """Sets the visual storyboard approval status on a single episode."""
        ep = self.series_db.get_episode(episode_id)
        if not ep:
            raise KeyError(f"Episode '{episode_id}' not found.")

        ep.is_approved = approved
        now_iso = datetime.now(timezone.utc).isoformat()
        if approved:
            ep.approval_date = now_iso
            # If episode was in invalid or draft state, advance to READY for rendering
            if ep.status in (EpisodeStatus.STALE_INVALIDATED, EpisodeStatus.DRAFT, EpisodeStatus.ADAPTED):
                ep.status = EpisodeStatus.READY
            if ep.storyboard:
                ep.storyboard["approval_status"] = "APPROVED"
                ep.storyboard["is_approved"] = True
                ep.storyboard["approved_by"] = reviewer
                ep.storyboard["approval_date"] = now_iso
                if notes:
                    ep.storyboard["approval_notes"] = notes
        else:
            ep.approval_date = None
            ep.status = EpisodeStatus.DRAFT
            if ep.storyboard:
                ep.storyboard["approval_status"] = "REJECTED"
                ep.storyboard["is_approved"] = False

        self.series_db.save_episode(ep)
        logger.info(f"Episode '{episode_id}' visual approval status set to {approved} by {reviewer}.")
        return ep


# Global planner singleton instance
production_planner = ProductionPlanner()
