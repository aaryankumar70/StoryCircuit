"""Tests for StoryDirector across random, plan, and custom_script modes."""
from __future__ import annotations

from reelforge.brain.director import StoryDirector
from reelforge.models import SourceMode
from reelforge.storage.db import ReelDatabase


class _StubLLM:
    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.6):
        return None


def test_custom_script_preserves_exact_words_and_host_cues(tmp_path):
    db = ReelDatabase(tmp_path / "test.db")
    director = StoryDirector(llm=_StubLLM())
    script = (
        "[Alex]: Why did a 1912 brass diving bell vanish in the Baltic Sea?\n"
        "[Maya]: Navy logs showed three contradictory sonar readings that night."
    )
    plan = director.build_story(
        db,
        mode=SourceMode.CUSTOM_SCRIPT,
        topic="Baltic Diving Bell",
        custom_script=script,
        style="editorial_dark",
    )
    assert plan.title == "Baltic Diving Bell"
    assert len(plan.beats) == 2
    assert plan.beats[0].speaker == "primary"
    assert plan.beats[1].speaker == "secondary"
    assert "1912 brass diving bell" in plan.beats[0].text
    assert "three contradictory sonar readings" in plan.beats[1].text
    assert all(b.visual_prompt for b in plan.beats)
    assert all(b.broll_query for b in plan.beats)
    assert all(b.host_appearance in ("presenter", "cameo", "none") for b in plan.beats)


def test_random_mode_produces_non_empty_media_beats_offline(tmp_path):
    db = ReelDatabase(tmp_path / "test.db")
    director = StoryDirector(llm=_StubLLM())
    plan = director.build_story(
        db,
        mode=SourceMode.PLAN,
        topic="The 1814 London Beer Flood",
        facts=(
            "In October 1814 an iron hoop snapped on a wooden vat in London. "
            "Over 320,000 gallons of porter surged through St Giles streets. "
            "Walls collapsed within minutes across two neighboring blocks. "
            "Rescuers waded waist-deep through dark beer searching for survivors."
        ),
    )
    assert len(plan.beats) >= 4
    assert all(b.visual_prompt for b in plan.beats)
    assert all(b.broll_query for b in plan.beats)
