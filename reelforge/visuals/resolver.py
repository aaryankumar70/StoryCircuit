"""100% Real-Media visual resolver: Pixabay HD B-Roll, Pollinations/HF AI Art, NASA/Wikimedia Archival."""
from __future__ import annotations

import hashlib
import logging
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Optional, Set

import numpy as np
import requests
from PIL import Image

from reelforge import config
from reelforge.models import BeatSpec, MediaPreference, StoryPlan, VideoFormat, get_style_prompt

logger = logging.getLogger("reelforge.visuals.resolver")

_HEADERS = {"User-Agent": "ReelForge/0.4 (StoryCircuit pure-media resolver)"}


def _validate_raster_image(path: Path, min_side: int = 360) -> Optional[str]:
    """Validate raster image integrity, size, non-flat variance, and return SHA-256 hash."""
    try:
        if not path.exists() or path.stat().st_size < 5_000:
            return None
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            w, h = rgb.size
            if w < min_side or h < min_side:
                return None
            arr = np.asarray(rgb.resize((64, 64)), dtype=np.float32)
            if float(np.std(arr)) < 10.0:
                return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _validate_video_clip(path: Path, width: int = 1080, height: int = 1920) -> bool:
    """Confirm downloaded MP4 B-roll has a valid stream and no black frames after target aspect crop."""
    try:
        if not path.exists() or path.stat().st_size < 40_000:
            return False
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if res.returncode != 0 or "," not in (res.stdout or ""):
            return False
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"blackdetect=d=0.6:pix_th=0.14"
        )
        bd = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(path), "-t", "12", "-vf", vf, "-an", "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if "black_duration:" in (bd.stderr or ""):
            return False
        return True
    except Exception:
        return False


def _fetch_pexels_video(query: str, out_mp4: Path, *, is_long: bool, width: int = 1080, height: int = 1920, seen_urls: Optional[Set[str]] = None) -> bool:
    if not config.PEXELS_API_KEY or not query.strip():
        return False
    orientation = "landscape" if is_long else "portrait"
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": orientation, "per_page": 6, "size": "medium"},
            headers={**_HEADERS, "Authorization": config.PEXELS_API_KEY},
            timeout=15,
        )
        if resp.status_code != 200:
            return False
        for vid in resp.json().get("videos") or []:
            vid_key = f"pexels_vid:{vid.get('id')}"
            if seen_urls is not None and vid_key in seen_urls:
                continue
            files = sorted(
                (f for f in (vid.get("video_files") or []) if str(f.get("file_type", "")).endswith("mp4")),
                key=lambda f: abs(int(f.get("width") or 0) - (1920 if is_long else 1080)),
            )
            for vf in files:
                link = vf.get("link")
                if not link:
                    continue
                dl = requests.get(link, headers=_HEADERS, timeout=45)
                if dl.status_code == 200:
                    out_mp4.write_bytes(dl.content)
                    if _validate_video_clip(out_mp4, width=width, height=height):
                        if seen_urls is not None:
                            seen_urls.add(vid_key)
                        return True
        return False
    except Exception as exc:
        logger.debug("Pexels video lookup failed: %s", exc)
        return False


_BANNED_PIXABAY_TAGS = (
    "green screen", "chroma", "subscribe", "like button", "thumbs up",
    "icon", "button", "animation", "intro", "outro", "overlay", "alpha", "emoji",
)


