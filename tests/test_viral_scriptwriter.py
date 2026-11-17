"""Comprehensive Test Suite for Viral Shorts Scriptwriter & Editorial Transformation.

Verifies:
1. Editorial Policy:
   - Three allowed categories: MYSTERY, HISTORY, SPACE.
   - Rejection of biology, anatomy, animal trivia, medical advice, and generic science lists.
   - Contextual space validation: space stories are allowed while biology/science trivia is denied.
2. Research Dossier Engine:
   - Source credibility tiers (Tier 1-4).
   - Claim verification and dossier structure validation.
3. Narrative Engine:
   - 8-candidate Hook Playbook generation.
   - Hook evaluation: <= 14 words, no banned openers, concrete specifics.
   - 5-beat documentary structure (Hook, Stakes, 3 Escalations, Turn, Loop).
4. Independent Story Critic:
   - 10-dimension scoring and strict publication thresholds.
   - Targeted rewrites and emergency repair.
5. Deterministic Script Validator:
   - Calibrated 2.46 WPS duration (42-58s target, 40-60s hard bounds).
   - Word budget (103-140 words target, 90-148 words hard bounds).
   - Sentence length <= 22 words, banned slop phrases, weak CTAs.
6. Curated Fallback Catalog:
   - 30 verified dossiers (10 Mystery, 10 History, 10 Space).
   - 100% pass deterministic validator.
7. Downstream Compatibility & Full Pipeline Integration.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Dict

import pytest

from curiosity_engine.config import (
    CALIBRATED_WORDS_PER_SECOND,
    MAX_DURATION_SEC,
    MIN_DURATION_SEC,
    STYLE_MAPPINGS,
    VOICE_MAP,
)
from curiosity_engine.content.curated_fallback import CURATED_TOPICS
from curiosity_engine.content.editorial_policy import (
    ALLOWED_CATEGORIES,
    BANNED_OPENERS,
    BANNED_PHRASES,
    WEAK_CTAS,
    get_visual_style_for_category,
    is_forbidden_content,
    normalize_category_name,
    validate_editorial_category,
)
from curiosity_engine.content.narrative_engine import (
    build_documentary_outline,
    evaluate_hook_candidate,
    generate_draft_script,
    generate_hook_candidates,
    select_best_hook,
)
from curiosity_engine.content.research_dossier import (
    build_research_dossier,
    classify_source_tier,
    validate_dossier,
)
from curiosity_engine.content.scriptwriter import count_spoken_words, write_video_script
from curiosity_engine.content.story_critic import (
    CRITIC_DIMENSIONS,
    THRESHOLDS,
    critique_and_rewrite,
    evaluate_script_critique,
    repair_script_emergency,
)
from curiosity_engine.quality.script_validator import extract_script_fields, validate_script


# =============================================================================
# 1. EDITORIAL POLICY TESTS
# =============================================================================
class TestEditorialPolicy:
    def test_allowed_categories(self):
        assert set(ALLOWED_CATEGORIES) == {"MYSTERY", "HISTORY", "SPACE"}

    @pytest.mark.parametrize("category,expected", [
        ("MYSTERY", "MYSTERY"),
        ("History", "HISTORY"),
        ("space", "SPACE"),
        ("Unexplained events", "MYSTERY"),
        ("historical_events", "HISTORY"),
        ("cosmic_mysteries", "SPACE"),
        ("Survival", "HISTORY"),
        ("Interesting discoveries", "HISTORY"),
    ])
    def test_normalize_category_name(self, category, expected):
        assert normalize_category_name(category) == expected

    @pytest.mark.parametrize("forbidden_topic,expected_reason_substr", [
        ("Why do your ears ring in absolute silence?", "ears"),
        ("How dopamine and serotonin control motivation", "dopamine"),
        ("A blind Arctic shark born in 1600s may still be swimming", "shark"),
        ("Top 10 facts about the human brain", "trivia"),
        ("Why half the people miss someone in a gorilla suit", "gorilla"),
        ("New medical study reveals unexpected drug side effects", "medical"),
        ("10 amazing facts about photosynthesis and chlorophyll", "trivia"),
    ])
    def test_forbidden_content_detection(self, forbidden_topic, expected_reason_substr):
        forbidden, reason = is_forbidden_content(forbidden_topic)
        assert forbidden is True
        assert expected_reason_substr.lower() in reason.lower()

    @pytest.mark.parametrize("valid_text,declared_cat,expected_cat", [
        ("The Wow! Signal detected in 1977 by the Big Ear radio telescope in Ohio", "Space", "SPACE"),
        ("Why an intact ship was found sailing alone in 1872 without a soul aboard", "Mystery", "MYSTERY"),
        ("In 1925, a con man sold the Eiffel Tower for scrap metal twice", "History", "HISTORY"),
        ("In 2015, Kepler discovered Tabby's star dimming by twenty-two percent", "Space", "SPACE"),
        ("The water-trapped booby traps of the Oak Island Money Pit in Nova Scotia", "Mystery", "MYSTERY"),
        ("In 1859, the Carrington solar flare ignited telegraph paper worldwide", "History", "HISTORY"),
    ])
    def test_contextual_category_validation_accepts_valid_documentaries(self, valid_text, declared_cat, expected_cat):
        is_valid, detected_cat, reason = validate_editorial_category(valid_text, declared_category=declared_cat)
        assert is_valid is True
        assert detected_cat == expected_cat
        assert reason == ""

    def test_contextual_category_validation_rejects_forbidden_content(self):
        is_valid, detected_cat, reason = validate_editorial_category(
            "Why your ears ring in absolute silence in anechoic chambers",
            declared_category="Biology",
        )
        assert is_valid is False
        assert "forbidden" in reason.lower()

    @pytest.mark.parametrize("category,expected_style", [
        ("MYSTERY", "paper-atlas"),
        ("HISTORY", "paper-atlas"),
        ("SPACE", "inside-out"),
    ])
    def test_visual_style_routing(self, category, expected_style):
        assert get_visual_style_for_category(category) == expected_style


# =============================================================================
# 2. RESEARCH DOSSIER TESTS
# =============================================================================
class TestResearchDossier:
    @pytest.mark.parametrize("url,expected_tier", [
        ("https://www.nasa.gov/mission_pages/apollo", "TIER_1_PRIMARY"),
        ("https://www.nature.com/articles/s41586", "TIER_2_ACADEMIC"),
        ("https://www.science.org/doi/10.1126", "TIER_2_ACADEMIC"),
        ("https://www.smithsonianmag.com/history/amber-room", "TIER_3_INSTITUTION"),
        ("https://www.britannica.com/topic/Mary-Celeste", "TIER_3_INSTITUTION"),
        ("https://www.bbc.com/news/science-environment", "TIER_4_JOURNALISM"),
        ("https://random-blog.xyz/post", "TIER_5_SECONDARY"),
    ])
    def test_source_tier_classification(self, url, expected_tier):
        assert classify_source_tier(url) == expected_tier

    def test_build_research_dossier_deterministic(self):
        dossier = build_research_dossier(
            topic="The Wow! Signal of 1977",
            category="Space",
            source_seeds=["https://www.planetary.org/articles/the-wow-signal"],
        )
        is_valid, errors = validate_dossier(dossier)
        assert is_valid is True
        assert dossier["category"] == "SPACE"
        assert len(dossier["verified_claims"]) >= 2
        assert len(dossier["sources"]) >= 1
        assert (dossier.get("niche") or dossier.get("subcategory")) in ("space_mysteries", "space_exploration", "astrophysics_phenomena")

    def test_validate_dossier_rejects_insufficient_claims(self):
        invalid_dossier = {
            "topic": "Empty Story",
            "category": "MYSTERY",
            "verified_claims": [],
            "sources": ["https://en.wikipedia.org/wiki/Test"],
        }
        is_ok, errors = validate_dossier(invalid_dossier)
        assert is_ok is False
        assert any("claims" in e.lower() for e in errors)


# =============================================================================
# 3. NARRATIVE ENGINE & HOOK PLAYBOOK TESTS
# =============================================================================
class TestNarrativeEngine:
    def test_evaluate_hook_candidate_valid(self):
        hook = "In 1872, an intact ship was found sailing alone across the Atlantic."
        candidate = evaluate_hook_candidate(hook, "impossible_claim")
        assert candidate.is_valid is True
        assert candidate.word_count <= 14
        assert candidate.score >= 8.0
        assert len(candidate.rejection_reasons) == 0

    @pytest.mark.parametrize("bad_hook,reason_substr", [
        ("Did you know that in 1872 an intact ship was found sailing across the Atlantic ocean?", "banned opener"),
        ("Imagine waking up in the morning and finding an entire ancient Egyptian city underwater.", "banned opener"),
        ("In this video we will explore why a solar storm set telegraph papers on fire in 1859.", "banned opener"),
        ("In nineteen twenty-five a con man decided that he could sell the Eiffel Tower to scrap metal dealers because it was too expensive to maintain.", "exceeds 14 words"),
        ("Why do your ears ring inside a soundproof room when there is zero noise?", "forbidden"),
    ])
    def test_evaluate_hook_candidate_invalid(self, bad_hook, reason_substr):
        candidate = evaluate_hook_candidate(bad_hook, "mid_action")
        assert candidate.is_valid is False
        assert any(reason_substr.lower() in r.lower() for r in candidate.rejection_reasons)

    def test_generate_hook_candidates_playbook_coverage(self):
        dossier = build_research_dossier(
            topic="The Vanished Amber Room of Konigsberg",
            category="MYSTERY",
            source_seeds=["https://en.wikipedia.org/wiki/Amber_Room"],
        )
        hooks = generate_hook_candidates(dossier)
        assert len(hooks) >= 8
        best = select_best_hook(hooks)
        assert best.is_valid is True
        assert best.score >= 7.0

    def test_build_documentary_outline_structure(self):
        dossier = build_research_dossier("The Wow! Signal", "Space", ["https://planetary.org/wow"])
        hook = evaluate_hook_candidate("In 1977, a radio telescope detected a seventy-two second burst from deep space.", "number_shock")
        outline = build_documentary_outline(dossier, hook)
        assert len(outline) == 7
        assert outline[0].name == "Hook"
        assert outline[1].name == "Stakes & Context"
        assert outline[-1].name == "Resolution / Loop Line"
        # Verify scenes attached
        for beat in outline:
            assert "visual_type" in beat.scene
            assert "headline" in beat.scene

    def test_generate_draft_script_calibrated_word_count(self):
        dossier = build_research_dossier("The Wow! Signal", "Space", ["https://planetary.org/wow"])
        hook = evaluate_hook_candidate("In 1977, a radio telescope detected a seventy-two second burst from deep space.", "number_shock")
        outline = build_documentary_outline(dossier, hook)
        draft = generate_draft_script(dossier, hook, outline)
        assert 103 <= draft.word_count <= 140
        assert 40.0 <= draft.est_seconds <= 60.0
        assert draft.lines[0]["text"] == hook.text


# =============================================================================
# 4. INDEPENDENT STORY CRITIC TESTS
# =============================================================================
class TestStoryCritic:
    def test_critic_evaluates_all_ten_dimensions(self):
        script = CURATED_TOPICS[0]["script"]
        report = evaluate_script_critique(script, CURATED_TOPICS[0].get("research_dossier"))
        assert len(report.scores) == 10
        for dim in CRITIC_DIMENSIONS:
            assert dim in report.scores
            assert 0.0 <= report.scores[dim] <= 10.0
        assert report.overall_score >= THRESHOLDS["overall"]
        assert report.passed is True

    def test_critic_fails_weak_hook_or_forbidden_content(self):
        bad_script = {
            "title": "Bad Story",
            "lines": [
                {"text": "Did you know that your ears ring when it is quiet?"},
                {"text": "This biology trivia is very interesting to know."},
                {"text": "Subscribe to our channel for more videos."},
            ],
        }
        report = evaluate_script_critique(bad_script, {})
        assert report.passed is False
        assert report.scores["hook_strength"] < 7.0
        assert report.scores["ending_quality"] < 7.0

    def test_targeted_rewrite_cleans_weak_opener_and_cta(self):
        flawed_script = {
            "title": "Test Heist",
            "lines": [
                {"text": "Did you know in 1925 a con man sold the Eiffel Tower twice to scrap dealers."},
                {"text": "Victor Lustig forged official French government credentials to execute the scam."},
                {"text": "Andre Poisson paid seventy thousand dollars in cash to secure the demolition contract."},
                {"text": "Lustig fled to Vienna immediately with a suitcase packed with French currency."},
                {"text": "Poisson was too humiliated to ever report the con to the Paris police."},
                {"text": "Please subscribe to the channel and like for part 2."},
            ],
        }
        repaired, new_report = critique_and_rewrite(flawed_script, {})
        assert not repaired["lines"][0]["text"].lower().startswith("did you know")
        assert "subscribe" not in repaired["lines"][-1]["text"].lower()


# =============================================================================
# 5. DETERMINISTIC SCRIPT VALIDATOR TESTS
# =============================================================================
class TestScriptValidator:
    def test_extract_script_fields(self):
        data = {
            "title": "Test Title",
            "category": "MYSTERY",
            "lines": [{"text": "First line."}, {"text": "Second line."}],
        }
        title, cat, hook, beats, text = extract_script_fields(data)
        assert title == "Test Title"
        assert cat == "MYSTERY"
        assert hook == "First line."
        assert len(beats) == 2
        assert text == "First line. Second line."

    def test_validate_script_duration_and_word_count(self):
        # 114 words at 2.46 WPS + 8 sentences * 0.25s = 48.3s (Passes target & hard bounds)
        script = {
            "title": "The Wow! Signal",
            "category": "SPACE",
            "lines": [
                {"text": "In 1977, a seventy-two second radio burst hit an Ohio telescope."},
                {"text": "Astronomers logged the exact frequency within minutes, discovering an intense narrowband signal."},
                {"text": "No known satellite or military aircraft was passing through that sector of sky."},
                {"text": "The extraterrestrial transmitter would have required megawatts of focused power."},
                {"text": "Search teams scanned that exact same cosmic coordinate continuously for forty-nine years."},
                {"text": "Decades of deep space surveillance revealed nothing but natural background noise."},
                {"text": "Yet astronomers confirmed the broadcast was never repeated, leaving the source completely unclassified."},
                {"text": "Every sensor verified the signal was genuine and came from deep space."},
                {"text": "Official observatory logs recorded thirty times the standard cosmic radiation."},
                {"text": "Decades later, official archives still preserve that seventy-two second burst."},
            ],
        }
        res = validate_script(script, wps=CALIBRATED_WORDS_PER_SECOND)
        assert res["ok"] is True
        assert 103 <= res["words"] <= 140
        assert 42.0 <= res["est_seconds"] <= 58.0
        assert len(res["errors"]) == 0

    @pytest.mark.parametrize("flaw_type,script_mutation,expected_err_substr", [
        ("long_hook", lambda s: s["lines"].__setitem__(0, {"text": "In 1977 a very long seventy two second radio burst hit an Ohio telescope during a night shift."}), "hook exceeds 14 words"),
        ("banned_opener", lambda s: s["lines"].__setitem__(0, {"text": "Did you know a seventy two second radio burst hit an Ohio telescope?"}), "prohibited opener"),
        ("ai_slop", lambda s: s["lines"].__setitem__(1, {"text": "Astronomers were left stunned when this mind-blowing discovery changed everything."}), "prohibited ai slop"),
        ("weak_cta", lambda s: s["lines"].__setitem__(-1, {"text": "Follow for more daily space mysteries and comment below."}), "prohibited weak cta"),
        ("long_sentence", lambda s: s["lines"].__setitem__(2, {"text": "No known satellite or military aircraft or weather balloon or experimental plane of any nation on earth was passing through that exact sector of sky at midnight."}), "sentence exceeds 22 words"),
        ("biology_violation", lambda s: s["lines"].__setitem__(3, {"text": "The human brain and nervous system perceive sensory input through neural synapses and hormones."}), "forbidden content policy"),
    ])
    def test_validator_catches_all_flaws(self, flaw_type, script_mutation, expected_err_substr):
        base_script = {
            "title": "The Wow! Signal",
            "category": "SPACE",
            "lines": [
                {"text": "In 1977, a seventy-two second radio burst hit an Ohio telescope."},
                {"text": "Astronomers logged the exact frequency within minutes, discovering an intense narrowband signal."},
                {"text": "No known satellite or military aircraft was passing through that sector of sky."},
                {"text": "The extraterrestrial transmitter would have required megawatts of focused power."},
                {"text": "Search teams scanned that exact same cosmic coordinate continuously for forty-nine years."},
                {"text": "Decades of deep space surveillance revealed nothing but natural background noise."},
                {"text": "Yet astronomers confirmed the broadcast was never repeated, leaving the source completely unclassified."},
                {"text": "Every sensor verified the signal was genuine and came from deep space."},
                {"text": "Official observatory logs recorded thirty times the standard cosmic radiation."},
                {"text": "Decades later, official archives still preserve that seventy-two second burst."},
            ],
        }
        test_script = copy.deepcopy(base_script)
        script_mutation(test_script)
        res = validate_script(test_script, wps=CALIBRATED_WORDS_PER_SECOND)
        assert res["ok"] is False
        assert any(expected_err_substr.lower() in err.lower() for err in res["errors"])


# =============================================================================
# 6. CURATED FALLBACK CATALOG OVERHAUL TESTS
# =============================================================================
class TestCuratedFallbackCatalog:
    def test_curated_topics_count_and_distribution(self):
        assert len(CURATED_TOPICS) >= 30
        mysteries = [t for t in CURATED_TOPICS if t["category"] == "MYSTERY"]
        histories = [t for t in CURATED_TOPICS if t["category"] == "HISTORY"]
        spaces = [t for t in CURATED_TOPICS if t["category"] == "SPACE"]

        assert len(mysteries) >= 10, f"Expected >= 10 Mystery topics, found {len(mysteries)}"
        assert len(histories) >= 10, f"Expected >= 10 History topics, found {len(histories)}"
        assert len(spaces) >= 10, f"Expected >= 10 Space topics, found {len(spaces)}"

    def test_all_curated_topics_pass_deterministic_validator(self):
        failures = []
        for item in CURATED_TOPICS:
            script = item["script"]
            dossier = item.get("research_dossier")
            res = validate_script(script, wps=CALIBRATED_WORDS_PER_SECOND, dossier=dossier)
            if not res["ok"]:
                failures.append((item["id"], res["errors"]))
        assert len(failures) == 0, f"Curated catalog failures: {failures}"

    def test_curated_topics_downstream_schema(self):
        for item in CURATED_TOPICS:
            assert "id" in item
            assert "topic" in item
            assert "category" in item
            assert "style" in item
            assert "hook" in item
            assert "research_dossier" in item
            assert "lines" in item["script"]
            lines = item["script"]["lines"]
            assert len(lines) >= 6
            for idx, ln in enumerate(lines):
                assert "text" in ln
                assert "caps" in ln
                assert "gap" in ln
                assert "scene" in ln
                sc = ln["scene"]
                assert "visual_type" in sc
                assert "headline" in sc
                assert "mood" in sc
                assert "accent" in sc
                assert "cue" in sc


# =============================================================================
# 7. FULL INTEGRATION & PIPELINE REGRESSION TESTS
# =============================================================================
class TestScriptwriterPipelineIntegration:
    def test_write_video_script_returns_all_additive_fields(self):
        topic_info = {
            "topic": "The Sunken Port of Thonis-Heracleion",
            "category": "History",
            "style": "paper-atlas",
        }
        script = write_video_script(topic_info)
        assert script is not None
        assert "lines" in script
        assert "category" in script
        assert script["category"] == "HISTORY"
        assert "research_dossier" in script
        assert "hook" in script
        assert "hook_pattern" in script
        assert "claims" in script
        assert "sources" in script

        # Downstream compatibility checks
        assert count_spoken_words(script["lines"]) >= 90
        for ln in script["lines"]:
            assert "text" in ln
            assert "caps" in ln
            assert "gap" in ln
            assert "scene" in ln
            assert isinstance(ln["scene"], dict)

    def test_write_video_script_rejects_forbidden_biology_cleanly(self):
        # Passing an explicit biology query falls back safely to curated story without crashing
        bad_topic = {
            "topic": "Why do your ears ring in absolute silence and soundproof rooms?",
            "category": "Biology",
        }
        script = write_video_script(bad_topic)
        # Output must be a valid allowed category
        assert script["category"] in ("MYSTERY", "HISTORY", "SPACE")
        assert count_spoken_words(script["lines"]) >= 90


# =============================================================================
# 8. EDITORIAL EVALUATION SET VERIFICATION
# =============================================================================
class TestEditorialEvaluationSet:
    def test_ten_editorial_evaluation_artifacts_exist_and_pass(self):
        eval_dir = os.path.join(os.getcwd(), "output", "editorial_eval")
        assert os.path.isdir(eval_dir), f"Evaluation directory missing: {eval_dir}"
        eval_files = [f for f in os.listdir(eval_dir) if f.startswith("eval_script_") and f.endswith(".json")]
        assert len(eval_files) >= 10, f"Expected at least 10 eval files, found {len(eval_files)}"

        category_counts = {"MYSTERY": 0, "HISTORY": 0, "SPACE": 0}
        required_keys = [
            "topic", "category", "niche", "research_dossier", "hook_candidates",
            "selected_hook", "narrative_outline", "draft_script", "critic_evaluation",
            "revision_history", "final_script", "validator_result",
        ]

        for fname in eval_files:
            fpath = os.path.join(eval_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)

            for rk in required_keys:
                assert rk in data, f"File {fname} missing required key: {rk}"

            cat = data["category"]
            assert cat in category_counts, f"File {fname} has invalid category: {cat}"
            category_counts[cat] += 1

            # Verify hook candidates
            assert len(data["hook_candidates"]) >= 8, f"{fname} has fewer than 8 hook candidates"

            # Verify critic evaluation
            assert data["critic_evaluation"]["overall_score"] >= 8.0, f"{fname} critic score < 8.0"
            assert data["critic_evaluation"]["passed"] is True, f"{fname} critic did not pass"

            # Verify validator result
            val = validate_script(data["final_script"]["lines"], dossier=data["research_dossier"])
            assert val["ok"] is True, f"{fname} validation failed: {val['errors']}"
            assert len(val["errors"]) == 0, f"{fname} has errors: {val['errors']}"
            assert 90 <= val["words"] <= 148, f"{fname} words {val['words']} out of bounds"
            assert 40.0 <= val["est_seconds"] <= 60.0, f"{fname} duration {val['est_seconds']} out of bounds"

        assert category_counts["MYSTERY"] >= 3, f"Expected >= 3 MYSTERY, got {category_counts['MYSTERY']}"
        assert category_counts["HISTORY"] >= 3, f"Expected >= 3 HISTORY, got {category_counts['HISTORY']}"
        assert category_counts["SPACE"] >= 4, f"Expected >= 4 SPACE, got {category_counts['SPACE']}"
