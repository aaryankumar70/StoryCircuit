"""Pure-Python 1080x1920 editorial cards and image framing compositor."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from reelforge.config import VIDEO_HEIGHT, VIDEO_WIDTH
from reelforge.models import VisualStyle

_FONTS_BLACK = (
    "/usr/share/fonts/noto/NotoSans-Black.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
)
_FONTS_SERIF_BLACK = (
    "/usr/share/fonts/noto/NotoSerif-Black.ttf",
    "/usr/share/fonts/noto/NotoSerif-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSerif-Bold.ttf",
)
_FONTS_SANS_BOLD = (
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
)
_FONTS_SANS_MED = (
    "/usr/share/fonts/noto/NotoSans-Medium.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
)
_FONTS_MONO_BOLD = (
    "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationMono-Bold.ttf",
)

STYLE_PALETTES: Dict[str, Dict[str, Tuple[int, int, int]]] = {
    VisualStyle.EDITORIAL_DARK.value: {
        "bg1": (11, 15, 23),
        "bg2": (23, 32, 51),
        "accent": (34, 211, 238),
        "accent2": (245, 158, 11),
        "text": (244, 247, 252),
        "muted": (164, 178, 200),
        "panel": (17, 24, 39),
    },
    VisualStyle.VINTAGE_ARCHIVAL.value: {
        "bg1": (26, 20, 16),
        "bg2": (48, 37, 28),
        "accent": (214, 158, 92),
        "accent2": (242, 210, 158),
        "text": (246, 238, 224),
        "muted": (192, 176, 154),
        "panel": (36, 28, 22),
    },
    VisualStyle.GRAPHIC_NOIR.value: {
        "bg1": (13, 13, 18),
        "bg2": (34, 17, 26),
        "accent": (244, 63, 94),
        "accent2": (56, 189, 248),
        "text": (248, 248, 250),
        "muted": (178, 176, 190),
        "panel": (22, 18, 25),
    },
    VisualStyle.CINEMATIC_PAINTERLY.value: {
        "bg1": (12, 22, 33),
        "bg2": (22, 44, 60),
        "accent": (72, 202, 228),
        "accent2": (251, 191, 36),
        "text": (242, 248, 252),
        "muted": (162, 190, 208),
        "panel": (18, 34, 46),
    },
    VisualStyle.BLUEPRINT_TECH.value: {
        "bg1": (9, 18, 34),
        "bg2": (16, 36, 66),
        "accent": (56, 189, 248),
        "accent2": (52, 211, 153),
        "text": (238, 247, 255),
        "muted": (152, 188, 222),
        "panel": (13, 26, 48),
    },
}


def _load_font(candidates: Sequence[str] | str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [candidates] if isinstance(candidates, str) else list(candidates)
    for path in paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text_px(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> List[str]:
    """Wrap text accurately using rendered pixel width."""
    words = (text or "").strip().split()
    if not words:
        return []
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        bbox = draw.textbbox((0, 0), trial, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _vertical_gradient(w: int, h: int, c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> Image.Image:
    base = Image.new("RGB", (w, h), c1)
    draw = ImageDraw.Draw(base)
    for y in range(0, h, 4):
        t = y / max(1, h - 1)
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.rectangle([0, y, w, min(h, y + 4)], fill=(r, g, b))
    return base


def _add_radial_glow(
    img: Image.Image,
    center: Tuple[int, int],
    radius: int,
    color: Tuple[int, int, int],
    alpha: int = 75,
) -> Image.Image:
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx, cy = center
    gdraw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*color, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(30, radius // 3)))
    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


def _add_vignette(img: Image.Image) -> Image.Image:
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Stronger gradient behind bottom caption safe zone
    bottom_start = 0.68 if w > h else 0.52
    bottom_span = 1.0 - bottom_start
    for i in range(72):
        alpha = int((155 if w > h else 175) * ((i / 72.0) ** 1.15))
        y = int(h * bottom_start + (h * bottom_span) * (i / 72.0))
        step_h = max(8, int(h * bottom_span / 68) + 2)
        draw.rectangle([0, y, w, min(h, y + step_h)], fill=(6, 8, 13, alpha))
    for i in range(24):
        alpha = int(115 * (1.0 - i / 24.0))
        y = int(i * max(6, h // 160))
        draw.rectangle([0, y, w, y + max(6, h // 160)], fill=(6, 8, 13, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _rounded_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle([0, 0, size[0], size[1]], radius=radius, fill=255)
    return mask


def _draw_shadow_rounded_box(
    img: Image.Image,
    box: Tuple[int, int, int, int],
    radius: int,
    fill: Tuple[int, int, int],
    outline: Tuple[int, int, int],
    width: int = 3,
) -> Image.Image:
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle([x1 + 4, y1 + 14, x2 + 4, y2 + 22], radius=radius, fill=(0, 0, 0, 155))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
    out = Image.alpha_composite(img.convert("RGBA"), shadow)
    pdraw = ImageDraw.Draw(out)
    pdraw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=(*fill, 238), outline=(*outline, 220), width=width)
    return out.convert("RGB")


def _draw_top_pill(
    img: Image.Image,
    text: str,
    *,
    pal: Dict[str, Tuple[int, int, int]],
    is_stat: bool = False,
) -> Image.Image:
    label = (text or "").strip().upper()[:30]
    if not label:
        return img
    w, h = img.size
    is_landscape = w > h
    font = _load_font(_FONTS_MONO_BOLD, (34 if is_landscape else 38) if is_stat else (26 if is_landscape else 28))
    rgba = img.convert("RGBA")
    tmp_draw = ImageDraw.Draw(rgba)
    bbox = tmp_draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    dot_space = 26 if not is_stat else 0
    pw = tw + 48 + dot_space
    ph = th + 26
    x1, y1 = (54, 44) if is_landscape else (60, 136)
    x2, y2 = x1 + pw, y1 + ph

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x1 + 2, y1 + 6, x2 + 2, y2 + 10], radius=14, fill=(0, 0, 0, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    rgba = Image.alpha_composite(rgba, shadow)
    draw = ImageDraw.Draw(rgba)
    draw.rounded_rectangle([x1, y1, x2, y2], radius=14, fill=(*pal["panel"], 225), outline=(*pal["accent"], 230), width=2)
    tx = x1 + 24
    if not is_stat:
        cy = (y1 + y2) // 2
        draw.ellipse([x1 + 20, cy - 6, x1 + 32, cy + 6], fill=pal["accent"])
        tx += 24
    draw.text((tx, y1 + (ph - th) // 2 - bbox[1]), label, font=font, fill=pal["accent"] if is_stat else pal["text"])
    return rgba.convert("RGB")


def compose_scene_frame(
    src_image_path: Path,
    out_path: Path,
    *,
    style: VisualStyle,
    badge_text: str = "",
    stat_text: str = "",
    is_archival: bool = False,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> Path:
    """Frame any raster image cleanly into target dimensions (9:16 or 16:9) with style cohesion."""
    pal = STYLE_PALETTES.get(style.value, STYLE_PALETTES[VisualStyle.EDITORIAL_DARK.value])
    with Image.open(src_image_path) as raw:
        src = raw.convert("RGB")

    sw, sh = src.size
    src_aspect = sw / max(1, sh)
    target_aspect = width / max(1, height)
    is_landscape = width > height

    # Frame inside blurred ambient backdrop when aspect ratio mismatches significantly
    needs_card_frame = (src_aspect < 1.15) if is_landscape else (src_aspect > 0.95)
    if needs_card_frame:
        bg = src.resize((width, height), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
        bg = ImageEnhance.Brightness(bg).enhance(0.42)
        bg = _add_radial_glow(bg, (width // 2, int(height * 0.42)), 380, pal["accent"], alpha=55)

        if is_landscape:
            card_h = height - 180
            card_w = min(width - 220, int(card_h * max(0.4, src_aspect)))
            x_off = (width - card_w) // 2
            y_off = 64
        else:
            card_w = width - 96
            card_h = min(1040, int(card_w / max(0.3, src_aspect)))
            x_off = 48
            y_off = max(230, (1240 - card_h) // 2)

        fg = src.resize((card_w, card_h), Image.Resampling.LANCZOS)
        rgba = bg.convert("RGBA")
        shadow = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [x_off, y_off + 14, x_off + card_w, y_off + card_h + 22], radius=24, fill=(0, 0, 0, 170)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=20))
        rgba = Image.alpha_composite(rgba, shadow)

        mask = _rounded_mask((card_w, card_h), radius=24)
        rgba.paste(fg, (x_off, y_off), mask)
        draw = ImageDraw.Draw(rgba)
        draw.rounded_rectangle(
            [x_off - 1, y_off - 1, x_off + card_w + 1, y_off + card_h + 1],
            radius=24,
            outline=(*pal["accent"], 215),
            width=3,
        )
        canvas = rgba.convert("RGB")
    else:
        if src_aspect > target_aspect:
            new_h = height
            new_w = int(new_h * src_aspect)
        else:
            new_w = width
            new_h = int(new_w / max(0.1, src_aspect))
        resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = max(0, (new_w - width) // 2)
        top = max(0, (new_h - height) // 2)
        canvas = resized.crop((left, top, left + width, top + height))

    if is_archival and style == VisualStyle.VINTAGE_ARCHIVAL:
        canvas = ImageEnhance.Color(canvas).enhance(0.58)
        canvas = ImageEnhance.Contrast(canvas).enhance(1.12)

    canvas = _add_vignette(canvas)
    if stat_text:
        canvas = _draw_top_pill(canvas, stat_text, pal=pal, is_stat=True)
    elif badge_text:
        canvas = _draw_top_pill(canvas, badge_text, pal=pal, is_stat=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    return out_path


def _split_headline_and_body(headline: str, body_text: str) -> Tuple[str, str]:
    """Avoid awkward duplicate text when headline equals the start of body_text."""
    h = " ".join((headline or "").split()).strip()
    b = " ".join((body_text or "").split()).strip()
    if not h and b:
        words = b.split()
        if len(words) <= 8:
            return b, ""
        return " ".join(words[:7]), " ".join(words[7:])
    if h and b and b.lower().startswith(h.lower()):
        rem = b[len(h):].lstrip(" ,.:;-—")
        return h, rem
    if h.lower() == b.lower():
        return h, ""
    return h, b


def _extract_auto_stat(text: str) -> str:
    m = re.search(r"\b(\d{4}|\d+(?:\.\d+)?%|\$\d+(?:\.\d+)?[BMK]?|\d+(?:,\d{3})+)\b", text or "")
    return m.group(1) if m else ""


def render_editorial_card(
    out_path: Path,
    *,
    style: VisualStyle,
    headline: str,
    body_text: str,
    stat_text: str = "",
    badge_text: str = "STORY",
    seed_key: str = "",
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> Path:
    """Render a crisp layered editorial / stat / dossier card in 9:16 or 16:9 pure Python."""
    pal = STYLE_PALETTES.get(style.value, STYLE_PALETTES[VisualStyle.EDITORIAL_DARK.value])
    digest = int(hashlib.sha256((seed_key or headline or body_text).encode("utf-8")).hexdigest()[:8], 16)
    is_landscape = width > height

    img = _vertical_gradient(width, height, pal["bg1"], pal["bg2"])
    cx = int(width * 0.2) + (digest % max(120, int(width * 0.6)))
    cy = int(height * 0.22) + ((digest >> 8) % max(120, int(height * 0.25)))
    img = _add_radial_glow(img, (cx, cy), 340, pal["accent"], alpha=70)
    img = _add_radial_glow(img, (width - cx, cy + int(height * 0.22)), 260, pal["accent2"], alpha=45)

    draw = ImageDraw.Draw(img)
    dot_color = (
        min(255, pal["bg2"][0] + 24),
        min(255, pal["bg2"][1] + 26),
        min(255, pal["bg2"][2] + 30),
    )
    pattern_h = height - 160 if is_landscape else 1340
    if digest % 2 == 0:
        for x in range(45, width, 60):
            for y in range(45, pattern_h, 60):
                draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=dot_color)
    else:
        for x in range(0, width, 90):
            draw.line([(x, 0), (x, pattern_h)], fill=dot_color, width=1)
        for y in range(0, pattern_h, 90):
            draw.line([(0, y), (width, y)], fill=dot_color, width=1)

    head_clean, body_clean = _split_headline_and_body(headline, body_text)
    hero_stat = (stat_text or "").strip() or _extract_auto_stat(f"{head_clean} {body_clean}")
    layout_idx = 0 if hero_stat else (1 + (digest % 2))

    # Main shadowed editorial panel (above caption safe zone)
    if is_landscape:
        panel_box = (96, 68, width - 96, height - 180)
    else:
        panel_box = (68, 220, width - 68, 1180)
    px1, py1, px2, py2 = panel_box
    img = _draw_shadow_rounded_box(
        img,
        panel_box,
        radius=28,
        fill=pal["panel"],
        outline=pal["accent"],
        width=3,
    )
    draw = ImageDraw.Draw(img)

    # Top chrome bar inside card
    inner_x = px1 + 48
    inner_right = px2 - 48
    bar_y = py1 + 48
    badge_font = _load_font(_FONTS_MONO_BOLD, 28)
    badge_lbl = (badge_text or "STORY").upper()[:24]
    bb = draw.textbbox((0, 0), badge_lbl, font=badge_font)
    bw = (bb[2] - bb[0]) + 44
    draw.rounded_rectangle([inner_x, bar_y, inner_x + bw, bar_y + 54], radius=10, fill=pal["accent"])
    draw.text((inner_x + 22, bar_y + 11), badge_lbl, font=badge_font, fill=pal["bg1"])

    tag_right = "CASE FILE" if layout_idx == 2 else ("KEY METRIC" if layout_idx == 0 else "STORY BEAT")
    tr_font = _load_font(_FONTS_MONO_BOLD, 24)
    tb = draw.textbbox((0, 0), tag_right, font=tr_font)
    draw.text((inner_right - (tb[2] - tb[0]), bar_y + 15), tag_right, font=tr_font, fill=pal["muted"])
    draw.line([(inner_x, bar_y + 80), (inner_right, bar_y + 80)], fill=dot_color, width=2)

    title_fonts = _FONTS_SERIF_BLACK if style == VisualStyle.VINTAGE_ARCHIVAL else _FONTS_BLACK
    max_text_w = inner_right - inner_x
    y_cursor = bar_y + 114

    if layout_idx == 0 and hero_stat:
        stat_size = (108 if is_landscape else 132) if len(hero_stat) <= 6 else ((92 if is_landscape else 104) if len(hero_stat) <= 10 else 80)
        stat_font = _load_font(_FONTS_BLACK, stat_size)
        draw.text((inner_x + 2, y_cursor + 4), hero_stat[:16], font=stat_font, fill=(6, 8, 13))
        draw.text((inner_x, y_cursor), hero_stat[:16], font=stat_font, fill=pal["accent"])
        sb_box = draw.textbbox((0, 0), hero_stat[:16], font=stat_font)
        y_cursor += (sb_box[3] - sb_box[1]) + (28 if is_landscape else 42)

    # High-impact headline with accent-colored lead line for visual pop
    h_size = (58 if is_landscape else 66) if len(head_clean) <= 55 else (50 if is_landscape else 56)
    title_font = _load_font(title_fonts, h_size)
    head_lines = _wrap_text_px(draw, head_clean, title_font, max_text_w)[: (3 if is_landscape else 4)]

    if layout_idx == 1 and head_lines:
        block_h = len(head_lines) * (h_size + 16)
        draw.rounded_rectangle([inner_x, y_cursor + 6, inner_x + 10, y_cursor + block_h - 6], radius=4, fill=pal["accent"])
        x_head = inner_x + 32
        head_lines = _wrap_text_px(draw, head_clean, title_font, max_text_w - 32)[: (3 if is_landscape else 4)]
    else:
        x_head = inner_x

    for idx_ln, ln in enumerate(head_lines):
        fill_col = pal["accent"] if (layout_idx == 1 and idx_ln == 0 and not hero_stat) else pal["text"]
        draw.text((x_head + 2, y_cursor + 3), ln, font=title_font, fill=(6, 8, 13))
        draw.text((x_head, y_cursor), ln, font=title_font, fill=fill_col)
        y_cursor += h_size + 16

    body_limit_y = py2 - 90
    if body_clean and y_cursor < body_limit_y - 80:
        y_cursor += 16
        draw.rounded_rectangle([inner_x, y_cursor, inner_x + 164, y_cursor + 6], radius=3, fill=pal["accent2"])
        y_cursor += 28

        body_font = _load_font(_FONTS_SANS_MED, 38 if is_landscape else 42)
        body_lines = _wrap_text_px(draw, body_clean, body_font, max_text_w)[: (4 if is_landscape else 5)]
        for ln in body_lines:
            if y_cursor > body_limit_y:
                break
            draw.text((inner_x, y_cursor), ln, font=body_font, fill=pal["muted"])
            y_cursor += 50 if is_landscape else 56

    # Subtle HUD corner ticks inside panel
    c_in = 24
    draw.line([(px1 + c_in, py2 - 42), (px1 + c_in + 40, py2 - 42)], fill=pal["accent"], width=3)
    draw.line([(px1 + c_in, py2 - 80), (px1 + c_in, py2 - 42)], fill=pal["accent"], width=3)
    draw.line([(px2 - c_in - 40, py2 - 42), (px2 - c_in, py2 - 42)], fill=pal["accent"], width=3)
    draw.line([(px2 - c_in, py2 - 80), (px2 - c_in, py2 - 42)], fill=pal["accent"], width=3)

    img = _add_vignette(img)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path