def _fetch_pixabay_video(query: str, out_mp4: Path, *, width: int = 1080, height: int = 1920, seen_urls: Optional[Set[str]] = None) -> bool:
    if not config.PIXABAY_API_KEY or not query.strip():
        return False
    try:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": config.PIXABAY_API_KEY, "q": query, "video_type": "film", "per_page": 8},
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return False
        for hit in resp.json().get("hits") or []:
            tags_lower = str(hit.get("tags") or "").lower()
            if any(bad in tags_lower for bad in _BANNED_PIXABAY_TAGS):
                continue
            vid_key = f"pixabay_vid:{hit.get('id')}"
            if seen_urls is not None and vid_key in seen_urls:
                continue
            vids = hit.get("videos") or {}
            cand = vids.get("medium") or vids.get("large") or vids.get("small") or {}
            link = cand.get("url")
            if not link:
                continue
            dl = requests.get(link, headers=_HEADERS, timeout=45)
            if dl.status_code == 200:
                out_mp4.write_bytes(dl.content)
                if _validate_video_clip(out_mp4, width=width, height=height):
                    if seen_urls is not None:
                        seen_urls.add(vid_key)
                    return True
        return False
    except Exception as exc:
        logger.debug("Pixabay video lookup failed: %s", exc)
        return False


