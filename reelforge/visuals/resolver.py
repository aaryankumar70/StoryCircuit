"""Zero-cost multi-source visual resolver for each StoryPlan beat."""
from __future__ import annotations

import hashlib
import logging
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import requests
from PIL import Image

from reelforge import config
from reelforge.models import BeatSpec, MediaPreference, StoryPlan, VideoFormat, get_style_prompt
from reelforge.visuals.cards import compose_scene_frame, render_editorial_card

logger = logging.getLogger("reelforge.visuals.resolver")

_HEADERS = {"User-Agent": "ReelForge/0.1 (zero-cost storyboard resolver)"}


def _validate_raster_image(path: Path, min_side: int = 360) -> bool:
    try:
        if not path.exists() or path.stat().st_size < 5_000:
            return False
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            w, h = rgb.size
            if w < min_side or h < min_side:
                return False
            arr = np.asarray(rgb.resize((64, 64)), dtype=np.float32)
            if float(np.std(arr)) < 10.0:
                return False
        return True
    except Exception:
        return False


def _fetch_pollinations_image(
    prompt: str,
    seed: int,
    raw_out: Path,
    *,
    width: int = 768,
    height: int = 1344,
) -> bool:
    encoded = urllib.parse.quote(prompt[:420], safe="")
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&model={urllib.parse.quote(config.POLLINATIONS_MODEL)}"
        f"&nologo=true&seed={seed}"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=config.POLLINATIONS_TIMEOUT_SEC)
        if resp.status_code != 200:
            logger.debug("Pollinations HTTP %s", resp.status_code)
            return False
        ctype = resp.headers.get("content-type", "").lower()
        if "image" not in ctype:
            return False
        raw_out.write_bytes(resp.content)
        return _validate_raster_image(raw_out)
    except Exception as exc:
        logger.debug("Pollinations fetch failed: %s", exc)
        return False


