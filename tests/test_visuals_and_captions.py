"""Tests for enhanced ASS captions, illustrated host sprites, Ken Burns media, B-roll overlay, and deduplicated resolver."""
from __future__ import annotations

import hashlib
import json
import subprocess
import numpy as np
from PIL import Image

from reelforge.audio.underscore import generate_ambient_underscore
from reelforge.models import (
    BeatSpec,
    CharacterSpec,
    MediaPreference,
    StoryPlan,
    VideoFormat,
    VisualStyle,
    WordTiming,
)
from reelforge.qc.gatekeeper import verify_video
from reelforge.video.captions import write_word_synced_ass
from reelforge.video.renderer import render_short_video
from reelforge.visuals import resolver as visual_resolver
from reelforge.visuals.scene2d import render_2d_beat_preview


def test_word_synced_ass_generates_animated_dialogue(tmp_path):
    words = [
        WordTiming(word="In", start_sec=0.0, end_sec=0.2, speaker="primary"),
        WordTiming(word="1914", start_sec=0.2, end_sec=0.6, speaker="primary"),
        WordTiming(word="soldiers", start_sec=0.6, end_sec=1.0, speaker="primary"),
        WordTiming(word="paused.", start_sec=1.05, end_sec=1.4, speaker="secondary"),
    ]
    ass_path = write_word_synced_ass(words, tmp_path / "captions.ass", style=VisualStyle.GRAPHIC_NOIR)
    txt = ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in txt
    assert "PlayResY: 1920" in txt
    assert "Dialogue: 0," in txt
    assert "\\fscx115\\fscy115" in txt
    assert "&H00F8BD38" in txt


def test_illustrated_host_presenter_and_cameo_previews(tmp_path):
    bg_img = tmp_path / "scene.png"
    arr_ex = np.zeros((1344, 768, 3), dtype=np.uint8)
    arr_ex[:672, :] = (24, 62, 118)
    arr_ex[672:, :] = (165, 78, 38)
    Image.fromarray(arr_ex).save(bg_img)

    plan = StoryPlan(
        title="The 1914 Christmas Truce",
        hook="In December 1914 soldiers stopped fighting.",
        category="history",
        style=VisualStyle.GRAPHIC_NOIR,
        video_format=VideoFormat.SHORT,
        target_width=1080,
        target_height=1920,
        beats=[
            BeatSpec(
                index=0,
                speaker="primary",
                text="In December 1914 soldiers stepped out of the trenches.",
                visual_prompt="soldiers meeting in snowy no-mans-land",
                media_preference=MediaPreference.AI_IMAGE,
                host_appearance="presenter",
                characters=[CharacterSpec(name="Atlas", pose="pointing")],
                callout_stat="1914",
                callout_title="WESTERN FRONT",
                resolved_image_path=str(bg_img),
                start_sec=0.0,
                end_sec=3.0,
            ),
            BeatSpec(
                index=1,
                speaker="secondary",
                text="Archival evidence captured the moment.",
                visual_prompt="archival truce photo",
                media_preference=MediaPreference.ARCHIVAL,
                host_appearance="cameo",
                characters=[CharacterSpec(name="Atlas", pose="shocked")],
                resolved_image_path=str(bg_img),
                start_sec=3.0,
                end_sec=6.0,
            ),
        ],
    )
    words = [WordTiming(word="soldiers", start_sec=0.8, end_sec=1.8, speaker="primary")]

    out0 = render_2d_beat_preview(plan, tmp_path / "beat0.png", beat_index=0, words=words, work_dir=tmp_path)
    out1 = render_2d_beat_preview(plan, tmp_path / "beat1.png", beat_index=1, words=words, work_dir=tmp_path)

    for p in (out0, out1):
        with Image.open(p) as im:
            assert im.size == (1080, 1920)
            arr = np.asarray(im, dtype=np.float32)
            assert float(np.std(arr)) > 15.0


