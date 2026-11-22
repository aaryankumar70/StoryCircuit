"""Chromium/Three.js/FFmpeg implementation of CurioLoop's visual contract."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from curiosity_engine.config import DATA_DIR, MAX_DURATION_SEC, MAX_WORD_COUNT, MIN_DURATION_SEC, OUTPUT_DIR, PROJECT_ROOT, get_chrome_executable
from curiosity_engine.generation.contracts import GenerationEngineError, VisualRenderingEngine
from curiosity_engine.generation.resource_lock import sequential_resource_stage
from curiosity_engine.production.renderer import current_render_matches, resolve_ffprobe_executable, validate_rendered_mp4, write_render_manifest
from curiosity_engine.production.asset_system import build_asset_manifest
from curiosity_engine.production.visual_director import assign_narrative_scenes, build_scene_plan, group_scene_plan
from curiosity_engine.production.visual_style_selector import select_visual_style

logger = logging.getLogger("curiosity_engine.generation.cartoon3d")
HARD_MAX_TEMP_BYTES = 16 * 1024 ** 3
HARD_MAX_BUNDLE_BYTES = 250 * 1024 ** 2
HARD_MAX_DURATION_SEC = float(MAX_DURATION_SEC)
STALE_WORKSPACE_HOURS = 24
RENDERER_VERSION = "cartoon3d-v2"


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("video_id must contain at least one safe filename character")
    return cleaned[:100]


def _string_list(value: Any, limit: int, max_chars: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip()[:max_chars] for item in value if str(item).strip()][:limit]


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_symlink():
                continue
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total


def _contains_symlink(root: Path) -> bool:
    if root.is_symlink():
        return True
    return any(path.is_symlink() for path in root.rglob("*"))


def _renderer_temp_bytes(root: Path) -> int:
    """Count only CurioLoop-owned temp directories under a dedicated render root."""
    return sum(_tree_bytes(path) for path in root.glob("curioloop-render-*") if path.is_dir() and not path.is_symlink())


def _renderer_stage_bytes(parent: Path) -> int:
    total = 0
    for path in parent.glob(".curioloop-render-stage-*.mp4"):
        owner = path.with_suffix(path.suffix + ".owner.json")
        try:
            if path.is_file() and not path.is_symlink() and owner.is_file() and not owner.is_symlink():
                metadata = json.loads(owner.read_text(encoding="utf-8"))
                if metadata.get("owner") == "curioloop_render_stage":
                    total += path.stat().st_size
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return total


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _cleanup_stale_capture_dirs(temp_root: Path, older_than_hours: int = 24) -> int:
    """Remove only inactive directories with our private prefix under the configured root."""
    cutoff = time.time() - older_than_hours * 3600
    removed = 0
    if not temp_root.exists():
        return removed
    resolved_root = temp_root.resolve()
    for path in temp_root.glob("curioloop-render-*"):
        try:
            if not path.is_dir() or path.resolve().parent != resolved_root or path.stat().st_mtime >= cutoff:
                continue
            marker = path / "owner.json"
            if not marker.is_file() or marker.is_symlink():
                continue
            owner = json.loads(marker.read_text(encoding="utf-8"))
            if owner.get("owner") != "curioloop_render_temp":
                continue
            pids = {int(owner.get(key, 0) or 0) for key in ("pid", "node_pid", "browser_pid")}
            if any(_alive(pid) for pid in pids if pid > 0):
                continue
            if path.resolve().parent != resolved_root:
                continue
            shutil.rmtree(path)
            removed += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.debug("Leaving stale render temp candidate %s untouched: %s", path, exc)
    return removed


def _cleanup_stale_project_staging(project_parent: Path, older_than_hours: int = STALE_WORKSPACE_HOURS) -> int:
    cutoff = time.time() - older_than_hours * 3600
    removed = 0
    resolved_parent = project_parent.resolve()
    for path in project_parent.glob("*.staging-????????"):
        try:
            if not path.is_dir() or path.is_symlink() or path.resolve().parent != resolved_parent or path.stat().st_mtime >= cutoff:
                continue
            marker = path / "owner.json"
            if not marker.is_file() or marker.is_symlink():
                continue
            owner = json.loads(marker.read_text(encoding="utf-8"))
            if owner.get("owner") != "curioloop_project_staging":
                continue
            pids = {int(owner.get(key, 0) or 0) for key in ("pid", "node_pid", "browser_pid")}
            if any(_alive(pid) for pid in pids if pid > 0):
                continue
            shutil.rmtree(path)
            removed += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.debug("Leaving stale project staging directory %s untouched: %s", path, exc)
    return removed


def _cleanup_stale_output_stages(output_parent: Path, older_than_hours: int = STALE_WORKSPACE_HOURS) -> int:
    """Recover only renderer-owned staged MP4s whose Python, Node, and browser owners are gone."""
    cutoff = time.time() - older_than_hours * 3600
    removed = 0
    resolved_parent = output_parent.resolve()
    for staged in output_parent.glob(".curioloop-render-stage-*.mp4"):
        try:
            owner_path = staged.with_suffix(staged.suffix + ".owner.json")
            if (not staged.is_file() or staged.is_symlink() or staged.resolve().parent != resolved_parent
                    or staged.stat().st_mtime >= cutoff or not owner_path.is_file() or owner_path.is_symlink()
                    or owner_path.resolve().parent != resolved_parent):
                continue
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            if owner.get("owner") != "curioloop_render_stage":
                continue
            pids = {int(owner.get(key, 0) or 0) for key in ("pid", "node_pid", "browser_pid")}
            if any(_alive(pid) for pid in pids if pid > 0):
                continue
            staged.unlink()
            owner_path.unlink(missing_ok=True)
            removed += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.debug("Leaving stale render stage %s untouched: %s", staged, exc)
    return removed


def _script_for_visuals(script_data: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt Automatic script or approved Creator episode to the common visual/TTS schema."""
    if script_data.get("lines"):
        normalized = dict(script_data)
        normalized["lines"] = [dict(line) for line in script_data["lines"] if isinstance(line, dict)]
        return normalized
    episode = script_data.get("episode") or {}
    if not isinstance(episode, dict):
        raise ValueError("Creator episode payload must be an object")
    raw_scenes = episode.get("storyboard") or script_data.get("storyboard") or {}
    if isinstance(raw_scenes, dict):
        raw_scenes = raw_scenes.get("scenes") or raw_scenes.get("shots") or []

    def scene_text(value: Any, keys: tuple[str, ...] = ("text", "description", "name")) -> str:
        if isinstance(value, dict):
            for key in keys:
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
            return ""
        if isinstance(value, (list, tuple)):
            return "; ".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    lines = []
    if isinstance(raw_scenes, list):
        for i, scene in enumerate(raw_scenes):
            if not isinstance(scene, dict):
                continue
            text = (scene_text(scene.get("narration"), ("text", "narration", "voiceover"))
                    or scene_text(scene.get("narration_excerpt"))
                    or scene_text(scene.get("voiceover"))
                    or scene_text(scene.get("text")))
            if not text:
                continue
            primary = scene.get("primary_subject") or {}
            primary_name = scene_text(primary, ("name", "character", "subject"))
            primary_action = scene_text(primary, ("action", "animation"))
            camera = scene.get("camera") or {}
            camera_text = scene_text(camera, ("description", "motivation", "shot_type", "movement"))
            lighting = scene.get("lighting") or scene.get("lighting_and_atmosphere") or {}
            lighting_text = scene_text(lighting, ("description", "mood", "style", "key_source"))
            environment = scene_text(scene.get("environment"), ("name", "setting", "description", "era"))
            continuity = scene_text(scene.get("continuity") or scene.get("continuity_requirements"), ("description",))
            transition = scene_text(scene.get("transition") or scene.get("transition_out"), ("type", "description"))
            props = (scene.get("props") or scene.get("important_objects") or scene.get("objects") or [])
            characters = (scene.get("characters") or scene.get("character_requirements") or ([primary_name] if primary_name else []))
            visual_description = (scene_text(scene.get("visual_description"))
                                  or scene_text(scene.get("visual_objective"))
                                  or scene_text(scene.get("visual_match_explanation"))
                                  or scene_text(scene.get("story_event"))
                                  or text)
            lines.append({"text": text, "scene": {
                "scene_id": str(scene.get("scene_id") or scene.get("id") or f"creator_scene_{i + 1:02d}"),
                "visual_description": visual_description,
                "visual_cues": _string_list(scene.get("visual_cues") or scene.get("story_event"), 8, 160),
                "characters": _string_list(characters, 5, 80),
                "environment": environment,
                "props": _string_list(props, 8, 100), "camera": camera_text,
                "lighting": lighting_text, "animation": scene_text(scene.get("animation")) or primary_action,
                "transition": transition, "continuity": continuity,
                "estimated_start_sec": (scene.get("narration") or {}).get("start_s", 0) if isinstance(scene.get("narration"), dict) else 0,
                "estimated_end_sec": (scene.get("narration") or {}).get("end_s", 0) if isinstance(scene.get("narration"), dict) else 0,
            }})
    if not lines:
        narration = str(episode.get("adapted_narration") or episode.get("script") or "").strip()
        if not narration:
            raise ValueError("Creator episode has no narration")
        import re
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()]
        lines = [{"text": s} for s in sentences]
    return {"topic": str(script_data.get("title") or episode.get("title") or "Creator Story"),
            "title": str(episode.get("title") or script_data.get("title") or "Creator Story"),
            "category": "CreatorSeries", "content_lane": "creator_series", "voice": "am_michael", "speed": 1.0,
            "storytelling_delivery": True, "lines": lines,
            "duration": float(episode.get("estimated_duration") or script_data.get("duration") or 48.0),
            "sources": script_data.get("sources") or []}


