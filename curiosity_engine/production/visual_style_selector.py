"""Narrative keyword and category selector for Cartoon 3D V1."""
from __future__ import annotations

import re
from typing import Any, Dict

PROFILES = {
    "historical": {"environment": "street", "palette": "sunny ochre, brick red, teal", "lighting": "warm daylight"},
    "mystery": {"environment": "forest", "palette": "deep teal, amber, plum", "lighting": "cool dusk with a warm story focal light"},
    "space": {"environment": "space", "palette": "indigo, cobalt, bright warm gold", "lighting": "high contrast star light and colored rim"},
    "science": {"environment": "laboratory", "palette": "teal, cream, warm orange", "lighting": "bright laboratory key with cool fill"},
    "fiction": {"environment": "interior", "palette": "story-specific saturated colors", "lighting": "cinematic warm key and colored fill"},
}


def select_visual_style(script_data: Dict[str, Any], manual_override: str = "") -> Dict[str, Any]:
    """Select only a supported variation of the Cartoon 3D family."""
    text = " ".join([
        str(script_data.get("topic", "")),
        str(script_data.get("category", "")),
        str(script_data.get("title", "")),
        " ".join(str(line.get("text", "")) for line in script_data.get("lines", []) if isinstance(line, dict)),
    ]).lower()
    category = str(script_data.get("category", "")).lower()
    if manual_override:
        key = manual_override.strip().lower()
        if key not in PROFILES:
            raise ValueError(f"Unsupported Cartoon 3D visual profile: {manual_override}")
        selected = key
    elif any(x in category for x in ("space", "astronomy", "cosmic")) or re.search(r"\b(planet|orbit|spacecraft|astronaut|comet|asteroid|moon|star|galaxy)\b", text):
        selected = "space"
    elif any(x in category for x in ("history", "historical")) or re.search(r"\b(century|empire|ancient|historical|191[0-9]|18[0-9]{2}|19[0-9]{2})\b", text):
        selected = "historical"
    elif any(x in category for x in ("science", "discovery")) or re.search(r"\b(laboratory|scientist|experiment|telescope|microscope|discovery)\b", text):
        selected = "science"
    elif any(x in category for x in ("fiction", "horror", "thriller")):
        selected = "fiction"
    elif any(x in category for x in ("mystery", "mysteries", "unexplained")) or re.search(r"\b(cabin|forest|missing|vanished|mystery|mysteries|unexplained|secret|mysterious|shipwreck)\b", text):
        selected = "mystery"
    else:
        selected = "fiction" if script_data.get("content_lane") == "creator_series" else "historical"
    return {"renderer_family": "cartoon_3d", "profile": selected, **PROFILES[selected]}
