"""Deterministic procedural asset catalog for CurioLoop's Cartoon 3D family."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict


def _asset_id(kind: str, label: str) -> str:
    stable = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")[:48] or "story_asset"
    digest = hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()[:8]
    return f"{kind}_{stable}_{digest}"


def build_asset_manifest(script: Dict[str, Any]) -> Dict[str, Any]:
    """Describe reusable procedural assets and their provenance for each render."""
    characters: Dict[str, Dict[str, str]] = {}
    environments: Dict[str, Dict[str, str]] = {}
    props: Dict[str, Dict[str, str]] = {}
    animations: Dict[str, Dict[str, str]] = {}
    for index, line in enumerate(script.get("lines") or []):
        scene = line.get("scene") if isinstance(line, dict) else {}
        scene = scene if isinstance(scene, dict) else {}
        # Do not invent a character when the narration centers on an object, place,
        # or event. The scene composer can still build its focal prop/environment.
        names = scene.get("characters") or []
        if isinstance(names, str):
            names = [names]
        for name in names[:5]:
            label = str(name).strip()[:80]
            if label:
                characters.setdefault(label.casefold(), {
                    "id": _asset_id("character", label), "name": label, "kind": "original_procedural_2d_cartoon",
                    "palette": "stable_by_character_identity", "license": "CurioLoop original procedural asset",
                })
        env = str(scene.get("environment") or "Cartoon story environment").strip()[:180]
        environments.setdefault(env.casefold(), {
            "id": _asset_id("environment", env), "description": env,
            "kind": "original_procedural_threejs_environment", "license": "CurioLoop original procedural asset",
        })
        for prop in scene.get("props") or []:
            label = str(prop).strip()[:100]
            if label:
                props.setdefault(label.casefold(), {
                    "id": _asset_id("prop", label), "name": label,
                    "kind": "original_procedural_threejs_prop", "license": "CurioLoop original procedural asset",
                })
        motion = str(scene.get("animation") or "gentle character and environment movement").strip()[:180]
        animations.setdefault(motion.casefold(), {
            "id": _asset_id("animation", motion), "instruction": motion,
            "kind": "procedural_timeline", "license": "CurioLoop original procedural animation",
        })
    return {
        "catalog_version": 1,
        "renderer_family": "cartoon_3d",
        "source_policy": "No external or unlicensed visual assets; generated procedurally at render time.",
        "characters": list(characters.values()),
        "environments": list(environments.values()),
        "props": list(props.values()),
        "animations": list(animations.values()),
        "background": {"kind": "procedural_story_environment", "license": "CurioLoop original procedural asset"},
    }