def _fetch_pixabay_photo(
    query: str,
    raw_out: Path,
    *,
    is_long: bool,
    seen_urls: Optional[Set[str]] = None,
    seen_hashes: Optional[Set[str]] = None,
) -> bool:
    if not config.PIXABAY_API_KEY or not query.strip():
        return False
    orientation = "horizontal" if is_long else "vertical"
    try:
        resp = requests.get(
            "https://pixabay.com/api/",
            params={"key": config.PIXABAY_API_KEY, "q": query, "orientation": orientation, "image_type": "photo", "per_page": 6},
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return False
        for hit in resp.json().get("hits") or []:
            purl = hit.get("largeImageURL") or hit.get("webformatURL")
            if not purl or (seen_urls is not None and purl in seen_urls):
                continue
            dl = requests.get(purl, headers=_HEADERS, timeout=20)
            if dl.status_code == 200:
                raw_out.write_bytes(dl.content)
                digest = _validate_raster_image(raw_out)
                if not digest or (seen_hashes is not None and digest in seen_hashes):
                    continue
                if seen_urls is not None:
                    seen_urls.add(purl)
                if seen_hashes is not None:
                    seen_hashes.add(digest)
                return True
        return False
    except Exception as exc:
        logger.debug("Pixabay photo lookup failed: %s", exc)
        return False


def _fetch_nasa_video(query: str, out_mp4: Path, *, width: int = 1080, height: int = 1920, seen_urls: Optional[Set[str]] = None) -> bool:
    if not query.strip():
        return False
    try:
        resp = requests.get(
            "https://images-api.nasa.gov/search",
            params={"q": query, "media_type": "video"},
            headers=_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return False
        items = (resp.json().get("collection") or {}).get("items") or []
        for item in items[:5]:
            col_url = item.get("href")
            if not col_url or (seen_urls is not None and col_url in seen_urls):
                continue
            col_resp = requests.get(col_url, headers=_HEADERS, timeout=10)
            if col_resp.status_code != 200:
                continue
            assets = [str(u) for u in (col_resp.json() or []) if str(u).lower().endswith(".mp4")]
            preferred = sorted(
                assets,
                key=lambda u: 0 if "~medium.mp4" in u else (1 if "~small.mp4" in u else (2 if "~large.mp4" in u else 3)),
            )
            for mp4_url in preferred[:2]:
                dl = requests.get(mp4_url, headers=_HEADERS, timeout=35)
                if dl.status_code == 200 and len(dl.content) < 45_000_000:
                    out_mp4.write_bytes(dl.content)
                    if _validate_video_clip(out_mp4, width=width, height=height):
                        if seen_urls is not None:
                            seen_urls.add(col_url)
                        return True
        return False
    except Exception as exc:
        logger.debug("NASA video lookup failed: %s", exc)
        return False


def _fetch_pexels_photo(
    query: str,
    raw_out: Path,
    *,
    is_long: bool,
    seen_urls: Optional[Set[str]] = None,
    seen_hashes: Optional[Set[str]] = None,
) -> bool:
    if not config.PEXELS_API_KEY or not query.strip():
        return False
    orientation = "landscape" if is_long else "portrait"
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": orientation, "per_page": 6},
            headers={**_HEADERS, "Authorization": config.PEXELS_API_KEY},
            timeout=15,
        )
        if resp.status_code != 200:
            return False
        for photo in resp.json().get("photos") or []:
            purl = (photo.get("src") or {}).get("large2x") or (photo.get("src") or {}).get("large")
            if not purl or (seen_urls is not None and purl in seen_urls):
                continue
            dl = requests.get(purl, headers=_HEADERS, timeout=20)
            if dl.status_code == 200:
                raw_out.write_bytes(dl.content)
                digest = _validate_raster_image(raw_out)
                if not digest or (seen_hashes is not None and digest in seen_hashes):
                    continue
                if seen_urls is not None:
                    seen_urls.add(purl)
                if seen_hashes is not None:
                    seen_hashes.add(digest)
                return True
        return False
    except Exception as exc:
        logger.debug("Pexels photo lookup failed: %s", exc)
        return False


def _fetch_huggingface_image(
    prompt: str,
    raw_out: Path,
    *,
    width: int,
    height: int,
    seen_hashes: Optional[Set[str]] = None,
) -> bool:
    if not config.HF_API_TOKEN:
        return False
    url = f"https://router.huggingface.co/hf-inference/models/{config.HF_IMAGE_MODEL}"
    headers = {**_HEADERS, "Authorization": f"Bearer {config.HF_API_TOKEN}"}
    payload = {"inputs": prompt[:450], "parameters": {"width": width, "height": height}}
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < 2:
                time.sleep(8.0 * (attempt + 1))
                continue
            if resp.status_code != 200 or "image" not in resp.headers.get("content-type", "").lower():
                return False
            raw_out.write_bytes(resp.content)
            digest = _validate_raster_image(raw_out)
            if not digest or (seen_hashes is not None and digest in seen_hashes):
                return False
            if seen_hashes is not None:
                seen_hashes.add(digest)
            return True
        except Exception as exc:
            logger.debug("HF image fetch failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(4.0)
    return False


def _fetch_pollinations_image(
    prompt: str,
    seed: int,
    raw_out: Path,
    *,
    width: int = 768,
    height: int = 1344,
    seen_hashes: Optional[Set[str]] = None,
) -> bool:
    encoded = urllib.parse.quote(prompt[:420], safe="")
    models = [config.POLLINATIONS_MODEL or "flux", "zimage"] if config.POLLINATIONS_API_KEY else [config.POLLINATIONS_MODEL or "flux"]

    for model_name in list(dict.fromkeys(models)):
        headers = dict(_HEADERS)
        if config.POLLINATIONS_API_KEY:
            url = (
                f"https://gen.pollinations.ai/image/{encoded}"
                f"?width={width}&height={height}&model={urllib.parse.quote(model_name)}"
                f"&nologo=true&seed={seed}"
            )
            headers["Authorization"] = f"Bearer {config.POLLINATIONS_API_KEY}"
        else:
            url = (
                f"https://image.pollinations.ai/prompt/{encoded}"
                f"?width={width}&height={height}&model={urllib.parse.quote(model_name)}"
                f"&nologo=true&seed={seed}"
            )

        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, timeout=max(65, config.POLLINATIONS_TIMEOUT_SEC))
                if (resp.status_code == 429 or resp.status_code >= 500) and attempt < 2:
                    time.sleep(10.0 * (attempt + 1))
                    continue
                if resp.status_code != 200 or "image" not in resp.headers.get("content-type", "").lower():
                    logger.debug("Pollinations (%s) HTTP %s", model_name, resp.status_code)
                    break
                raw_out.write_bytes(resp.content)
                digest = _validate_raster_image(raw_out)
                if not digest or (seen_hashes is not None and digest in seen_hashes):
                    break
                if seen_hashes is not None:
                    seen_hashes.add(digest)
                return True
            except Exception as exc:
                logger.debug("Pollinations (%s) fetch failed (attempt %d): %s", model_name, attempt + 1, exc)
                if attempt < 2:
                    time.sleep(6.0)
    return False


def _fetch_wikimedia_image(
    query: str,
    raw_out: Path,
    *,
    seen_urls: Optional[Set[str]] = None,
    seen_hashes: Optional[Set[str]] = None,
) -> bool:
    if not query.strip():
        return False
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": "8",
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
            if not img_url or (seen_urls is not None and img_url in seen_urls):
                continue
            img_resp = requests.get(img_url, headers=_HEADERS, timeout=15)
            if img_resp.status_code == 200:
                raw_out.write_bytes(img_resp.content)
                digest = _validate_raster_image(raw_out)
                if not digest or (seen_hashes is not None and digest in seen_hashes):
                    continue
                if seen_urls is not None:
                    seen_urls.add(img_url)
                if seen_hashes is not None:
                    seen_hashes.add(digest)
                return True
        return False
    except Exception as exc:
        logger.debug("Wikimedia lookup failed: %s", exc)
        return False


def _fetch_nasa_image(
    query: str,
    raw_out: Path,
    *,
    seen_urls: Optional[Set[str]] = None,
    seen_hashes: Optional[Set[str]] = None,
) -> bool:
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
        for item in items[:6]:
            for link in item.get("links") or []:
                href = link.get("href")
                if not href or not href.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                if seen_urls is not None and href in seen_urls:
                    continue
                img_resp = requests.get(href, headers=_HEADERS, timeout=12)
                if img_resp.status_code == 200:
                    raw_out.write_bytes(img_resp.content)
                    digest = _validate_raster_image(raw_out)
                    if not digest or (seen_hashes is not None and digest in seen_hashes):
                        continue
                    if seen_urls is not None:
                        seen_urls.add(href)
                    if seen_hashes is not None:
                        seen_hashes.add(digest)
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
    *,
    skip_pollinations: bool = False,
    seen_urls: Optional[Set[str]] = None,
    seen_hashes: Optional[Set[str]] = None,
) -> str:
    """Resolve real visual media for every beat (HD stock video, custom AI art, or unique archival photo)."""
    visuals_dir.mkdir(parents=True, exist_ok=True)
    mode = (visual_mode or config.VISUAL_MODE or "hybrid").strip().lower()
    raw_img = visuals_dir / f"beat_{beat.index:02d}_media.img"
    raw_vid = visuals_dir / f"beat_{beat.index:02d}_broll.mp4"

    beat.resolved_image_path = None
    beat.resolved_video_path = None

    tw = plan.target_width
    th = plan.target_height
    is_long = (plan.video_format == VideoFormat.LONG) or (tw > th)
    gen_w, gen_h = (1280, 720) if is_long else (768, 1344)
    style_suffix = get_style_prompt(plan.style, VideoFormat.LONG if is_long else VideoFormat.SHORT)
    seed = int(hashlib.sha256(f"{plan.title}:{beat.index}:{beat.text}".encode("utf-8")).hexdigest()[:8], 16)
    broll_q = (beat.broll_query or beat.archival_query or plan.title).strip()
    arch_q = (beat.archival_query or beat.broll_query or f"{plan.title} {beat.index}").strip()
    full_prompt = f"{beat.visual_prompt}. {style_suffix}"

    def _try_broll() -> Optional[str]:
        got_vid = (
            _fetch_pexels_video(broll_q, raw_vid, is_long=is_long, width=tw, height=th, seen_urls=seen_urls)
            or _fetch_pixabay_video(broll_q, raw_vid, width=tw, height=th, seen_urls=seen_urls)
            or (_fetch_nasa_video(broll_q, raw_vid, width=tw, height=th, seen_urls=seen_urls) if plan.category in ("space", "science", "tech") else False)
        )
        if got_vid:
            beat.resolved_video_path = str(raw_vid)
            beat.resolved_source = "broll_video"
            return "broll_video"
        if _fetch_pexels_photo(broll_q, raw_img, is_long=is_long, seen_urls=seen_urls, seen_hashes=seen_hashes) or _fetch_pixabay_photo(
            broll_q, raw_img, is_long=is_long, seen_urls=seen_urls, seen_hashes=seen_hashes
        ):
            beat.resolved_image_path = str(raw_img)
            beat.resolved_source = "broll_photo"
            return "broll_photo"
        return None

    def _try_ai() -> Optional[str]:
        if _fetch_huggingface_image(full_prompt, raw_img, width=gen_w, height=gen_h, seen_hashes=seen_hashes):
            beat.resolved_image_path = str(raw_img)
            beat.resolved_source = "hf_ai_image"
            return "hf_ai_image"
        if not skip_pollinations and _fetch_pollinations_image(
            full_prompt, seed, raw_img, width=gen_w, height=gen_h, seen_hashes=seen_hashes
        ):
            beat.resolved_image_path = str(raw_img)
            beat.resolved_source = "pollinations"
            return "pollinations"
        return None

    def _try_archival() -> Optional[str]:
        if (plan.category == "space" and _fetch_nasa_image(arch_q, raw_img, seen_urls=seen_urls, seen_hashes=seen_hashes)) or _fetch_wikimedia_image(
            arch_q, raw_img, seen_urls=seen_urls, seen_hashes=seen_hashes
        ):
            beat.resolved_image_path = str(raw_img)
            beat.resolved_source = "archival"
            return "archival"
        return None

    # Order resolution chain by requested mode & per-beat preference so 100% of beats get real media
    if mode == "broll":
        order = (_try_broll, _try_ai, _try_archival)
    elif mode == "archival":
        order = (_try_archival, _try_broll, _try_ai)
    elif mode in ("pollinations", "ai_only"):
        order = (_try_ai, _try_broll, _try_archival)
    else:
        if beat.media_preference == MediaPreference.BROLL_VIDEO:
            order = (_try_broll, _try_ai, _try_archival)
        elif beat.media_preference == MediaPreference.ARCHIVAL:
            order = (_try_archival, _try_ai, _try_broll)
        else:
            order = (_try_ai, _try_broll, _try_archival)

    for fn in order:
        res = fn()
        if res:
            return res

    # Final graceful fallback if completely offline: host presenter over minimal styled backdrop
    raw_img.unlink(missing_ok=True)
    raw_vid.unlink(missing_ok=True)
    beat.resolved_source = "host_fallback"
    return "host_fallback"