def _fetch_wikimedia_image(query: str, raw_out: Path) -> bool:
    if not query.strip():
        return False
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": "5",
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "iiurlwidth": "1200",
    }
    try:
        resp = requests.get("https://commons.wikimedia.org/w/api.php", params=params, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            return False
        pages = (resp.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = str(info.get("mime", "")).lower()
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            img_url = info.get("thumburl") or info.get("url")
            if not img_url:
                continue
            img_resp = requests.get(img_url, headers=_HEADERS, timeout=15)
            if img_resp.status_code == 200:
                raw_out.write_bytes(img_resp.content)
                if _validate_raster_image(raw_out):
                    return True
        return False
    except Exception as exc:
        logger.debug("Wikimedia lookup failed: %s", exc)
        return False


def _fetch_nasa_image(query: str, raw_out: Path) -> bool:
    if not query.strip():
        return False
    try:
        resp = requests.get(
            "https://images-api.nasa.gov/search",
            params={"q": query, "media_type": "image"},
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return False
        items = (resp.json().get("collection") or {}).get("items") or []
        for item in items[:4]:
            for link in item.get("links") or []:
                href = link.get("href")
                if href and href.lower().endswith((".jpg", ".jpeg", ".png")):
                    img_resp = requests.get(href, headers=_HEADERS, timeout=12)
                    if img_resp.status_code == 200:
                        raw_out.write_bytes(img_resp.content)
                        if _validate_raster_image(raw_out):
                            return True
        return False
    except Exception as exc:
        logger.debug("NASA lookup failed: %s", exc)
        return False


def resolve_beat_visual(
    plan: StoryPlan,
    beat: BeatSpec,
    visuals_dir: Path,
    visual_mode: Optional[str] = None,
    skip_pollinations: bool = False,
) -> Path:
    """Resolve and render a frame PNG (9:16 Short or 16:9 Landscape) for one beat, never failing."""
    visuals_dir.mkdir(parents=True, exist_ok=True)
    mode = (visual_mode or config.VISUAL_MODE).strip().lower()
    final_png = visuals_dir / f"beat_{beat.index:02d}.png"
    raw_img = visuals_dir / f"beat_{beat.index:02d}_raw.img"

    tw = plan.target_width
    th = plan.target_height
    is_long = (plan.video_format == VideoFormat.LONG) or (tw > th)
    gen_w, gen_h = (1344, 768) if is_long else (768, 1344)
    style_suffix = get_style_prompt(plan.style, VideoFormat.LONG if is_long else VideoFormat.SHORT)
    seed = int(hashlib.sha256(f"{plan.title}:{beat.index}:{beat.text}".encode("utf-8")).hexdigest()[:8], 16)

    if mode != "cards_only":
        # 1. Explicit graphic card beats render crisp editorial typography
        if beat.media_preference == MediaPreference.GRAPHIC_CARD:
            render_editorial_card(
                final_png,
                style=plan.style,
                headline=beat.callout_title or beat.text,
                body_text=beat.text,
                stat_text=beat.callout_stat,
                badge_text=plan.category,
                seed_key=f"{plan.title}:{beat.index}",
                width=tw,
                height=th,
            )
            beat.resolved_image_path = str(final_png)
            beat.resolved_source = "editorial_card"
            return final_png

        # 2. Archival lookup (Wikimedia / NASA) when preferred or in archival mode
        if beat.media_preference == MediaPreference.ARCHIVAL or mode == "archival":
            query = beat.archival_query or plan.title
            got_archival = (
                (_fetch_nasa_image(query, raw_img) if plan.category == "space" else False)
                or _fetch_wikimedia_image(query, raw_img)
            )
            if got_archival:
                compose_scene_frame(
                    raw_img,
                    final_png,
                    style=plan.style,
                    badge_text=plan.category,
                    stat_text=beat.callout_stat,
                    is_archival=True,
                    width=tw,
                    height=th,
                )
                beat.resolved_image_path = str(final_png)
                beat.resolved_source = "archival"
                return final_png

        # 3. Per-beat AI image matching exact beat dialogue
        if mode in ("auto", "pollinations"):
            if not skip_pollinations:
                full_prompt = f"{beat.visual_prompt}. {style_suffix}"
                if _fetch_pollinations_image(full_prompt, seed, raw_img, width=gen_w, height=gen_h):
                    compose_scene_frame(
                        raw_img,
                        final_png,
                        style=plan.style,
                        badge_text="" if beat.index > 0 else plan.category,
                        stat_text=beat.callout_stat,
                        is_archival=False,
                        width=tw,
                        height=th,
                    )
                    beat.resolved_image_path = str(final_png)
                    beat.resolved_source = "pollinations"
                    return final_png

            # Secondary fallback to Wikimedia archival before card fallback
            if _fetch_wikimedia_image(beat.archival_query or plan.title, raw_img):
                compose_scene_frame(
                    raw_img,
                    final_png,
                    style=plan.style,
                    badge_text=plan.category,
                    stat_text=beat.callout_stat,
                    is_archival=True,
                    width=tw,
                    height=th,
                )
                beat.resolved_image_path = str(final_png)
                beat.resolved_source = "archival_fallback"
                return final_png

    # 4. Guaranteed offline procedural card fallback
    render_editorial_card(
        final_png,
        style=plan.style,
        headline=beat.callout_title or " ".join(beat.text.split()[:6]),
        body_text=beat.text,
        stat_text=beat.callout_stat,
        badge_text=plan.category,
        seed_key=f"{plan.title}:{beat.index}",
        width=tw,
        height=th,
    )
    beat.resolved_image_path = str(final_png)
    beat.resolved_source = "editorial_card_fallback"
    return final_png


def resolve_all_visuals(
    plan: StoryPlan,
    work_dir: Path,
    visual_mode: Optional[str] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    visuals_dir = work_dir / "visuals"
    total = len(plan.beats)
    consecutive_pollinations_misses = 0
    for idx, beat in enumerate(plan.beats, start=1):
        skip_poll = consecutive_pollinations_misses >= 2
        resolve_beat_visual(plan, beat, visuals_dir, visual_mode=visual_mode, skip_pollinations=skip_poll)
        if beat.resolved_source == "pollinations":
            consecutive_pollinations_misses = 0
        elif not skip_poll and beat.media_preference == MediaPreference.AI_IMAGE:
            consecutive_pollinations_misses += 1
        if on_progress:
            on_progress(idx, total, beat.resolved_source or "resolved")
