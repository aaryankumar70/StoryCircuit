"""Tests for enhanced ASS captions and 1080x1920 editorial/scene cards."""
from __future__ import annotations

from PIL import Image

from reelforge.models import VisualStyle, WordTiming
from reelforge.video.captions import write_word_synced_ass
from reelforge.visuals.cards import (
    _split_headline_and_body,
    compose_scene_frame,
    render_editorial_card,
)


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
    # Secondary speaker switches accent color
    assert "&H00F8BD38" in txt


def test_editorial_card_and_scene_frame_dimensions(tmp_path):
    assert _split_headline_and_body("Soldiers stopped fighting", "Soldiers stopped fighting along the trenches.") == (
        "Soldiers stopped fighting",
        "along the trenches.",
    )

    for idx, style in enumerate(VisualStyle):
        card = render_editorial_card(
            tmp_path / f"card_{idx}.png",
            style=style,
            headline="The 1914 Christmas Truce",
            body_text="Over 100,000 troops laid down weapons along the Western Front.",
            stat_text="100K+" if idx % 2 == 0 else "",
            badge_text="history",
            seed_key=f"seed_{idx}",
        )
        with Image.open(card) as im:
            assert im.size == (1080, 1920)

    # Wide archival framing
    raw_wide = tmp_path / "wide.png"
    Image.new("RGB", (1200, 700), (40, 90, 140)).save(raw_wide)
    framed = compose_scene_frame(
        raw_wide,
        tmp_path / "framed.png",
        style=VisualStyle.EDITORIAL_DARK,
        badge_text="history",
        is_archival=True,
    )
    with Image.open(framed) as im:
        assert im.size == (1080, 1920)