def _storyboard_for_qc(script: Dict[str, Any]) -> Dict[str, Any]:
    plans = script.get("scene_plan") or build_scene_plan(script)
    scenes = []
    camera_modes = ("MEDIUM", "CLOSE_UP", "WIDE", "OVER_SHOULDER")
    for index, shot in enumerate(plans):
        narration = str(shot.get("narration") or "").strip()
        description = str(shot.get("visual_description") or narration).strip()
        subject = (shot.get("characters") or [None])[0]
        if not subject:
            subject = " ".join(re.findall(r"[A-Za-z0-9'-]+", narration)[:5]) or str(script.get("topic") or "Story subject")
        props = _string_list(shot.get("props") or shot.get("visual_cues"), 8, 100)
        if not props:
            props = [word for word in ("key", "bell", "ledger", "log", "wheel", "ship", "door", "letter", "telescope") if word in narration.lower()]
        cam = str(shot.get("camera") or "medium shot; gentle push-in")
        scenes.append({
            "scene_id": str(shot.get("scene_id") or f"scene_{index + 1:02d}"),
            "beat_index": index + 1,
            "narration": {"text": narration, "start_s": 0, "end_s": 0},
            "primary_subject": {"name": str(subject), "action": str(shot.get("animation") or narration)},
            "environment": {"name": str(shot.get("environment") or description), "era": "", "time_of_day": str(shot.get("lighting") or "story lighting")},
            "important_objects": props,
            "composition_type": camera_modes[index % len(camera_modes)],
            "camera": {"shot_type": camera_modes[index % len(camera_modes)], "motivation": f"{cam}; {description}"},
            "rendering_method": "CARTOON_3D_THREEJS",
            "layers": [{"asset_path": "curioloop/cartoon_3d/narrative_scene"}],
            "visual_match_explanation": description,
        })
    return {"title": str(script.get("title") or script.get("topic") or "CurioLoop Story"),
            "setting": str(script.get("visual_profile", {}).get("environment") or "Cartoon 3D story setting"),
            "total_scenes": len(scenes), "scenes": scenes, "renderer_family": "cartoon_3d"}