def test_resolver_deduplicates_and_chains_media_fallbacks(tmp_path, monkeypatch):
    sample_img = tmp_path / "sample.png"
    arr = np.zeros((420, 420, 3), dtype=np.uint8)
    arr[:, :210] = (30, 120, 210)
    arr[:, 210:] = (220, 90, 40)
    Image.fromarray(arr).save(sample_img)
    sample_bytes = sample_img.read_bytes()

    def fake_wiki(query: str, raw_out, *, seen_urls=None, seen_hashes=None):
        digest = hashlib.sha256(sample_bytes).hexdigest()
        if seen_hashes is not None and digest in seen_hashes:
            return False
        raw_out.write_bytes(sample_bytes)
        if seen_hashes is not None:
            seen_hashes.add(digest)
        return True

    monkeypatch.setattr(visual_resolver, "_fetch_wikimedia_image", fake_wiki)
    monkeypatch.setattr(visual_resolver, "_fetch_huggingface_image", lambda *a, **k: False)
    monkeypatch.setattr(visual_resolver, "_fetch_pollinations_image", lambda *a, **k: False)
    monkeypatch.setattr(visual_resolver, "_fetch_pexels_video", lambda *a, **k: False)
    monkeypatch.setattr(visual_resolver, "_fetch_pixabay_video", lambda *a, **k: False)
    monkeypatch.setattr(visual_resolver, "_fetch_pexels_photo", lambda *a, **k: False)
    monkeypatch.setattr(visual_resolver, "_fetch_pixabay_photo", lambda *a, **k: False)

    plan = StoryPlan(
        title="Deduplication Test",
        hook="Testing deduplicated visuals.",
        beats=[
            BeatSpec(index=0, text="First beat.", visual_prompt="scene 0", archival_query="query one", media_preference=MediaPreference.ARCHIVAL),
            BeatSpec(index=1, text="Second beat.", visual_prompt="scene 1", archival_query="query two", media_preference=MediaPreference.ARCHIVAL),
        ],
    )
    visual_resolver.resolve_all_visuals(plan, tmp_path, visual_mode="hybrid")

    assert plan.beats[0].resolved_source == "archival"
    assert plan.beats[0].resolved_image_path is not None
    assert plan.beats[1].resolved_source == "host_fallback"
    assert plan.beats[1].resolved_image_path is None


def test_hybrid_broll_video_plus_illustrated_host_render_and_qc(tmp_path):
    """Verify full-bleed AI/photo Ken Burns + HD B-roll MP4 + transparent Host Sprite overlay pass QC."""
    broll_src = tmp_path / "sample_broll.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "testsrc2=size=720x1280:rate=30:duration=2.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(broll_src),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    ai_img = tmp_path / "ai_scene.png"
    arr = np.zeros((1344, 768, 3), dtype=np.uint8)
    arr[:672, :] = (22, 65, 110)
    arr[672:, :] = (170, 80, 40)
    Image.fromarray(arr).save(ai_img)

    plan = StoryPlan(
        title="Hybrid Pure-Media Test",
        hook="Testing real media plus illustrated host.",
        category="science",
        style=VisualStyle.EDITORIAL_DARK,
        video_format=VideoFormat.SHORT,
        target_width=1080,
        target_height=1920,
        beats=[
            BeatSpec(
                index=0,
                speaker="primary",
                text="Testing AI scene with presenter.",
                visual_prompt="deep borehole illustration",
                media_preference=MediaPreference.AI_IMAGE,
                host_appearance="presenter",
                characters=[CharacterSpec(name="Atlas", pose="pointing")],
                callout_stat="12,262M",
                callout_title="KOLA DEPTH",
                resolved_image_path=str(ai_img),
                start_sec=0.0,
                end_sec=2.0,
            ),
            BeatSpec(
                index=1,
                speaker="primary",
                text="Testing video b-roll cameo.",
                visual_prompt="broll clip",
                media_preference=MediaPreference.BROLL_VIDEO,
                host_appearance="cameo",
                characters=[CharacterSpec(name="Atlas", pose="shocked")],
                resolved_video_path=str(broll_src),
                start_sec=2.0,
                end_sec=4.0,
            ),
        ],
    )
    narr = tmp_path / "narr.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=4.0", "-ar", "44100", "-ac", "1", "-af", "volume=-16dB", str(narr)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    bgm = generate_ambient_underscore(4.0, tmp_path / "bgm.wav", beat_cut_times=[2.0])
    words = [
        WordTiming(word="Testing", start_sec=0.1, end_sec=1.0, speaker="primary"),
        WordTiming(word="real", start_sec=1.1, end_sec=1.9, speaker="primary"),
        WordTiming(word="media", start_sec=2.1, end_sec=3.5, speaker="primary"),
    ]
    words_json = tmp_path / "words.json"
    words_json.write_text(json.dumps([w.model_dump() for w in words]), encoding="utf-8")

    out_mp4 = tmp_path / "hybrid_9x16.mp4"
    render_short_video(plan=plan, narration_wav=narr, bgm_wav=bgm, words=words, work_dir=tmp_path, output_mp4=out_mp4, duration_sec=4.0)

    qc = verify_video(out_mp4, words_json_path=words_json, min_duration_sec=3.0, expected_width=1080, expected_height=1920, video_format="short")
    assert qc.passed, f"Hybrid pure-media QC failed: {qc.issues} ({qc.checks})"
    assert qc.checks["resolution"] == "1080x1920"
