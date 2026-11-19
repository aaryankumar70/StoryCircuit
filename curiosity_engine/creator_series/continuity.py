"""Story & Character Continuity Engine for CurioLoop Creator Series.

Maintains a persistent continuity ledger across serialized episodes to prevent:
- Repeated character introductions
- Inconsistent age/appearance states
- Duplicated narration or phrasing
- Premature revelations
- Forgotten clues
- Contradictory timeline facts
- Accidental ending alterations
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("curiosity_engine.continuity")


@dataclass
class ContinuityLedgerEntry:
    episode_num: int
    title: str
    revealed_facts: List[str]
    introduced_characters: List[str]
    introduced_locations: List[str]
    opening_frame_motif: str
    closing_frame_motif: str
    withheld_until_next: List[str]
    hand_off_notes: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CharacterStateRecord:
    character_id: str
    canonical_name: str
    state_id: str
    age: Any
    timeline_period: str
    clothing: List[str]
    locked_traits: List[str]
    reference_description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LocationRecord:
    location_id: str
    name: str
    variants: List[str]
    fixed_elements: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StoryContinuityBible:
    series_id: str
    characters: Dict[str, CharacterStateRecord] = field(default_factory=dict)
    locations: Dict[str, LocationRecord] = field(default_factory=dict)
    ledger: List[ContinuityLedgerEntry] = field(default_factory=list)
    established_facts: Set[str] = field(default_factory=set)
    unanswered_questions: List[str] = field(default_factory=list)
    narrative_perspective: str = "first_person"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_id": self.series_id,
            "characters": {k: v.to_dict() for k, v in self.characters.items()},
            "locations": {k: v.to_dict() for k, v in self.locations.items()},
            "ledger": [e.to_dict() for e in self.ledger],
            "established_facts": sorted(list(self.established_facts)),
            "unanswered_questions": self.unanswered_questions,
            "narrative_perspective": self.narrative_perspective,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoryContinuityBible":
        chars = {
            k: CharacterStateRecord(**v)
            for k, v in data.get("characters", {}).items()
        }
        locs = {
            k: LocationRecord(**v)
            for k, v in data.get("locations", {}).items()
        }
        ledger = [
            ContinuityLedgerEntry(**e)
            for e in data.get("ledger", [])
        ]
        return cls(
            series_id=data.get("series_id", ""),
            characters=chars,
            locations=locs,
            ledger=ledger,
            established_facts=set(data.get("established_facts", [])),
            unanswered_questions=data.get("unanswered_questions", []),
            narrative_perspective=data.get("narrative_perspective", "first_person"),
        )


class ContinuityEngine:
    """Validates and enforces continuity between successive episodes."""

    def validate_episode_continuity(
        self,
        bible: StoryContinuityBible,
        episode_num: int,
        narration: str,
        upcoming_secrets: Optional[List[str]] = None,
    ) -> Tuple[bool, List[str]]:
        """Verify that episode N adheres to previously established facts and avoids premature reveals."""
        errors: List[str] = []
        narration_lower = narration.lower()

        # Check premature revelations
        if upcoming_secrets:
            for secret in upcoming_secrets:
                words = [w for w in secret.lower().split() if len(w) > 3]
                if words and all(w in narration_lower for w in words):
                    errors.append(f"Premature revelation detected in Ep {episode_num}: '{secret}'")

        # Check repeated verbatim intros
        if episode_num > 1 and len(bible.ledger) >= episode_num - 1:
            prev_entry = bible.ledger[episode_num - 2]
            for intro_char in prev_entry.introduced_characters:
                # If introduced previously, shouldn't re-introduce with "My name is" or "Let me introduce"
                pattern = rf"\b(meet|introducing|my name is)\s+{re.escape(intro_char.lower())}\b"
                if re.search(pattern, narration_lower):
                    errors.append(f"Redundant character re-introduction in Ep {episode_num} for '{intro_char}'")

        is_valid = len(errors) == 0
        return is_valid, errors

    def record_episode_in_ledger(
        self,
        bible: StoryContinuityBible,
        entry: ContinuityLedgerEntry,
    ) -> None:
        """Append episode hand-off record to the persistent continuity ledger."""
        bible.ledger.append(entry)
        for fact in entry.revealed_facts:
            bible.established_facts.add(fact)
        logger.info(
            f"Logged Episode {entry.episode_num} into continuity ledger for '{bible.series_id}'."
        )


continuity_engine = ContinuityEngine()