def _synchronize_storyboard_timing(project_dir: Path) -> None:
    """Bind storyboard scene windows to the finalized Kokoro sentence timing."""
    storyboard_path = project_dir / "storyboard.json"
    try:
        storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
        timing = json.loads((project_dir / "data" / "lines.json").read_text(encoding="utf-8"))
        line_times = timing.get("lines") or []
        scenes = storyboard.get("scenes") or []
        if not scenes or not line_times:
            raise ValueError("storyboard scenes or narration line timing are empty")
        for index, scene in enumerate(scenes):
            indexes = scene.get("line_indices") or [index]
            indexes = [int(value) for value in indexes]
            if any(value < 0 or value >= len(line_times) for value in indexes):
                raise ValueError(f"scene {scene.get('scene_id')} references an invalid narration line")
            first, last = line_times[indexes[0]], line_times[indexes[-1]]
            start, end = float(first["start"]), float(last["end"])
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                raise ValueError(f"scene {scene.get('scene_id')} has invalid narration timing")
            scene.setdefault("narration", {})["start_s"] = round(start, 3)
            scene["narration"]["end_s"] = round(end, 3)
        storyboard["timing_source"] = "kokoro_sentence_alignment"
        staged = storyboard_path.with_name(f".{storyboard_path.name}.{uuid.uuid4().hex}.tmp")
        staged.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(staged, storyboard_path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise GenerationEngineError(f"Could not synchronize storyboard scenes to narration timing: {exc}") from exc


class Cartoon3DVisualEngine(VisualRenderingEngine):
    def __init__(self, template_dir: Optional[Path] = None, chrome: Optional[str] = None,
                 ffmpeg: str = "ffmpeg", node: str = "node"):
        self.template_dir = Path(template_dir or os.environ.get("CURIOLOOP_CARTOON_TEMPLATE") or PROJECT_ROOT / "templates" / "cartoon-3d")
        self.chrome = chrome or os.environ.get("CHROME") or get_chrome_executable()
        self.ffmpeg = shutil.which(ffmpeg) or ffmpeg
        self.node = shutil.which(node) or node
        self.node_supported = self._node_22_or_newer()

    def _node_22_or_newer(self) -> bool:
        try:
            result = subprocess.run([self.node, "--version"], capture_output=True, text=True, timeout=5,
                                    creationflags=0x08000000 if os.name == "nt" else 0, check=True)
            match = re.search(r"v?(\d+)", result.stdout.strip())
            return bool(match and int(match.group(1)) >= 22)
        except (OSError, subprocess.SubprocessError, ValueError):
            return False

    def is_configured(self) -> bool:
        return (self.template_dir.is_dir() and (self.template_dir / "tools" / "capture.mjs").is_file()
                and (self.template_dir / "tools" / "mix.py").is_file()
                and (self.template_dir / "index.html").is_file()
                and (self.template_dir / "src" / "main.js").is_file()
                and (self.template_dir / "src" / "shots.js").is_file()
                and (self.template_dir / "src" / "environment.js").is_file()
                and (self.template_dir / "vendor" / "three.module.js").is_file()
                and all((self.template_dir / "vendor" / "addons" / "postprocessing" / name).is_file()
                        for name in ("EffectComposer.js", "RenderPass.js", "BokehPass.js", "OutputPass.js"))
                and self.node_supported
                and bool(shutil.which(self.ffmpeg) or Path(self.ffmpeg).exists())
                and bool(resolve_ffprobe_executable())
                and bool(self.chrome and (Path(self.chrome).exists() or shutil.which(self.chrome))))

    def not_configured_reason(self) -> str:
        missing = []
        if not (self.template_dir / "tools" / "capture.mjs").is_file():
            missing.append(f"capture script under {self.template_dir}")
        if not (self.template_dir / "tools" / "mix.py").is_file():
            missing.append("procedural sound design mixer")
        if not (self.template_dir / "index.html").is_file():
            missing.append("renderer index.html")
        if (not (self.template_dir / "src" / "main.js").is_file() or not (self.template_dir / "src" / "shots.js").is_file()
                or not (self.template_dir / "src" / "environment.js").is_file()):
            missing.append("Three.js cartoon assets and scene selector")
        if not (self.template_dir / "vendor" / "three.module.js").is_file():
            missing.append("vendored Three.js module")
        if not all((self.template_dir / "vendor" / "addons" / "postprocessing" / name).is_file()
                   for name in ("EffectComposer.js", "RenderPass.js", "BokehPass.js", "OutputPass.js")):
            missing.append("Three.js postprocessing modules")
        if not self.node_supported:
            missing.append("Node.js 22 or newer")
        if not (shutil.which(self.ffmpeg) or Path(self.ffmpeg).exists()):
            missing.append("FFmpeg")
        if not resolve_ffprobe_executable():
            missing.append("FFprobe")
        if not (self.chrome and (Path(self.chrome).exists() or shutil.which(self.chrome))):
            missing.append("Chromium/Edge")
        return "Missing visual renderer dependencies: " + ", ".join(missing) if missing else "Cartoon 3D renderer is ready."

    def project_directory(self, video_id: str, script_data: Dict[str, Any], output_dir: Path = OUTPUT_DIR) -> Path:
        safe_id = _safe_id(video_id)
        normalized = assign_narrative_scenes(_script_for_visuals(script_data))
        profile = select_visual_style(normalized, os.environ.get("CURIOLOOP_VISUAL_PROFILE", ""))
        normalized["visual_profile"] = profile
        normalized["renderer_version"] = RENDERER_VERSION
        normalized["asset_manifest"] = build_asset_manifest(normalized)
        normalized["scene_plan"] = group_scene_plan(build_scene_plan(normalized))
        key = _sha({"video_id": safe_id, "renderer_version": RENDERER_VERSION, "script": normalized, "visual_profile": profile})
        return Path(output_dir) / ".engine_projects" / safe_id / key

    @sequential_resource_stage
    def prepare_project(self, video_id: str, script_data: Dict[str, Any], output_dir: Path) -> Path:
        if not self.is_configured():
            raise GenerationEngineNotConfiguredError(self.not_configured_reason())
        if not self.template_dir.is_dir():
            raise GenerationEngineError(f"Cartoon renderer template is missing: {self.template_dir}")
        normalized = assign_narrative_scenes(_script_for_visuals(script_data))
        normalized["visual_profile"] = select_visual_style(
            normalized, os.environ.get("CURIOLOOP_VISUAL_PROFILE", "")
        )
        normalized["renderer_version"] = RENDERER_VERSION
        normalized["asset_manifest"] = build_asset_manifest(normalized)
        lines = normalized.get("lines") or []
        if len(lines) > 60:
            raise GenerationEngineError("A short render is limited to 60 narration lines; split long Creator material into approved episodes.")
        words = sum(len(re.findall(r"\b[\w’'-]+\b", str(line.get("text") or ""))) for line in lines if isinstance(line, dict))
        if not lines or words > MAX_WORD_COUNT:
            raise GenerationEngineError(f"Render narration must contain 1-{MAX_WORD_COUNT} words; received {words}.")
        if any(len(str(line.get("text") or "")) > 1200 for line in lines if isinstance(line, dict)):
            raise GenerationEngineError("A narration line exceeds the safe 1,200 character render limit.")
        plan = build_scene_plan(normalized)
        normalized["scene_plan"] = group_scene_plan(plan)
        project_dir = self.project_directory(video_id, normalized, output_dir)
        if project_dir.is_symlink():
            raise GenerationEngineError("Renderer project path is a symbolic link; no files were opened or changed.")
        marker = project_dir / ".curioloop_project.json"
        project_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            max_bundle = int(float(os.environ.get("CURIOLOOP_RENDER_MAX_BUNDLE_MB", "100")) * 1024 * 1024)
        except ValueError as exc:
            raise GenerationEngineError("CURIOLOOP_RENDER_MAX_BUNDLE_MB must be a positive number.") from exc
        if max_bundle <= 0 or max_bundle > HARD_MAX_BUNDLE_BYTES:
            raise GenerationEngineError("CURIOLOOP_RENDER_MAX_BUNDLE_MB must be positive and no greater than the 250 MiB hard limit.")
        if any(path.is_symlink() for path in self.template_dir.rglob("*")):
            raise GenerationEngineError("The renderer bundle contains a symbolic link; remove it before rendering to prevent files escaping the bundle root.")
        if _tree_bytes(self.template_dir) > max_bundle:
            raise GenerationEngineError(f"Cartoon renderer bundle exceeds configured limit ({max_bundle // (1024*1024)} MiB).")
        _cleanup_stale_project_staging(project_dir.parent)
        if not project_dir.exists():
            staging = project_dir.with_name(project_dir.name + f".staging-{uuid.uuid4().hex[:8]}")
            try:
                staging.mkdir(parents=False, exist_ok=False)
                (staging / "owner.json").write_text(json.dumps({"owner": "curioloop_project_staging", "pid": os.getpid(), "created_at": time.time()}), encoding="utf-8")
                shutil.copytree(self.template_dir, staging, copy_function=shutil.copy2, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("script.json", "data", "renders", "review"))
                (staging / "data").mkdir(parents=True, exist_ok=True)
                (staging / "renders").mkdir(parents=True, exist_ok=True)
                (staging / "script.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
                (staging / "storyboard.json").write_text(json.dumps(_storyboard_for_qc(normalized), ensure_ascii=False, indent=2), encoding="utf-8")
                (staging / "owner.json").unlink(missing_ok=True)
                staging_marker = staging / ".curioloop_project.json"
                staging_marker.write_text(json.dumps({"video_id": _safe_id(video_id), "project_id": project_dir.name,
                    "script_hash": _sha(normalized), "engine": "Cartoon3DVisualEngine", "renderer_version": RENDERER_VERSION,
                    "family": "cartoon_3d"}, indent=2), encoding="utf-8")
                staging.replace(project_dir)
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise
        else:
            try:
                if _contains_symlink(project_dir):
                    raise GenerationEngineError("Existing renderer project contains a symbolic link; it was preserved and not opened.")
                prior = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
                stored_script = json.loads((project_dir / "script.json").read_text(encoding="utf-8"))
                if prior.get("script_hash") != _sha(normalized) or _sha(stored_script) != _sha(normalized):
                    raise GenerationEngineError("Existing project workspace content does not match its immutable script key; preserved without overwrite.")
                if not (project_dir / "storyboard.json").exists():
                    (project_dir / "storyboard.json").write_text(json.dumps(_storyboard_for_qc(normalized), ensure_ascii=False, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError) as exc:
                raise GenerationEngineError(f"Existing render workspace is incomplete; it was preserved: {exc}") from exc
        return project_dir

    @sequential_resource_stage
    def render_video(self, project_dir: Path, output_mp4: Path, resume: bool = True, force_rebuild: bool = False) -> Path:
        project_dir, output_mp4 = Path(project_dir), Path(output_mp4)
        if not self.is_configured():
            raise GenerationEngineError("Cartoon renderer dependencies are missing (Three.js assets, Node 22+, Chromium/Edge, or FFmpeg).")
        if _contains_symlink(project_dir):
            raise GenerationEngineError("Render project contains a symbolic link; rendering was refused to keep asset paths inside the project.")
        if output_mp4.is_symlink():
            raise GenerationEngineError("Render output path is a symbolic link; the existing target was preserved.")
        try:
            script = json.loads((project_dir / "script.json").read_text(encoding="utf-8"))
            lines_info = json.loads((project_dir / "data" / "lines.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GenerationEngineError(f"Narration/timing assets are missing or invalid: {exc}") from exc
        if not (project_dir / ".curioloop_project.json").is_file() or not project_dir.parent.parent.name == ".engine_projects":
            raise GenerationEngineError("Render project is missing its CurioLoop ownership marker or is outside an engine workspace.")
        output_root = project_dir.parents[2].resolve()
        try:
            output_mp4.resolve().relative_to(output_root)
        except ValueError as exc:
            raise GenerationEngineError(f"Output path must remain inside the prepared project root {output_root}.") from exc
        if output_mp4.exists():
            if resume and not force_rebuild and current_render_matches(output_mp4, project_dir):
                return output_mp4
            if not force_rebuild:
                raise GenerationEngineError("An existing MP4 is not bound to this exact script. It was preserved; choose a new video ID or explicitly request force_rebuild.")
        try:
            duration = float(lines_info.get("duration") or 0)
        except (TypeError, ValueError) as exc:
            raise GenerationEngineError("Narration duration metadata is not numeric.") from exc
        try:
            max_duration = min(HARD_MAX_DURATION_SEC, float(os.environ.get("CURIOLOOP_RENDER_MAX_DURATION_SEC", "180")))
        except ValueError as exc:
            raise GenerationEngineError("CURIOLOOP_RENDER_MAX_DURATION_SEC must be a number.") from exc
        if not math.isfinite(max_duration) or not MIN_DURATION_SEC <= duration <= max_duration:
            raise GenerationEngineError(f"Narration duration {duration:.1f}s is outside CurioLoop's {MIN_DURATION_SEC}-{max_duration:.0f}s render safety range.")
        _synchronize_storyboard_timing(project_dir)
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        temp_root = Path(os.environ.get("CURIOLOOP_RENDER_TMP_DIR") or (Path(tempfile.gettempdir()) / "curioloop-render"))
        temp_root.mkdir(parents=True, exist_ok=True)
        _cleanup_stale_capture_dirs(temp_root)
        _cleanup_stale_output_stages(output_mp4.parent)
        try:
            min_free = int(float(os.environ.get("CURIOLOOP_RENDER_MIN_FREE_GB", "5")) * (1024 ** 3))
            max_temp = int(float(os.environ.get("CURIOLOOP_RENDER_MAX_TMP_GB", "8")) * (1024 ** 3))
        except (ValueError, OverflowError) as exc:
            raise GenerationEngineError("Render disk-space limits must be valid positive numbers of GiB.") from exc
        if min_free < 0 or max_temp <= 0 or max_temp > HARD_MAX_TEMP_BYTES:
            raise GenerationEngineError("Render disk-space limits must be non-negative and temporary storage cannot exceed the 16 GiB hard cap.")
        used_temp = _renderer_temp_bytes(temp_root) + _renderer_stage_bytes(output_mp4.parent)
        estimated_temp = int((0.5 + duration * 0.01) * (1024 ** 3))
        if used_temp + estimated_temp > max_temp:
            raise GenerationEngineError(f"Render temp preflight needs about {estimated_temp / 1024**3:.1f} GiB plus {used_temp / 1024**3:.1f} GiB already in use; configured hard cap is {max_temp / 1024**3:.1f} GiB.")
        free = shutil.disk_usage(temp_root).free
        try:
            output_min_free = int(float(os.environ.get("CURIOLOOP_RENDER_MIN_OUTPUT_FREE_GB", "2")) * (1024 ** 3))
        except (ValueError, OverflowError) as exc:
            raise GenerationEngineError("CURIOLOOP_RENDER_MIN_OUTPUT_FREE_GB must be a valid number of GiB.") from exc
        output_free = shutil.disk_usage(output_mp4.parent).free
        if output_min_free < 0:
            raise GenerationEngineError("CURIOLOOP_RENDER_MIN_OUTPUT_FREE_GB cannot be negative.")
        if free < max(min_free, estimated_temp):
            raise GenerationEngineError(f"Insufficient free space at render temp directory {temp_root}: need at least {max(min_free, estimated_temp) / 1024**3:.1f} GiB; {free / 1024**3:.1f} GiB available.")
        if output_free < output_min_free:
            raise GenerationEngineError(f"Insufficient free space for staged MP4 output at {output_mp4.parent}: {output_free / 1024**3:.1f} GiB free.")
        try:
            timeout = int(float(os.environ.get("CURIOLOOP_RENDER_TIMEOUT_SEC", "3000")))
        except (ValueError, OverflowError) as exc:
            raise GenerationEngineError("CURIOLOOP_RENDER_TIMEOUT_SEC must be a number of seconds.") from exc
        if not 30 <= timeout <= 7200:
            raise GenerationEngineError("Render timeout must be between 30 seconds and the 2-hour hard limit.")
        wav = project_dir / "data" / "mix.wav"
        mix_script = project_dir / "tools" / "mix.py"
        owned_temp = temp_root / f"curioloop-render-{uuid.uuid4().hex}"
        owned_temp.mkdir(parents=True, exist_ok=False)
        env = os.environ.copy()
        owner_file = owned_temp / "owner.json"
        stage_mp4 = output_mp4.with_name(f".curioloop-render-stage-{uuid.uuid4().hex}.mp4")
        stage_owner_file = stage_mp4.with_suffix(stage_mp4.suffix + ".owner.json")
        norm_wav: Optional[Path] = None
        try:
            owner_file.write_text(json.dumps({"owner": "curioloop_render_temp", "pid": os.getpid(), "created_at": time.time(), "stage_path": str(stage_mp4)}), encoding="utf-8")
            stage_owner_file.write_text(json.dumps({"owner": "curioloop_render_stage", "pid": os.getpid(), "created_at": time.time(), "temp_path": str(owned_temp)}), encoding="utf-8")
        except OSError as exc:
            shutil.rmtree(owned_temp, ignore_errors=True)
            stage_owner_file.unlink(missing_ok=True)
            raise GenerationEngineError(f"Could not create render ownership markers: {exc}") from exc
        ffmpeg_dir = str(Path(self.ffmpeg).resolve().parent)
        env.update({"CHROME": str(self.chrome), "CURIOLOOP_FFMPEG": str(self.ffmpeg),
                    "PATH": ffmpeg_dir + os.pathsep + env.get("PATH", ""),
                    "FPS": "30", "SOFTWARE_GL": "1", "QS": "&res=0.6&aa=0&shadow=512",
                    "CURIOLOOP_RENDER_TMP_DIR": str(owned_temp), "CURIOLOOP_STAGE_OWNER_FILE": str(stage_owner_file),
                    "CURIOLOOP_STAGE_MP4": str(stage_mp4),
                    "CURIOLOOP_ALLOWED_STAGE_MP4": str(stage_mp4.resolve()),
                    "TEMP": str(owned_temp), "TMP": str(owned_temp), "TMPDIR": str(owned_temp)})
        node_capture = project_dir / "tools" / "capture.mjs"
        log = project_dir / "data" / "render.log"
        try:
            logger.info("Render disk preflight passed: temp=%s used=%.2f GiB / cap=%.2f GiB, output_free=%.2f GiB",
                        temp_root, used_temp / 1024**3, max_temp / 1024**3, output_free / 1024**3)
            # The mixer reads narration.wav and optional cues.json to create mix.wav.
            # Create its narration/ambience base before cue capture; otherwise checking
            # for mix.wav here makes a clean new project impossible to render.
            if (not wav.is_file() or wav.stat().st_size < 10_000) and mix_script.is_file():
                self._run_capture([sys.executable, str(mix_script), str(project_dir)], project_dir, env, log,
                                  min(timeout, 300), "base narration sound mix", max_temp)
            if not wav.is_file() or wav.stat().st_size < 10_000:
                raise GenerationEngineError("Narration sound mix is missing; the bundled mixer could not prepare it.")
            self._run_capture([self.node, str(node_capture), "cues"], project_dir, env, log, min(timeout, 300), "scene and SFX cue capture", max_temp)
            if mix_script.is_file():
                self._run_capture([sys.executable, str(mix_script), str(project_dir)], project_dir, env, log, min(timeout, 300), "procedural sound design mix", max_temp)
            norm_wav = owned_temp / f"mix-{uuid.uuid4().hex}.normalized.wav"
            self._run_capture([self.ffmpeg, "-v", "error", "-y", "-i", str(wav), "-af", "loudnorm=I=-16:TP=-1.5:LRA=7:linear=true", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(norm_wav)], project_dir, env, log, min(timeout, 300), "EBU R128 audio normalization", max_temp)
            if not norm_wav.is_file() or norm_wav.stat().st_size < 10_000:
                raise GenerationEngineError("FFmpeg loudness normalization produced no usable mix.")
            self._run_capture([self.node, str(node_capture), "check"], project_dir, env, log,
                              min(timeout, 600), "narrative scene and browser error preflight", max_temp)
            render_env = env.copy()
            render_env["CURIOLOOP_MIX_AUDIO"] = str(norm_wav.resolve())
            render_env["CURIOLOOP_ALLOWED_MIX_AUDIO"] = str(norm_wav.resolve())
            self._run_capture([self.node, str(node_capture), "video", str(stage_mp4)], project_dir, render_env, log, timeout, "Chromium/Three.js/FFmpeg video render", max_temp)
            metadata = validate_rendered_mp4(stage_mp4, expected_duration=duration, min_bytes=40_000)
            if metadata["width"] != 1080 or metadata["height"] != 1920:
                raise GenerationEngineError(f"Rendered geometry is {metadata['width']}x{metadata['height']}, expected 1080x1920.")
            if abs(float(metadata.get("fps") or 0) - 30.0) > 0.05:
                raise GenerationEngineError(f"Rendered frame rate is {metadata.get('fps')} FPS, expected 30 FPS.")
            # os.replace commits the fully validated staged file atomically and preserves the
            # previous deliverable if capture or validation fails.
            os.replace(stage_mp4, output_mp4)
            write_render_manifest(output_mp4, project_dir, metadata)
            logger.info("Rendered verified Cartoon 3D MP4: %s (%s bytes, %.2fs, %sx%s)", output_mp4, metadata["size_bytes"], metadata["duration"], metadata["width"], metadata["height"])
            return output_mp4
        except subprocess.TimeoutExpired as exc:
            raise GenerationEngineError(f"Render stage timed out ({exc.cmd}).") from exc
        except Exception as exc:
            tail = log.read_text(encoding="utf-8", errors="replace")[-2500:] if log.exists() else ""
            raise GenerationEngineError(f"Cartoon render failed; prior deliverables were preserved. {exc}\n{tail}") from exc
        finally:
            try:
                stage_owner = json.loads(stage_owner_file.read_text(encoding="utf-8")) if stage_owner_file.is_file() else {}
                active_stage_process = any(
                    int(stage_owner.get(key, 0) or 0) != os.getpid() and _alive(int(stage_owner.get(key, 0) or 0))
                    for key in ("pid", "node_pid", "browser_pid")
                )
            except (OSError, ValueError, json.JSONDecodeError):
                active_stage_process = True
            if active_stage_process:
                logger.warning("Leaving staged MP4 and owner marker because a render process may still be using them: %s", stage_mp4)
            else:
                if stage_mp4.exists():
                    stage_mp4.unlink(missing_ok=True)
                stage_owner_file.unlink(missing_ok=True)
            # This path is newly created for this call, inside the configured temp root.
            if owned_temp.exists() and owned_temp.resolve().parent == temp_root.resolve():
                try:
                    if not owner_file.is_file() or owner_file.is_symlink():
                        raise ValueError("render temp owner marker is missing")
                    owner = json.loads(owner_file.read_text(encoding="utf-8"))
                    if owner.get("owner") != "curioloop_render_temp" or int(owner.get("pid", 0)) != os.getpid():
                        raise ValueError("render temp ownership marker does not match this process")
                    active = any(_alive(int(owner.get(key, 0) or 0)) for key in ("node_pid", "browser_pid"))
                    if active:
                        logger.warning("Leaving render temp directory because a Node/Chromium process may still be using it: %s", owned_temp)
                    else:
                        shutil.rmtree(owned_temp, ignore_errors=True)
                        stage_owner_file.unlink(missing_ok=True)
                except (OSError, ValueError, json.JSONDecodeError):
                    logger.warning("Leaving render temp directory because its process marker could not be verified: %s", owned_temp)

    @staticmethod
    def _run_capture(cmd: list[str], cwd: Path, env: Dict[str, str], log_path: Path,
                     timeout: int, label: str, max_temp_bytes: int) -> None:
        started = time.monotonic()
        peak_temp_bytes = 0
        with log_path.open("a", encoding="utf-8") as out:
            out.write(f"\n--- {label} ---\n")
            proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=subprocess.STDOUT, creationflags=0x08000000 if os.name == "nt" else 0)
            try:
                while proc.poll() is None:
                    if time.monotonic() - started > timeout:
                        Cartoon3DVisualEngine._kill_tree(proc)
                        raise subprocess.TimeoutExpired(cmd, timeout)
                    tmp_path = Path(env["CURIOLOOP_RENDER_TMP_DIR"])
                    if tmp_path.exists():
                        stage_path = Path(env["CURIOLOOP_STAGE_MP4"])
                        peak_temp_bytes = max(peak_temp_bytes, _renderer_temp_bytes(tmp_path.parent) + _renderer_stage_bytes(stage_path.parent))
                    if peak_temp_bytes > max_temp_bytes:
                        Cartoon3DVisualEngine._kill_tree(proc)
                        raise GenerationEngineError(f"Render temporary storage exceeded configured {max_temp_bytes / 1024**3:.1f} GiB cap.")
                    owner_path = tmp_path / "owner.json"
                    stage_owner = env.get("CURIOLOOP_STAGE_OWNER_FILE")
                    if owner_path.is_file() and stage_owner:
                        try:
                            owner = json.loads(owner_path.read_text(encoding="utf-8"))
                            stage = json.loads(Path(stage_owner).read_text(encoding="utf-8"))
                            stage.update({key: owner[key] for key in ("node_pid", "browser_pid") if key in owner})
                            Path(stage_owner).write_text(json.dumps(stage), encoding="utf-8")
                        except (OSError, ValueError, json.JSONDecodeError):
                            pass
                    time.sleep(2)
            finally:
                if proc.poll() is None:
                    Cartoon3DVisualEngine._kill_tree(proc)
                    proc.wait(timeout=10)
        temp_path = Path(env["CURIOLOOP_RENDER_TMP_DIR"])
        if temp_path.exists():
            stage_path = Path(env["CURIOLOOP_STAGE_MP4"])
            peak_temp_bytes = max(peak_temp_bytes, _renderer_temp_bytes(temp_path.parent) + _renderer_stage_bytes(stage_path.parent))
        if peak_temp_bytes > max_temp_bytes:
            raise GenerationEngineError(f"Render temporary storage exceeded configured {max_temp_bytes / 1024**3:.1f} GiB cap.")
        with log_path.open("a", encoding="utf-8") as out:
            out.write(f"render_temp_peak_bytes={peak_temp_bytes}\n")
        if proc.returncode != 0:
            raise GenerationEngineError(f"{label} exited with status {proc.returncode}.")

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("taskkill could not terminate renderer process tree %s: %s", proc.pid, exc)
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise GenerationEngineError(f"Renderer process {proc.pid} is still active after termination attempts; its temp files were retained.") from exc
        else:
            proc.kill()
