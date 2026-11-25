"""Tests for long-script 1-2m splitter, end-of-day garbage remover, SEO metadata, and 16:9 auto-landscape."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

from reelforge import config
from reelforge.brain.metadata import build_youtube_tags, clean_youtube_title, enrich_story_metadata
from reelforge.brain.splitter import analyze_and_split_script
from reelforge.audio.underscore import generate_ambient_underscore
from reelforge.brain.llm_client import ZeroCostLLM
from reelforge.models import BeatSpec, SourceMode, StoryPlan, VideoFormat, VisualStyle, WordTiming
from reelforge.qc.gatekeeper import verify_video
from reelforge.storage.cleanup import cleanup_ended_day_videos
from reelforge.storage.db import ReelDatabase
from reelforge.video.captions import write_word_synced_ass
from reelforge.video.renderer import render_short_video
from reelforge.visuals.cards import compose_scene_frame, render_editorial_card
from reelforge.youtube.uploader import YouTubeUploader


def _make_long_script(sentences: int = 36) -> str:
    lines = []
    for i in range(1, sentences + 1):
        lines.append(
            f"In chapter {i}, engineers discovered an unexpected anomaly inside the old vault mechanism during winter tests."
        )
        if i % 6 == 0:
            lines.append("")
    return "\n".join(lines)


def test_long_script_splits_into_balanced_1_to_2_min_shorts():
    long_script = _make_long_script(34)  # ~510 words (~200s = ~3.3 min)
    res = analyze_and_split_script(long_script, base_title="The Vault Mechanism", category="mystery")
    assert res["exceeds_short_limit"] is True
    assert res["recommended_format"] == "long"
    assert res["possible_videos"] >= 2
    assert len(res["parts"]) == res["possible_videos"]

    for part in res["parts"]:
        assert 60.0 < part["estimated_duration_sec"] < 120.0
        assert part["description"]
        assert len(part["tags"]) >= 5
        assert "(Part " in part["title"]


def test_garbage_remover_deletes_ended_day_videos_and_preserves_history(tmp_path, monkeypatch):
    out_dir = tmp_path / "output"
    monkeypatch.setattr(config, "OUTPUT_DIR", out_dir)
    db = ReelDatabase(tmp_path / "cleanup.db")

    old_dir = out_dir / "rf_old_01"
    old_dir.mkdir(parents=True)
    old_mp4 = old_dir / "final.mp4"
    old_mp4.write_bytes(b"0" * 5000)

    today_dir = out_dir / "rf_today_01"
    today_dir.mkdir(parents=True)
    today_mp4 = today_dir / "final.mp4"
    today_mp4.write_bytes(b"1" * 5000)

    active_old_dir = out_dir / "rf_old_active"
    active_old_dir.mkdir(parents=True)
    (active_old_dir / "part.tmp").write_bytes(b"2" * 2000)

    db.create_job(
        job_id="rf_old_01",
        source_mode="random",
        title="Old Video",
        category="history",
        style="editorial_dark",
        script_text="Old story script.",
        storyboard={},
        scheduled_date="2026-11-24",
        slot_num=1,
        status="scheduled",
    )
    db.update_job("rf_old_01", video_path=str(old_mp4))
    db.record_topic_history("Old Video", "Old story script.", "history", "rf_old_01")

    db.create_job(
        job_id="rf_today_01",
        source_mode="random",
        title="Today Video",
        category="science",
        style="blueprint_tech",
        script_text="Today story script.",
        storyboard={},
        scheduled_date="2026-11-25",
        slot_num=1,
        status="scheduled",
    )
    db.update_job("rf_today_01", video_path=str(today_mp4))

    db.create_job(
        job_id="rf_old_active",
        source_mode="random",
        title="Active Old",
        category="story",
        style="editorial_dark",
        script_text="Still running.",
        storyboard={},
        scheduled_date="2026-11-24",
        slot_num=2,
        status="rendering",
    )

    stats = cleanup_ended_day_videos(db, current_date="2026-11-25")
    assert "rf_old_01" in stats["deleted_job_ids"]
    assert stats["freed_bytes"] >= 5000
    assert not old_dir.exists()
    assert today_mp4.exists()
    assert active_old_dir.exists()

    old_job = db.get_job("rf_old_01")
    assert old_job["video_path"] is None and old_job["cleaned_at"] is not None
    # Anti-repeat history MUST remain intact
    is_dup, _ = db.check_duplicate_topic("Old Video", "Old story script.")
    assert is_dup is True


def test_landscape_16x9_cards_captions_metadata_and_uploader(tmp_path):
    card = render_editorial_card(
        tmp_path / "land_card.png",
        style=VisualStyle.CINEMATIC_PAINTERLY,
        headline="Long Documentary Breakdown",
        body_text="When a script exceeds two minutes, StoryCircuit automatically renders 16:9 widescreen.",
        stat_text="16:9",
        badge_text="science",
        width=1920,
        height=1080,
    )
    with Image.open(card) as im:
        assert im.size == (1920, 1080)

    # Tall source photo framed cleanly on 1920x1080 blurred backdrop
    tall = tmp_path / "tall.png"
    Image.new("RGB", (600, 1000), (80, 110, 140)).save(tall)
    framed = compose_scene_frame(
        tall,
        tmp_path / "land_framed.png",
        style=VisualStyle.EDITORIAL_DARK,
        width=1920,
        height=1080,
    )
    with Image.open(framed) as im:
        assert im.size == (1920, 1080)

    ass = write_word_synced_ass(
        [WordTiming(word="Widescreen", start_sec=0.0, end_sec=0.5)],
        tmp_path / "land.ass",
        width=1920,
        height=1080,
    )
    ass_txt = ass.read_text(encoding="utf-8")
    assert "PlayResX: 1920" in ass_txt
    assert "PlayResY: 1080" in ass_txt

    plan = StoryPlan(
        title="Deep Dive Into Ancient Gears",
        hook="In 1901 divers lifted a corroded bronze box.",
        category="history",
        video_format=VideoFormat.LONG,
        target_width=1920,
        target_height=1080,
        source_mode=SourceMode.CUSTOM_SCRIPT,
        beats=[
            BeatSpec(index=0, text="Divers found the wreck.", visual_prompt="shipwreck", start_sec=0.0, end_sec=25.0),
            BeatSpec(index=1, text="Gears predicted eclipses.", visual_prompt="bronze gears", start_sec=25.0, end_sec=60.0),
            BeatSpec(index=2, text="Modern scans solved it.", visual_prompt="x-ray scan", start_sec=60.0, end_sec=135.0),
            BeatSpec(index=3, text="It changed tech history.", visual_prompt="museum", start_sec=135.0, end_sec=145.0),
        ],
    )
    enrich_story_metadata(plan, is_long=True)
    assert "Chapters:" in plan.description
    assert "00:00 -" in plan.description
    assert "#Shorts" not in plan.description
    assert clean_youtube_title(plan.title, is_long=True) == "Deep Dive Into Ancient Gears"

    tags = build_youtube_tags(
        title="Very Long Topic Title About Ancient Gears",
        category="history",
        script=" ".join(["astronomy mechanical bronze eclipse"] * 10),
        extra_tags=[f"extra tag number {i}" for i in range(25)],
        is_long=True,
    )
    total_tag_budget = sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)
    assert total_tag_budget <= 475
    assert len(tags) <= 15

    # Simulated uploader check for long-format watch URL
    dummy_mp4 = tmp_path / "long_job" / "final.mp4"
    dummy_mp4.parent.mkdir(parents=True)
    dummy_mp4.write_bytes(b"mp4")
    up = YouTubeUploader(mode="simulation")
    res = up.upload_short(
        video_path=dummy_mp4,
        title=plan.title,
        description=plan.description,
        tags=plan.tags,
        is_long=True,
    )
    assert res["url"].startswith("https://www.youtube.com/watch?v=")
    assert "#Shorts" not in res["title"]


def test_real_ffmpeg_landscape_render_and_qc(tmp_path):
    """Verify actual FFmpeg 16:9 render, ASS subtitle burn, loudnorm+alimiter, and QC pass."""
    import json
    import subprocess

    card = render_editorial_card(
        tmp_path / "b0.png",
        style=VisualStyle.EDITORIAL_DARK,
        headline="1920x1080 Landscape Test",
        body_text="Verifying automatic widescreen conversion and audio loudness gatekeeper.",
        width=1920,
        height=1080,
    )
    plan = StoryPlan(
        title="Landscape Render Test",
        hook="Testing widescreen output.",
        video_format=VideoFormat.LONG,
        target_width=1920,
        target_height=1080,
        beats=[
            BeatSpec(
                index=0,
                text="Testing widescreen output.",
                visual_prompt="test",
                resolved_image_path=str(card),
                start_sec=0.0,
                end_sec=4.0,
            ),
        ],
    )
    # Create a 4s spoken-like audio wave via ffmpeg sine/anoisesrc so ebur128 hits broadcast range
    narr = tmp_path / "narr.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=220:duration=4.0",
            "-ar", "44100", "-ac", "1", "-af", "volume=-16dB", str(narr),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    bgm = generate_ambient_underscore(4.0, tmp_path / "bgm.wav")
    words = [
        WordTiming(word="Testing", start_sec=0.1, end_sec=1.2),
        WordTiming(word="widescreen", start_sec=1.3, end_sec=2.5),
        WordTiming(word="output.", start_sec=2.6, end_sec=3.6),
    ]
    words_json = tmp_path / "words.json"
    words_json.write_text(json.dumps([w.model_dump() for w in words]), encoding="utf-8")

    out_mp4 = tmp_path / "final_16x9.mp4"
    render_short_video(
        plan=plan,
        narration_wav=narr,
        bgm_wav=bgm,
        words=words,
        work_dir=tmp_path,
        output_mp4=out_mp4,
    )
    qc = verify_video(
        out_mp4,
        words_json_path=words_json,
        min_duration_sec=3.0,
        expected_width=1920,
        expected_height=1080,
        video_format="long",
    )
    assert qc.passed, f"QC failed: {qc.issues} ({qc.checks})"
    assert qc.checks["resolution"] == "1920x1080"
    assert qc.checks["true_peak_db"] <= 0.0


def test_llm_failsafe_falls_back_from_gemini_to_local_ollama(tmp_path, monkeypatch):
    """When Gemini fails (429/error/offline), ZeroCostLLM falls back to local Ollama automatically."""
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-bad-key")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-bad-key")

    llm = ZeroCostLLM()
    calls = []

    def fake_gemini(sys_p, usr_p, temp, *, api_key=None):
        calls.append(("gemini", api_key))
        return None  # Simulate quota/429/network failure

    def fake_ollama(sys_p, usr_p, temp, *, model_name=None):
        calls.append(("ollama", model_name))
        return {"ok": True, "source": "local_ollama"}

    monkeypatch.setattr(llm, "_call_gemini", fake_gemini)
    monkeypatch.setattr(llm, "_list_ollama_models", lambda: ["qwen2.5:3b-instruct"])
    monkeypatch.setattr(llm, "_call_ollama", fake_ollama)

    res = llm.generate_json("sys", "user")
    assert res == {"ok": True, "source": "local_ollama"}
    assert calls[0] == ("gemini", "fake-bad-key")
    assert calls[1] == ("ollama", "qwen2.5:3b-instruct")


def test_youtube_7day_reauth_timer_states(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(config, "CLIENT_SECRET_PATH", tmp_path / "missing_secret.json")

    now = datetime.now(timezone.utc)
    for delta_hours, expected_state in [(10, "ok"), (140, "expiring_soon"), (180, "expired")]:
        ts = (now - timedelta(hours=delta_hours)).isoformat()
        monkeypatch.setenv("YOUTUBE_AUTH_TS", ts)
        monkeypatch.setattr(config, "YOUTUBE_AUTH_TS", ts)
        up = YouTubeUploader(client_id="cid", client_secret="csec", refresh_token="rtok")
        st = up.get_connection_status(verify_network=False)
        assert st["reauth_state"] == expected_state
        assert st["reauth_expires_at"] is not None
        if expected_state == "expired":
            assert st["reauth_remaining_seconds"] == 0
        else:
            assert st["reauth_remaining_seconds"] > 0