def resolve_all_visuals(
    plan: StoryPlan,
    work_dir: Path,
    visual_mode: Optional[str] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    visuals_dir = work_dir / "visuals"
    total = len(plan.beats)
    seen_urls: Set[str] = set()
    seen_hashes: Set[str] = set()
    consecutive_pollinations_misses = 0

    for idx, beat in enumerate(plan.beats, start=1):
        skip_poll = (not config.POLLINATIONS_API_KEY) and (consecutive_pollinations_misses >= 2)
        src = resolve_beat_visual(
            plan,
            beat,
            visuals_dir,
            visual_mode=visual_mode,
            skip_pollinations=skip_poll,
            seen_urls=seen_urls,
            seen_hashes=seen_hashes,
        )
        if src == "pollinations":
            consecutive_pollinations_misses = 0
            if config.POLLINATIONS_API_KEY and config.AI_IMAGE_PACING_SEC > 0 and idx < total:
                time.sleep(min(15.0, config.AI_IMAGE_PACING_SEC))
        elif src == "hf_ai_image":
            if config.AI_IMAGE_PACING_SEC > 0 and idx < total:
                time.sleep(min(10.0, config.AI_IMAGE_PACING_SEC * 0.5))
        elif not skip_poll and beat.media_preference == MediaPreference.AI_IMAGE:
            consecutive_pollinations_misses += 1

        if on_progress:
            on_progress(idx, total, beat.resolved_source or "resolved")
