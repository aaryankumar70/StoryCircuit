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
   - Generates Three.js narrative visual engine storyboards (compatible with templates/narrative-engine/).
   - Provides granular single-episode editing with cascading invalidation (STALE_INVALIDATED).
   - Storyboard approval gate (is_approved flag).
"""
from __future__ import annotations

import logging
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
            plan_title="Bite-Sized Viral Shorts (~60s)",
            format_preset="1m",
            target_duration_sec=60.0,
            episode_count=len(plan_1m_episodes),
            total_runtime_sec=round(plan_1m_runtime, 1),
            avg_episode_duration_sec=round(plan_1m_runtime / max(1, len(plan_1m_episodes)), 1),
            trade_off_analysis=TradeOffAnalysis(
                pacing="High-velocity, dopamine-optimized pacing tailored for vertical mobile feeds (Shorts/Reels).",
                retention_pros=[
                    "Highest completion rate (>80%) on vertical mobile algorithms.",
                    "Punchy cliffhangers at 50-60s maximize Part 2/3 binge-viewing.",
                    "Quick algorithmic testing and maximum publishing frequency.",
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
                    "Higher overall watch-time per viewer for storytelling-focused YouTube channels.",
                ],
                retention_cons=[
                    "Requires strong mid-video retention hook around 45s to prevent drop-off before climax.",
                    "Slightly lower initial swipe-through tolerance than 60s shorts.",
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
                    "Higher monetization value and long-form algorithmic credit.",
                    "Deepest audience satisfaction and emotional payoff.",
                ],
                retention_cons=[
                    "Demands relentless visual diversity and dynamic camera movement to sustain mobile attention beyond 2 minutes.",
                    "Produces fewer individual published assets from a single narrative script.",
                ],
                audience_fit="Cinephiles, documentary lovers, and audiences looking for complete self-contained stories.",
            ),
            episodes=plan_3m_episodes,
        )

        plans = [plan_1m, plan_15m, plan_3m]

        # Optional Custom Plan if custom_seconds requested
        if custom_seconds and abs(custom_seconds - 60.0) > 5 and abs(custom_seconds - 90.0) > 5 and abs(custom_seconds - 180.0) > 5:
            custom_episodes = self.segment_narrative_organically(
                sentences=sentences,
                target_duration_sec=custom_seconds,
                raw_text=raw_text,
                series_title=story_title,
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
        """Generates a rich, grounded Three.js narrative visual storyboard compatible with
        templates/narrative-engine/ (Three.js 3D WebGL environments and cinematic cameras).
        """
        sentences = split_into_sentences(narration)
        if not sentences:
            sentences = [narration.strip()]

        dur_s = total_duration_sec or estimate_duration_seconds(narration)
        num_scenes = max(3, min(6, len(sentences)))
        time_per_scene = dur_s / num_scenes

        # Distribute sentences across scenes
        scene_sentences_map: List[List[str]] = [[] for _ in range(num_scenes)]
        for idx, sentence in enumerate(sentences):
            target_scene = min(idx * num_scenes // len(sentences), num_scenes - 1)
            scene_sentences_map[target_scene].append(sentence)

        for s_idx in range(num_scenes):
            if not scene_sentences_map[s_idx]:
                scene_sentences_map[s_idx].append(sentences[min(s_idx, len(sentences) - 1)])

        # Three.js 3D narrative environments available in templates/narrative-engine/src/three_scenes.js
        three_environments = [
            ("ocean_scene", "Atlantic Swell & Brigantine Hull", "Three-Quarter Perspective Broadside View", "REVEAL"),
            ("helm_scene", "Quarterdeck Abandoned Helm", "Three-Quarter Dolly-In onto Abandoned Ship's Wheel", "TENSION"),
            ("cabin_scene", "Captain's Writing Desk & Logbook", "Macro Close-Up slowly pushing down toward Logbook", "MYSTERY"),
            ("ocean_scene", "Swells Battering Wooden Hull", "Dynamic Low-Angle Prow View with sea spray", "DREAD"),
            ("cabin_scene", "Flickering Brass Candlestick", "Slow push-in on Wax Seal & Cursive Script", "CLIMAX"),
            ("ocean_scene", "Open Ocean Horizon Isolation", "Isolation Dolly-Out into Deep Fog", "RESOLUTION"),
        ]

        shot_types = ["wide", "medium", "over_the_shoulder", "close_up", "macro", "silhouette"]

        scenes: List[Dict[str, Any]] = []
        for s_idx in range(num_scenes):
            sc_id = f"ep{episode_num:02d}_s{s_idx + 1:02d}"
            s_text = " ".join(scene_sentences_map[s_idx])
            start_t = round(s_idx * time_per_scene, 2)
            end_t = round((s_idx + 1) * time_per_scene, 2)
            sc_dur = round(end_t - start_t, 2)

            env_preset = three_environments[s_idx % len(three_environments)]
            three_scene_id, env_name, camera_desc, motivation = env_preset
            shot_type = shot_types[s_idx % len(shot_types)]
            cam_move = "slow_push_in" if s_idx % 2 == 0 else "dolly_in"

            # Determine tension level based on position in episode (rising tension arc)
            tension = min(10, 4 + int((s_idx / max(1, num_scenes - 1)) * 5))

            scene_obj = {
                "scene_id": sc_id,
                "beat_index": s_idx,
                "narration": {
                    "text": s_text,
                    "start_s": start_t,
                    "end_s": end_t,
                    "duration_sec": sc_dur,
                },
                "story_event": f"Beat {s_idx + 1}: {s_text[:75]}...",
                "visual_objective": f"Cinematic visualization of beat {s_idx + 1}: {camera_desc}.",
                "primary_subject": {
                    "name": "Narrator / Key Subject",
                    "action": "advancing narrative tension",
                    "character_id": f"char_subject_{s_idx + 1}",
                    "presence": "silhouette" if visual_profile == "psychological_horror" else "grounded",
                },
                "environment": {
                    "name": env_name,
                    "era": "Narrative Era",
                    "time_of_day": "Night / Dim Twilight",
                    "setting_id": f"env_{three_scene_id}",
                },
                "three_js_scene": three_scene_id,
                "rendering_method": "SELECTIVE_3D",
                "composition_type": shot_type.upper(),
                "camera": {
                    "shot_type": shot_type,
                    "movement": cam_move,
                    "motivation": motivation,
                    "description": camera_desc,
                },
                "lighting_and_atmosphere": {
                    "style": "low_key",
                    "contrast": "high",
                    "mood": "dread" if visual_profile == "psychological_horror" else "cinematic",
                    "key_source": "motivated practical / moonlight / lantern",
                },
                "tension_level": tension,
                "transition_out": {
                    "type": "hard_cut" if s_idx < num_scenes - 1 else "dip_to_black",
                    "duration_ms": 200 if s_idx < num_scenes - 1 else 500,
                },
                "continuity_requirements": [
                    "Preserve consistent color grading across Three.js 3D WebGL scenes.",
                    "Maintain continuous camera momentum and lighting motivation.",
                ],
            }
            scenes.append(scene_obj)

        storyboard = {
            "series_id": series_id,
            "episode_number": episode_num,
            "title": episode_title,
            "total_scenes": len(scenes),
            "total_duration_sec": dur_s,
            "visual_profile": visual_profile,
            "rendering_engine": "Three.js 3D Narrative Engine (templates/narrative-engine/)",
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
    ) -> Tuple[SeriesRecord, List[EpisodeRecord]]:
        """Generates full episode breakdowns, scripts, and Three.js visual scene storyboards
        for the selected production plan, persisting them to series_db.
        """
        sid = series_id or f"series_{int(datetime.now().timestamp())}"
        stitle = title or "Creator Series"

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
                visual_profile="psychological_horror",
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
            creator_info={"name": author, "source": source_url},
            content_type="creator_story",
            visual_profile="psychological_horror",
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
