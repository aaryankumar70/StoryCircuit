"""Authoritative Source-Event Ledger & Source-Fidelity Validator for CurioLoop Creator Series.

Ensures strict fidelity to the original source narrative:
1. Source-Event Ledger tracking all 17 mandatory narrative events across their assigned episodes.
2. Deterministic validation against invented plot twists, changed relationships,
   unsupported medical/supernatural explanations, altered endings, or broken chronology.
3. Independent source-fidelity scoring (0.0 - 10.0) separate from retention scores.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("curiosity_engine.source_fidelity")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Authoritative Source-Event Ledger (The 17 Mandatory Story Events)
# ─────────────────────────────────────────────────────────────────────────────

SOURCE_EVENT_LEDGER: List[Dict[str, Any]] = [
    {
        "event_id": "EVT_01_WALKMAN_HEADPHONES",
        "checklist_item": 1,
        "source_range": "Lines 1-14",
        "title": "Joshua Misses Story on Walkman",
        "description": "Joshua (12) wears headphones on a Walkman during field trip, tuning out the substitute driver who offers to tell the scariest story in the world.",
        "characters": ["Joshua", "Substitute Bus Driver"],
        "timeline_position": 1,
        "required_keywords": ["walkman", "headphones", "substitute"],
        "forbidden_keywords": ["radio", "ipod", "phone"],
        "episode_assignment": 1,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_02_BUS_SILENCE_REFUSAL",
        "checklist_item": 2,
        "source_range": "Lines 15-28",
        "title": "Unnatural Silence and Refusal",
        "description": "Tape ends; bus is completely silent; children sit slack-jawed and frozen; Isaiah gives monotone refusal; kids whisper 'Don't tell him.'",
        "characters": ["Joshua", "Isaiah", "Classmates", "Substitute Bus Driver"],
        "timeline_position": 2,
        "required_keywords": ["silent", "slack-jawed", "isaiah", "monotone"],
        "forbidden_keywords": ["laughing", "screaming"],
        "episode_assignment": 1,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_03_BUS_CRASH_DRIVER_DEATH",
        "checklist_item": 3,
        "source_range": "Lines 29-32",
        "title": "Head-on Collision & Driver Death",
        "description": "Horn blares as bus drifts into opposing traffic; oncoming truck collision kills the substitute driver, spins bus, knocks children out.",
        "characters": ["Joshua", "Substitute Bus Driver", "Truck Driver", "Classmates"],
        "timeline_position": 3,
        "required_keywords": ["truck", "opposing traffic", "killed"],
        "forbidden_keywords": ["cliff", "train", "bridge"],
        "episode_assignment": 2,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_04_SHINJI_COMA",
        "checklist_item": 4,
        "source_range": "Lines 29, 33",
        "title": "Shinji's Coma",
        "description": "One student on the bus, Shinji, falls into a severe coma from the crash impact.",
        "characters": ["Shinji", "Joshua"],
        "timeline_position": 4,
        "required_keywords": ["shinji", "coma"],
        "forbidden_keywords": ["killed instantly", "paralyzed"],
        "episode_assignment": 2,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_05_CHILDREN_REFUSAL",
        "checklist_item": 5,
        "source_range": "Lines 29, 37, 45",
        "title": "Wall of Silence and Fainting Rumor",
        "description": "Rumor spreads that students and driver fainted from the story causing the crash; surviving children refuse to discuss it with Joshua.",
        "characters": ["Joshua", "Classmates"],
        "timeline_position": 5,
        "required_keywords": ["rumor", "fainted"],
        "forbidden_keywords": ["told everyone", "investigation"],
        "episode_assignment": 2,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_06_MARIA_REFUSAL",
        "checklist_item": 6,
        "source_range": "Lines 33-45",
        "title": "Maria in Math Class",
        "description": "Joshua asks classmate Maria doodling in math class; she admits it was scary, packs her notebook, moves desks, and says loudly: 'I don't want to talk to you, Joshua.'",
        "characters": ["Joshua", "Maria"],
        "timeline_position": 6,
        "required_keywords": ["maria", "math", "doodling", "desk"],
        "forbidden_keywords": ["seizure", "catatonia", "hospital"],
        "episode_assignment": 2,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_07_ISAIAH_55_PROMISE",
        "checklist_item": 7,
        "source_range": "Lines 46-56",
        "title": "Isaiah's Age 55 Refusal",
        "description": "Joshua begs best friend Isaiah to summarize the story; Isaiah snaps: 'I'll tell you when I'm fifty-five... Bro, just let it go!' almost breaking their friendship.",
        "characters": ["Joshua", "Isaiah"],
        "timeline_position": 7,
        "required_keywords": ["fifty-five", "let it go"],
        "forbidden_keywords": ["deathbed pact", "blood oath", "contract"],
        "episode_assignment": 3,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_08_CALENDAR_REUNION",
        "checklist_item": 8,
        "source_range": "Lines 57-62",
        "title": "Age 55 Calendar Alert & Coffee Meetup",
        "description": "Decades pass; Joshua finds calendar alert: 'Isaiah's birthday—fifty-five.' Reaches out; they meet for coffee (first time since high school reunion).",
        "characters": ["Joshua", "Isaiah"],
        "timeline_position": 8,
        "required_keywords": ["calendar", "fifty-five", "coffee"],
        "forbidden_keywords": ["funeral", "hospital room", "bar meetup"],
        "episode_assignment": 4,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_09_ISAIAH_CANCER_REFUSAL",
        "checklist_item": 9,
        "source_range": "Lines 63-78",
        "title": "Isaiah's Pancreatic Cancer & Final Refusal",
        "description": "Isaiah has glassy and yellowed eyes, looking much older; reveals terminal pancreatic cancer with few months to live; cuts off Joshua and refuses to speak: 'Before you ask, I'm not gonna tell you that bus story... If you hear it, you'll wish you hadn't. Brother, let it go.'",
        "characters": ["Joshua", "Isaiah"],
        "timeline_position": 9,
        "required_keywords": ["pancreatic cancer", "yellow", "not going to tell you", "bus story"],
        "forbidden_keywords": ["told him the story", "leukemia", "heart attack"],
        "episode_assignment": 4,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_10_ISAIAH_DEATH",
        "checklist_item": 10,
        "source_range": "Lines 79-82",
        "title": "Isaiah's Death with Secret Intact",
        "description": "Sad goodbye; Joshua knows it is the last time; Isaiah passes away months later with secret kept; Joshua accepts mystery will go unsolved.",
        "characters": ["Joshua", "Isaiah"],
        "timeline_position": 10,
        "required_keywords": ["goodbye", "died", "grave"],
        "forbidden_keywords": ["revealed on deathbed", "left a letter", "audio tape"],
        "episode_assignment": 4,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_11_BAR_MARIA_OVERHEARING",
        "checklist_item": 11,
        "source_range": "Lines 83-96",
        "title": "Overhearing Maria at Local Bar",
        "description": "Until yesterday: at a local bar, Joshua overhears a middle-aged woman with brown curly hair at a nearby table recounting the bus field trip; recognizes her as Maria.",
        "characters": ["Joshua", "Maria", "Bar Patron"],
        "timeline_position": 11,
        "required_keywords": ["bar", "yesterday", "maria", "curly"],
        "forbidden_keywords": ["college dive bar", "seizures", "screaming at bar"],
        "episode_assignment": 5,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_12_DEVON_STABBING",
        "checklist_item": 12,
        "source_range": "Lines 97-100",
        "title": "Devon's Stepfather Stabbing",
        "description": "Maria recounts the driver's predictions coming true: Devon's stepfather stabbed him.",
        "characters": ["Maria", "Devon", "Stepfather"],
        "timeline_position": 12,
        "required_keywords": ["devon", "stepfather", "stabbed"],
        "forbidden_keywords": ["psychiatric breakdown", "insane asylum", "car accident"],
        "episode_assignment": 5,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_13_MITSUKO_WEDDING_DOWEL",
        "checklist_item": 13,
        "source_range": "Lines 99-100",
        "title": "Mitsuko's Wedding Cake Dowel Accident",
        "description": "Maria recounts: Mitsuko died at her wedding when the cake was smashed into her face, and one of the dowels went through her eye.",
        "characters": ["Maria", "Mitsuko"],
        "timeline_position": 13,
        "required_keywords": ["mitsuko", "wedding", "cake", "dowel", "eye"],
        "forbidden_keywords": ["poisoned", "jumped", "curse ritual"],
        "episode_assignment": 5,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_14_JOSHUA_3_DAY_PREDICTION",
        "checklist_item": 14,
        "source_range": "Lines 103-104",
        "title": "Driver Prophesied Joshua Dies Three Days After Hearing It",
        "description": "Maria reveals the driver's final prophecy for the one kid not listening: 'Joshua dies three days after he hears this story.'",
        "characters": ["Maria", "Joshua", "Substitute Bus Driver"],
        "timeline_position": 14,
        "required_keywords": ["joshua", "three days", "hears this story"],
        "forbidden_keywords": ["72-hour", "cardiac cessation", "cardiac arrest", "cognitohazard"],
        "episode_assignment": 6,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_15_BUS_ACCIDENT_PREDICTION_FULFILLED",
        "checklist_item": 15,
        "source_range": "Line 103",
        "title": "Bus Crash Predicted at the Beginning",
        "description": "The truck crash itself was the driver's first prophecy, fulfilled immediately after he spoke it.",
        "characters": ["Maria", "Substitute Bus Driver", "Shinji"],
        "timeline_position": 15,
        "required_keywords": ["predicted", "truck crash", "beginning"],
        "forbidden_keywords": ["unforeseen", "freak lightning"],
        "episode_assignment": 6,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_16_CHILDREN_PROTECTION_PACT",
        "checklist_item": 16,
        "source_range": "Line 104",
        "title": "Children Protected Joshua with Silence",
        "description": "The surviving children realized they could keep Joshua alive by never telling him what the driver said: 'We used to joke how if we never told him, maybe he'd never die—'",
        "characters": ["Maria", "Isaiah", "Joshua"],
        "timeline_position": 16,
        "required_keywords": ["joke", "never told him", "never die"],
        "forbidden_keywords": ["conspiracy to torment", "blood pact"],
        "episode_assignment": 6,
        "verbatim_meaning_required": True,
    },
    {
        "event_id": "EVT_17_FINAL_REALIZATION_ENDING",
        "checklist_item": 17,
        "source_range": "Lines 105-111",
        "title": "Final Realization & Exact Ending",
        "description": "Strangled sound escapes Joshua's throat; Maria looks up; Joshua flees; realization that Isaiah protected him for 43 years; exact ending preserved: 'Dammit, brother, you were right! I wish I'd never heard.'",
        "characters": ["Joshua", "Maria", "Isaiah"],
        "timeline_position": 17,
        "required_keywords": ["protecting my life", "dammit, brother, you were right", "wish i'd never heard"],
        "forbidden_keywords": ["died on the spot", "went insane"],
        "episode_assignment": 6,
        "verbatim_meaning_required": True,
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. Strict Hallucination & Deviation Blacklist
# ─────────────────────────────────────────────────────────────────────────────

FORBIDDEN_CONCEPTS = [
    # Invented medical / supernatural pseudoterms
    (r"\bcognitohazard\b", "Invented supernatural term 'cognitohazard' not in source."),
    (r"\b72-hour\b", "Invented terminology '72-hour' instead of original 'three days'."),
    (r"\bcardiac cessation\b", "Invented medical cause of death 'cardiac cessation'."),
    (r"\bcardiac arrest\b", "Invented medical term 'cardiac arrest' not in source."),
    # Invented character fates
    (r"\bpsychiatric breakdown\b", "Replaced Devon's stepfather stabbing him with 'psychiatric breakdown'."),
    (r"\bcatatoni[ac]\b", "Invented condition 'catatonia' for Maria/victims."),
    (r"\bseizures?\b", "Invented condition 'seizure' for Maria/victims."),
    (r"\bcollege (?:dive )?bar\b", "Changed local hometown bar to 'college dive bar'."),
    (r"\bdeathbed pact\b", "Distorted Isaiah's brush-off into an invented 'deathbed pact'."),
    (r"\bcurse explanation\b", "Invented general curse lore not in source."),
    (r"\bleaving her and isaiah\b", "Logical contradiction: Isaiah died of cancer, leaving Maria and Joshua as the last two."),
]


@dataclass
class SourceFidelityScore:
    fidelity_score: float  # 0.0 to 10.0
    passed: bool
    events_covered: int
    total_events: int
    missing_events: List[str] = field(default_factory=list)
    forbidden_violations: List[str] = field(default_factory=list)
    chronology_errors: List[str] = field(default_factory=list)
    ending_preserved: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SourceFidelityValidator:
    """Validates episode narrations strictly against the original source text."""

    def __init__(self, ledger: Optional[List[Dict[str, Any]]] = None):
        self.ledger = ledger or SOURCE_EVENT_LEDGER

    def validate_series_fidelity(self, episode_narrations: List[str]) -> SourceFidelityScore:
        """Evaluate a full series of episode texts against the 17 source events."""
        combined_text = " ".join(episode_narrations).lower()
        missing_events = []
        forbidden_violations = []
        chronology_errors = []

        # 1. Check Forbidden Concepts (Hallucinations)
        for pattern, explanation in FORBIDDEN_CONCEPTS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                forbidden_violations.append(explanation)

        # 2. Check Event Coverage per Episode
        events_covered_count = 0
        last_found_ep = 0

        for item in self.ledger:
            req_kws = item["required_keywords"]
            target_ep = item["episode_assignment"]  # 1-indexed
            
            # Check if event is in the assigned episode (or surrounding +/- 1 episode)
            ep_text = ""
            if 1 <= target_ep <= len(episode_narrations):
                ep_text = episode_narrations[target_ep - 1].lower()
            
            # Also allow in whole text for fallback coverage
            matches_ep = [kw for kw in req_kws if re.search(rf"\b{re.escape(kw.lower())}\b", ep_text)]
            matches_all = [kw for kw in req_kws if re.search(rf"\b{re.escape(kw.lower())}\b", combined_text)]

            if len(matches_ep) >= max(1, int(len(req_kws) * 0.7)):
                events_covered_count += 1
                if target_ep < last_found_ep:
                    chronology_errors.append(f"Event {item['event_id']} (target Ep {target_ep}) out of sequence after Ep {last_found_ep}.")
                last_found_ep = target_ep
            elif len(matches_all) >= max(1, int(len(req_kws) * 0.7)):
                # Present somewhere, but wrong episode
                events_covered_count += 1
                chronology_errors.append(f"Event {item['event_id']} found in different episode than assigned Ep {target_ep}.")
            else:
                missing_events.append(f"[{item['checklist_item']}] {item['event_id']}: missing keywords ({set(req_kws) - set(matches_all)}) in Ep {target_ep}")

        # 3. Check Ending Preservation
        last_episode = episode_narrations[-1].lower() if episode_narrations else ""
        ending_match = "dammit, brother, you were right" in last_episode and "wish i'd never heard" in last_episode
        if not ending_match:
            missing_events.append("[17] EVT_17_FINAL_REALIZATION_ENDING: Exact final line not preserved verbatim.")

        # 4. Compute Score (10.0 scale)
        coverage_pct = events_covered_count / len(self.ledger)
        score = coverage_pct * 8.0  # Up to 8.0 for event coverage

        # Bonus 1.0 for exact ending
        if ending_match:
            score += 1.0

        # Bonus 1.0 for zero forbidden hallucinations
        if not forbidden_violations:
            score += 1.0
        else:
            score = max(0.0, score - (len(forbidden_violations) * 2.0))

        # Penalty for chronology errors
        if chronology_errors:
            score = max(0.0, score - (len(chronology_errors) * 1.0))

        score = round(min(10.0, max(0.0, score)), 2)
        passed = (
            score >= 9.0
            and len(missing_events) == 0
            and len(forbidden_violations) == 0
            and len(chronology_errors) == 0
            and ending_match
        )

        return SourceFidelityScore(
            fidelity_score=score,
            passed=passed,
            events_covered=events_covered_count,
            total_events=len(self.ledger),
            missing_events=missing_events,
            forbidden_violations=forbidden_violations,
            chronology_errors=chronology_errors,
            ending_preserved=ending_match,
            details={
                "coverage_pct": round(coverage_pct * 100, 1),
                "event_count": len(self.ledger),
            },
        )


source_fidelity_validator = SourceFidelityValidator()
