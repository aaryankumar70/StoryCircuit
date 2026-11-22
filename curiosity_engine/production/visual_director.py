"""Deterministic, narration-led Cartoon 3D shot planning."""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from curiosity_engine.production.visual_style_selector import select_visual_style


def _short_list(value: Any, limit: int, max_chars: int) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip()[:max_chars] for item in value if str(item).strip()][:limit]


def build_scene_plan(script_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize approved script scene directions into bounded render instructions."""
    lines = script_data.get("lines") or []
    plan: List[Dict[str, Any]] = []
    for index, line in enumerate(lines):
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        raw = line.get("scene")
        if isinstance(raw, str):
            raw = {"visual_description": raw}
        elif not isinstance(raw, dict):
            raw = {}
        plan.append({
            "scene_id": str(raw.get("scene_id") or f"scene_{index + 1:02d}"),
            "line_index": index,
            "narration": text,
            "visual_description": str(raw.get("visual_description") or raw.get("description") or text)[:600],
            "visual_cues": _short_list(raw.get("visual_cues"), 8, 160),
            "characters": _short_list(raw.get("characters") or raw.get("character_requirements"), 5, 80),
            "environment": str(raw.get("environment") or "A colorful story setting illustrating the narration")[:180],
            "props": _short_list(raw.get("props"), 8, 100),
            "camera": str(raw.get("camera") or "medium shot, slow push in")[:180],
            "lighting": str(raw.get("lighting") or "warm cinematic daylight")[:120],
            "animation": str(raw.get("animation") or "character gesture and gentle environmental movement")[:180],
            "transition": str(raw.get("transition") or "cut")[:80],
            "continuity": str(raw.get("continuity") or "Maintain character appearance, costume, and screen direction")[:180],
        })
    if not plan:
        raise ValueError("A renderable script needs at least one non-empty narration line.")
    return plan


def group_scene_plan(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge adjacent lines with the same scene ID without losing narration detail."""
    grouped: List[Dict[str, Any]] = []
    for item in plan:
        if grouped and grouped[-1]["scene_id"] == item["scene_id"]:
            current = grouped[-1]
            current["line_indices"].append(item["line_index"])
            current["narration"] += " " + item["narration"]
            current["visual_description"] += "; " + item["visual_description"]
            for field in ("visual_cues", "characters", "props"):
                current[field] = list(dict.fromkeys(current[field] + item[field]))[:10]
            continue
        grouped.append({**item, "line_indices": [item["line_index"]]})
    return grouped


def safe_duration_hint(text: str, words_per_second: float = 2.46) -> float:
    words = len(re.findall(r"\b[\w’'-]+\b", text))
    return max(0.4, words / max(1.2, min(4.0, words_per_second)))


_STOP_WORDS = {
    "about", "after", "again", "against", "along", "also", "among", "another", "around", "because",
    "before", "being", "between", "could", "every", "from", "have", "into", "just", "might", "never",
    "only", "other", "over", "really", "said", "same", "some", "than", "that", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "under", "until", "very", "were", "what", "when",
    "where", "which", "while", "with", "would", "your", "into", "onto", "upon", "once", "afterwards",
    "finds", "found", "follows", "followed", "moves", "moved", "notices", "noticed", "shows", "showed",
    "turns", "turned", "opens", "opened", "looks", "looked", "walks", "walked", "runs", "ran", "sees",
    "saw", "reveals", "revealed", "discovers", "discovered", "appears", "appeared", "begins", "began",
}
_ROLE_WORDS = (
    "astronaut", "archivist", "captain", "child", "crew", "driver", "explorer", "investigator", "pilot",
    "researcher", "sailor", "scientist", "traveler", "traveller", "witness", "worker", "villager", "doctor",
    "teacher", "officer", "soldier", "engineer", "family", "mother", "father", "sister", "brother",
)
_OBJECT_WORDS = {
    "archive", "artifact", "bell", "book", "bottle", "bridge", "cabin", "camera", "canoe", "case", "chart",
    "clue", "compass", "door", "engine", "file", "fossil", "glass", "harbor", "harbour", "helmet", "key",
    "lantern", "ledger", "letter", "lighthouse", "log", "logbook", "map", "message", "mirror", "moon",
    "notebook", "planet", "photo", "photograph", "picture", "radio", "record", "report", "ring", "ruins",
    "satellite", "sea", "ship", "signal", "star", "telescope", "train", "vessel", "watch", "wheel", "wreck",
}
_CAMERA_SEQUENCE = (
    "wide establishing shot with a gentle forward dolly",
    "over-the-shoulder medium shot with a slow push toward the story clue",
    "close detail shot that racks focus from the subject to the relevant object",
    "low tracking shot following the action through the environment",
    "measured pullback that reveals the consequence and leaves a clear focal subject",
)
_VISUAL_TYPES = ("establishing", "narrative_action", "evidence_detail", "turning_point", "resolution")


def _salient_terms(text: str, limit: int = 4) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", str(text or ""))
    unique: List[str] = []
    seen = set()
    for word in words:
        key = word.casefold().strip("'-")
        if key in _STOP_WORDS or key in seen or len(key) < 4:
            continue
        seen.add(key)
        unique.append(word.strip("'-"))
        if len(unique) >= limit:
            break
    return unique


def _infer_characters(text: str) -> List[str]:
    lowered = text.casefold()
    roles = [role for role in _ROLE_WORDS if re.search(rf"\b{re.escape(role)}s?\b", lowered)]
    if roles:
        return [role.title() for role in roles[:3]]
    names = re.findall(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)\b", text)
    names = [name for name in names if name.casefold() not in {"the", "one", "then", "when", "after", "before"}]
    return list(dict.fromkeys(names[:2]))


def _environment_for_scene(terms: List[str], profile: Dict[str, str]) -> str:
    words = {term.casefold() for term in terms}
    if words & {"archive", "ledger", "log", "logbook", "record", "report", "file", "notebook", "document"}:
        return "Archive reading room with shelves, a worktable, and the story's records"
    if words & {"lighthouse", "harbor", "harbour", "ship", "vessel", "sailor", "captain", "ocean", "sea", "wreck"}:
        return "Story-matched lighthouse coast and harbor with a clear horizon line"
    if words & {"laboratory", "scientist", "experiment", "telescope", "microscope", "fossil"}:
        return "Working science laboratory arranged around the narrated discovery"
    if words & {"spacecraft", "astronaut", "planet", "satellite", "orbit", "moon", "star"}:
        return "Stylized orbital environment with the narrated spacecraft or celestial body"
    if words & {"rainforest", "forest", "woods", "tree", "jungle"}:
        return "Layered forest environment with visible depth and the narrated path"
    if words & {"cave", "tunnel", "underground", "mine"}:
        return "Readable underground passage shaped around the narrated clue"
    if words & {"street", "town", "village", "city", "station", "bridge"}:
        return "Story-matched town street with clear architectural landmarks"
    if words & {"letter", "message", "clue", "key", "door", "mirror"}:
        return "Atmospheric interior composed around the specific story clue"
    return f"{profile['environment']} setting composed around the narrated subject"


def assign_narrative_scenes(script_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create bounded Cartoon 3D shot directions from approved narration without an LLM call.

    This operation never creates or rewrites narration. It is available while Ollama is
    in safe standby so existing approved scripts and Creator stories can still be
    directed without pretending that model-generated scripts are available.
    """
    if not isinstance(script_data, dict):
        raise ValueError("Scene direction requires a script object.")
    out = copy.deepcopy(script_data)
    lines = out.get("lines") or []
    if not isinstance(lines, list) or not lines or len(lines) > 60:
        raise ValueError("Scene direction requires between 1 and 60 narration lines.")
    try:
        wps = float(out.get("words_per_second") or 2.46)
        lead = float(out.get("lead", 0.45))
        gap = float(out.get("gap", 0.30))
    except (TypeError, ValueError) as exc:
        raise ValueError("Scene direction timing values must be numeric.") from exc
    if not 1.2 <= wps <= 4.0 or not 0 <= lead <= 1.5 or not 0 <= gap <= 1.25:
        raise ValueError("Scene direction timing values are outside supported bounds.")
    profile = select_visual_style(out)
    cursor = lead
    previous_environment = ""

    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValueError(f"Narration line {index + 1} must be an object.")
        narration = str(line.get("text") or "").strip()
        if not narration or len(narration) > 1200:
            raise ValueError(f"Narration line {index + 1} is empty or exceeds 1,200 characters.")
        raw_scene = line.get("scene")
        if isinstance(raw_scene, str):
            scene = {"visual_description": raw_scene.strip()}
        elif isinstance(raw_scene, dict):
            scene = dict(raw_scene)
        else:
            scene = {}

        terms = _salient_terms(narration)
        cue = ", ".join(terms[:3]) or "the story's central subject"
        described_action = str(scene.get("visual_description") or scene.get("description") or "").strip()
        if (re.fullmatch(r"scene[ _-]?\d+", described_action, flags=re.IGNORECASE)
                or any(term in described_action.casefold() for term in ("generic decorative", "generic animation", "illustrate the specific subject"))):
            described_action = ""
        if not described_action:
            described_action = f"Show the specific event in the narration: {narration}"
        environment = str(scene.get("environment") or "").strip()
        if any(term in environment.casefold() for term in ("colorful story environment", "colorful story setting", "matched to the approved storyboard")):
            environment = ""
        if not environment:
            environment = _environment_for_scene(terms, profile)
        characters = _short_list(scene.get("characters") or scene.get("character_requirements"), 5, 80)
        if not characters:
            characters = _infer_characters(narration)
        props = _short_list(scene.get("props"), 8, 100)
        if not props:
            props = [term for term in terms if term.casefold() in _OBJECT_WORDS][:3]
            if not props:
                props = [term for term in terms if term.casefold() not in _ROLE_WORDS][:2]
        cues = _short_list(scene.get("visual_cues"), 8, 160)
        if not cues:
            cues = [f"Narration subject: {cue}", f"Visible action: {narration[:120]}"]
        visual_type = str(scene.get("visual_type") or _VISUAL_TYPES[index % len(_VISUAL_TYPES)])
        camera = str(scene.get("camera") or _CAMERA_SEQUENCE[index % len(_CAMERA_SEQUENCE)])
        lighting = str(scene.get("lighting") or profile["lighting"])
        animation = str(scene.get("animation") or f"Animate the narrated action directly: {narration[:150]}")
        transition = str(scene.get("transition") or ("opening reveal" if index == 0 else "cut"))
        continuity = str(scene.get("continuity") or "Keep character identity, costume, screen direction, and palette consistent")
        if previous_environment and index and transition.casefold() not in {"cut", "flashback", "location change"}:
            continuity = f"{continuity}; carry forward from {previous_environment[:70]}"
        duration = safe_duration_hint(narration, wps)
        start = cursor
        end = start + duration
        scene.update({
            "scene_id": str(scene.get("scene_id") or f"scene_{index + 1:02d}"),
            "visual_type": visual_type,
            "narration": narration,
            "visual_description": described_action[:600],
            "visual_cues": cues,
            "characters": characters,
            "environment": environment[:180],
            "props": props,
            "camera": camera[:180],
            "lighting": lighting[:120],
            "animation": animation[:180],
            "transition": transition[:80],
            "continuity": continuity[:180],
            "estimated_start_sec": round(start, 2),
            "estimated_end_sec": round(end, 2),
        })
        line["scene"] = scene
        line["visual"] = scene["visual_description"]
        previous_environment = environment
        cursor = end + gap
    out["scene_count"] = len(lines)
    return out
