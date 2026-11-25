"""Word-level animated ASS subtitle generator positioned in YouTube Shorts safe zone."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from reelforge import config
from reelforge.models import VisualStyle, WordTiming

# ASS colors are &HAABBGGRR
_ACCENT_ASS: Dict[str, str] = {
    VisualStyle.EDITORIAL_DARK.value: "&H0022D3EE",       # electric cyan
    VisualStyle.VINTAGE_ARCHIVAL.value: "&H005C9ED6",     # parchment gold
    VisualStyle.GRAPHIC_NOIR.value: "&H005A44EB",         # crimson
    VisualStyle.CINEMATIC_PAINTERLY.value: "&H00E4CA48",  # cyan-gold
    VisualStyle.BLUEPRINT_TECH.value: "&H00F8BD38",       # electric sky
}

_SECONDARY_ACCENT_ASS: Dict[str, str] = {
    VisualStyle.EDITORIAL_DARK.value: "&H0035A7FF",       # warm amber
    VisualStyle.VINTAGE_ARCHIVAL.value: "&H00B5E2FA",     # cream sky
    VisualStyle.GRAPHIC_NOIR.value: "&H00F8BD38",         # electric sky
    VisualStyle.CINEMATIC_PAINTERLY.value: "&H006BD6FF",  # warm gold
    VisualStyle.BLUEPRINT_TECH.value: "&H0086EFAC",       # mint emerald
}


def _fmt_ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _group_words(words: List[WordTiming], max_words: int = 3, max_chars: int = 18) -> List[List[WordTiming]]:
    """Group words into punchy 1-3 word chunks that stay compact on 1080px width."""
    groups: List[List[WordTiming]] = []
    cur: List[WordTiming] = []
    cur_len = 0
    for w in words:
        txt = w.word.strip()
        if not txt:
            continue
        added = len(txt) + (1 if cur else 0)
        if cur and (len(cur) >= max_words or cur_len + added > max_chars or w.speaker != cur[0].speaker):
            groups.append(cur)
            cur = [w]
            cur_len = len(txt)
        else:
            cur.append(w)
            cur_len += added
    if cur:
        groups.append(cur)
    return groups


def write_word_synced_ass(
    words: List[WordTiming],
    out_ass: Path,
    style: VisualStyle = VisualStyle.EDITORIAL_DARK,
    words_per_group: int = 3,
) -> Path:
    """Write a 1080x1920 ASS caption file with animated active-word highlight in safe zone."""
    accent_primary = _ACCENT_ASS.get(style.value, "&H0022D3EE")
    accent_secondary = _SECONDARY_ACCENT_ASS.get(style.value, "&H0035A7FF")

    # Layer 0: subtle dark backdrop pill/shadow; Layer 1: crisp heavy typography with micro-pop
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.VIDEO_WIDTH}
PlayResY: {config.VIDEO_HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.CAPTION_FONT_NAME},74,&H00FFFFFF,&H00FFFFFF,&H000A0D14,&HA0000000,-1,0,0,0,100,100,1.5,0,1,8,3,2,72,72,{config.CAPTION_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: List[str] = []
    clean_words = [w for w in words if w.word.strip()]
    groups = _group_words(clean_words, max_words=max(1, words_per_group))

    for g_idx, group in enumerate(groups):
        next_group_start = groups[g_idx + 1][0].start_sec if g_idx + 1 < len(groups) else None
        for active_idx, active_w in enumerate(group):
            start_t = active_w.start_sec
            if active_idx + 1 < len(group):
                end_t = max(start_t + 0.05, group[active_idx + 1].start_sec)
            elif next_group_start is not None:
                end_t = max(start_t + 0.06, min(next_group_start, active_w.end_sec + 0.22))
            else:
                end_t = max(start_t + 0.14, active_w.end_sec + 0.18)

            accent = accent_secondary if active_w.speaker == "secondary" else accent_primary
            parts: List[str] = []
            for j, w in enumerate(group):
                token = _esc_ass(w.word.strip().upper())
                if j == active_idx:
                    parts.append(
                        f"{{\\c{accent}\\fscx115\\fscy115\\t(0,75,\\fscx108\\fscy108)}}{token}"
                        f"{{\\c&H00FFFFFF&\\fscx100\\fscy100}}"
                    )
                elif j < active_idx:
                    parts.append(f"{{\\c&H00FFFFFF&}}{token}")
                else:
                    parts.append(f"{{\\c&H00CBD5E1&}}{token}")

            # Slight chunk entrance pop on first word of the group
            prefix = "{\\blur0.7\\fscx94\\fscy94\\t(0,70,\\fscx100\\fscy100)}" if active_idx == 0 else "{\\blur0.7}"
            line_text = prefix + " ".join(parts)
            events.append(
                f"Dialogue: 0,{_fmt_ass_time(start_t)},{_fmt_ass_time(end_t)},Default,,0,0,0,,{line_text}"
            )

    out_ass.parent.mkdir(parents=True, exist_ok=True)
    out_ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out_ass
