"""Production Incident End-to-End Verification Harness.

Executes isolated, end-to-end production runs for:
1. Automatic Mystery: Flight 19 in Bermuda Triangle (inside-out)
2. Automatic History: 1911 Mona Lisa Theft (paper-atlas)
3. Automatic Space: Shoemaker-Levy 9 Collision (stick-story)
4. Creator Series Horror: The Scariest Story Ever Told (paper-atlas)

Produces for each:
- Approved script with provenance
- Final narration audio with storytelling direction
- Scene storyboard with non-repetitive visual types
- Rendered video MP4
- Representative extracted frames
- Quality Control Report with 5-dimensional sub-scores
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curiosity_engine.config import OUTPUT_DIR, TEMPLATES_DIR
from curiosity_engine.content.scriptwriter import assign_line_scenes
from curiosity_engine.production.director import prepare_project
from curiosity_engine.production.renderer import render_project_video
from curiosity_engine.quality.provenance import build_production_provenance
from curiosity_engine.quality.qc_gatekeeper import verify_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("incident_verifier")

BASE_EVAL_DIR = OUTPUT_DIR / "incident_eval"


def extract_frames(video_mp4: Path, out_dir: Path, timestamps: list[float]) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    for t in timestamps:
        frame_file = out_dir / f"frame_t{int(t):02d}s.jpg"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(t),
            "-i", str(video_mp4),
            "-frames:v", "1",
            "-q:v", "2",
            str(frame_file)
        ]
        res = subprocess.run(cmd, capture_output=True)
        if frame_file.exists() and frame_file.stat().st_size > 5000:
            frame_paths.append(str(frame_file))
    return frame_paths


def build_test_cases() -> list[dict]:
    # 1. Mystery: Flight 19
    m_path = Path("output/original_story_demo/demo_01_flight_19_mystery.json")
    with open(m_path, "r", encoding="utf-8") as f:
        m_doc = json.load(f)
    mystery_script = {
        "id": "mystery_flight_19",
        "topic": "Flight 19 Vanishes in the Bermuda Triangle",
        "category": "MYSTERY",
        "style": "inside-out",
        "voice": "am_michael",
        "storytelling_delivery": True,
        "lines": m_doc["final_original_script"]["lines"],
        "sources": ["Naval History and Heritage Command: Flight 19", "US Navy Official Incident Archive 1945"],
        "evidence_type": "unexplained_mystery",
    }

    # 2. History: Mona Lisa Theft
    history_lines = [
        {"text": "In 1911, an unarmed carpenter walked out of the Louvre with the Mona Lisa."},
        {"text": "Vincenzo Peruggia had worked as a museum glazier, memorizing every guard rotation."},
        {"text": "On a quiet Monday morning, he slipped into a closet and waited for silence."},
        {"text": "He lifted the panel off the wall and hid the masterpiece under his coat."},
        {"text": "Incredibly, museum guards did not notice the empty wall for twenty-four hours."},
        {"text": "For two years, the stolen painting sat inside a wooden trunk in Paris."},
        {"text": "Peruggia was finally captured in Florence trying to sell the portrait to dealers."},
        {"text": "That brazen theft made an ordinary portrait the most famous painting in history."},
    ]
    history_script = {
        "id": "history_mona_lisa_theft",
        "topic": "The 1911 Mona Lisa Theft from the Louvre",
        "category": "HISTORY",
        "style": "paper-atlas",
        "voice": "am_michael",
        "storytelling_delivery": True,
        "lines": history_lines,
        "sources": ["Louvre Museum Historical Records 1911", "French Ministry of Justice Police Dossier"],
        "evidence_type": "documented_fact",
    }

    # 3. Space: Shoemaker-Levy 9 Collision
    space_lines = [
        {"text": "In 1994, twenty-one cosmic missiles slammed into Jupiter and scarred the planet."},
        {"text": "Astronomers watched as comet Shoemaker-Levy nine was torn apart by Jupiter's gravity."},
        {"text": "The icy fragments hurtled toward the planet at one hundred thirty thousand miles per hour."},
        {"text": "Each collision produced colossal fireballs rising thousands of miles above the clouds."},
        {"text": "The largest fragment created a dark impact bruise larger than planet Earth."},
        {"text": "For months, those scorched impact rings remained visible through backyard telescopes."},
        {"text": "The event gave humanity its first direct proof that cosmic collisions are real."},
        {"text": "Thirty years later, astronomers still scan deep space for incoming threats."},
    ]
    space_script = {
        "id": "space_shoemaker_levy_9",
        "topic": "Shoemaker-Levy 9 Jupiter Collision",
        "category": "SPACE",
        "style": "stick-story",
        "voice": "am_michael",
        "storytelling_delivery": True,
        "lines": space_lines,
        "sources": ["NASA Jet Propulsion Laboratory: SL9 Impact Archive", "Hubble Space Telescope Science Institute"],
        "evidence_type": "documented_fact",
    }

    # 4. Creator Series Horror: The Scariest Story Ever Told Ep 1
    horror_lines = [
        {"text": "I was twelve when our school bus broke down on a desolate county road."},
        {"text": "The substitute driver looked in his rearview mirror and asked if we wanted a story."},
        {"text": "He warned it was the scariest story in existence, but I put on my Walkman headphones."},
        {"text": "When the cassette ended, the bus had fallen into complete, paralyzed silence."},
        {"text": "Every kid sat slack-jawed and wide-eyed, refusing to repeat a single word."},
        {"text": "Moments later, a horrific crash crushed the driver's side of our bus."},
        {"text": "We survived, but none of those children were ever the same again."},
        {"text": "Decades later, the secret of what they heard refuses to stay buried."},
    ]
    creator_script = {
        "id": "creator_horror_scariest_story_ep1",
        "topic": "The Scariest Story Ever Told | Part 1: The Mountain Pass",
        "category": "CreatorSeries",
        "style": "paper-atlas",
        "voice": "am_michael",
        "storytelling_delivery": True,
        "lines": horror_lines,
        "sources": ["Creator Narrative Source Text: Authoritative Archive"],
        "evidence_type": "personal_account",
        "content_lane": "creator_series",
    }

    return [
        {"test_id": "test_01_mystery_flight19", "lane": "automatic", "script": mystery_script},
        {"test_id": "test_02_history_monalisa", "lane": "automatic", "script": history_script},
        {"test_id": "test_03_space_shoemakerlevy", "lane": "automatic", "script": space_script},
        {"test_id": "test_04_creator_horror_ep1", "lane": "creator_series", "script": creator_script},
    ]


def run_single_test(tc: dict, resume: bool = False) -> dict:
    test_id = tc["test_id"]
    lane = tc["lane"]
    script_data = tc["script"]
    style = script_data.get("style", "inside-out")

    logger.info(f"\n========================================================")
    logger.info(f"Running Incident Verification: {test_id} ({script_data['topic']})")
    logger.info(f"========================================================")

    # 1. Assign scenes with non-repetitive visual types
    assign_line_scenes(script_data)

    # 2. Build authoritative provenance record
    provenance = build_production_provenance(
        video_id=test_id,
        content_lane=lane,
        topic_id=script_data["id"],
        script_data=script_data,
        original_source_id=script_data["id"],
    )

    # 3. Prepare project (synthesize narration + align words)
    # Target directory under output/incident_eval/<test_id>
    proj_dir = BASE_EVAL_DIR / test_id
    if not resume or not proj_dir.exists():
        if proj_dir.exists():
            shutil.rmtree(proj_dir)
        proj_dir.mkdir(parents=True, exist_ok=True)

        tmpl_dir = TEMPLATES_DIR / style
        shutil.copytree(tmpl_dir, proj_dir, dirs_exist_ok=True)

        with open(proj_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_data, f, indent=2)

        from curiosity_engine.production.tts_engine import synthesize_narration
        from curiosity_engine.production.aligner import align_narration_words

        logger.info(f"[{test_id}] Synthesizing storytelling narration...")
        synthesize_narration(proj_dir)

        logger.info(f"[{test_id}] Aligning word timestamps...")
        align_narration_words(proj_dir)
    else:
        logger.info(f"[{test_id}] Resuming existing prepared project in {proj_dir}...")

    # 4. Render video MP4
    output_mp4 = BASE_EVAL_DIR / f"{test_id}.mp4"
    logger.info(f"[{test_id}] Rendering video to {output_mp4}...")
    render_project_video(proj_dir, output_mp4, resume=resume, force_rebuild=not resume)

    # 5. Extract representative preview frames
    frames_dir = BASE_EVAL_DIR / test_id / "preview_frames"
    extracted_frames = extract_frames(output_mp4, frames_dir, [2.0, 15.0, 28.0, 42.0])

    # 6. Execute Quality Control Gatekeeper
    qc_metadata = {
        "video_id": test_id,
        "content_lane": lane,
        "topic": script_data["topic"],
        "category": script_data["category"],
        "youtube_title": f"{script_data['topic']} #Shorts",
        "provenance": provenance,
        "script": script_data,
        "sources": script_data.get("sources", []),
        "evidence_type": script_data.get("evidence_type", "documented_fact"),
    }
    qc_report = verify_video(output_mp4, qc_metadata, project_dir=proj_dir)

    result = {
        "test_id": test_id,
        "content_lane": lane,
        "topic": script_data["topic"],
        "category": script_data["category"],
        "style": style,
        "duration_sec": qc_report.checks.get("duration_sec"),
        "resolution": qc_report.checks.get("resolution"),
        "provenance": provenance,
        "storyboard_scenes": [
            {"beat": i+1, "visual_type": ln.get("scene", {}).get("visual_type"), "headline": ln.get("scene", {}).get("headline")}
            for i, ln in enumerate(script_data["lines"])
        ],
        "qc_passed": qc_report.passed,
        "overall_score": qc_report.checks.get("overall_score"),
        "sub_scores": qc_report.checks.get("sub_scores"),
        "hard_failures": qc_report.checks.get("hard_failures", []),
        "issues": qc_report.issues,
        "video_mp4": str(output_mp4),
        "preview_frames": extracted_frames,
    }

    with open(BASE_EVAL_DIR / f"{test_id}_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    logger.info(
        f"Completed {test_id}: QC={'PASSED' if qc_report.passed else 'FAILED'}, "
        f"Score={qc_report.checks.get('overall_score')}, "
        f"Dur={qc_report.checks.get('duration_sec')}s"
    )
    return result


def main():
    BASE_EVAL_DIR.mkdir(parents=True, exist_ok=True)
    tests = build_test_cases()

    args = sys.argv[1:]
    resume_flag = "--resume" in args
    target_ids = [a for a in args if not a.startswith("--")]

    if target_ids:
        tests = [tc for tc in tests if tc["test_id"] in target_ids]

    results = []
    for tc in tests:
        res = run_single_test(tc, resume=resume_flag)
        results.append(res)

    summary_file = BASE_EVAL_DIR / "incident_verification_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logger.info(f"\nAll verification tests completed. Summary saved to {summary_file}.")


if __name__ == "__main__":
    main()
