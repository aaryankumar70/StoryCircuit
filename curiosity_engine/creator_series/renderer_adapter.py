"""Renderer Adapter for CurioLoop Creator Series.

Bridges cinematic storyboards to CurioLoop's existing headless Chrome
Canvas renderer without introducing new engines or paid APIs.

Translates:
- Storyboard palette -> CSS variables / Canvas palette colors
- Camera specifications -> 2D zoom/pan/drift coordinates
- Lighting & atmosphere -> Canvas radial gradients, vignettes, and particle layers
- Scene durations -> lines.json timing structures
- Unsupported generative features -> Graceful documented downgrades
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curiosity_engine.config import OUTPUT_DIR, TEMPLATES_DIR
from curiosity_engine.production.aligner import align_narration_words
from curiosity_engine.production.tts_engine import synthesize_narration

logger = logging.getLogger("curiosity_engine.renderer_adapter")


class RendererAdapter:
    """Adapts high-level cinematic storyboards to low-level browser canvas templates."""

    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or TEMPLATES_DIR

    def translate_storyboard_to_script_data(
        self,
        storyboard: Dict[str, Any],
        bible: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Map storyboard scenes and visual bible into CurioLoop script.json format.
        Returns (script_data, applied_downgrades).
        """
        applied_downgrades: List[str] = []
        scenes = storyboard.get("scenes", [])
        palette_info = bible.get("visual_identity", {}).get("palette", {})
        colors = {c["role"]: c["hex"] for c in palette_info.get("colors", [])}

        # Build lines array for audio synthesis and alignment
        lines = []
        for s in scenes:
            narration = s.get("narration", {})
            text = narration.get("text", "").strip()
            if not text:
                continue

            shot = s.get("shot", {})
            camera = s.get("camera_movement", {})
            lighting = s.get("lighting", {})

            # Graceful downgrade checks
            cam_type = camera.get("type", "static")
            if cam_type in ("orbit", "3d_crane", "handheld_shake"):
                applied_downgrades.append(
                    f"Downgraded camera move '{cam_type}' to 2D slow push/drift in scene {s.get('scene_id')}"
                )

            # Map camera zoom
            zoom_val = 0.08 if cam_type == "slow_push" else 0.04

            lines.append({
                "text": text,
                "scene": {
                    "headline": s.get("location_id", "").replace("loc_", "").replace("_", " ").upper(),
                    "sublabel": s.get("narrative_purpose", "")[:35].upper(),
                    "visual_type": "archive_map" if s.get("tension_level", 5) < 6 else "vault_mystery",
                    "mood": "tense",
                    "accent": "crimson",
                    "zoom": zoom_val,
                    "lighting": lighting.get("contrast", "high"),
                    "palette": {
                        "dominant": colors.get("shadow", "#0B0F12"),
                        "practical": colors.get("practical_light", "#C9B27A"),
                    },
                },
            })

        script_data = {
            "id": f"{storyboard.get('series_id')}_{storyboard.get('episode_number')}",
            "title": storyboard.get("title"),
            "topic": storyboard.get("title"),
            "category": "CreatorSeries",
            "style": "paper-atlas",  # Reuses existing dark archival paper-atlas renderer
            "visual_profile": storyboard.get("profile", "psychological_horror"),
            "lines": lines,
        }

        return script_data, applied_downgrades

    def prepare_creator_project(
        self,
        project_id: str,
        storyboard: Dict[str, Any],
        bible: Dict[str, Any],
        output_dir: Optional[Path] = None,
    ) -> Tuple[Path, List[str]]:
        """Stage project folder with template, adapted script.json, voice, and word alignment."""
        base_out = output_dir or OUTPUT_DIR
        project_dir = base_out / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)

        # Re-use paper-atlas template structure
        template_dir = self.templates_dir / "paper-atlas"
        shutil.copytree(template_dir, project_dir, dirs_exist_ok=True)

        # Translate storyboard & save script.json
        script_data, downgrades = self.translate_storyboard_to_script_data(storyboard, bible)
        with open(project_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump(script_data, f, indent=2)

        # Save raw storyboard and bible for QC auditing
        with open(project_dir / "storyboard.json", "w", encoding="utf-8") as f:
            json.dump(storyboard, f, indent=2)
        with open(project_dir / "visual_bible.json", "w", encoding="utf-8") as f:
            json.dump(bible, f, indent=2)

        # If visual_profile is psychological_horror, inject dedicated dark cinematic renderer
        profile = storyboard.get("profile", bible.get("profile"))
        if profile == "psychological_horror":
            self._inject_horror_scenes_renderer(project_dir)

        logger.info(f"Creator series project staged at {project_dir}.")
        return project_dir, downgrades

    def _inject_horror_scenes_renderer(self, project_dir: Path) -> None:
        """Inject dark, eerie psychological horror scene choreographer into the project copy."""
        horror_scenes_js = '''// Psychological Horror Scene Choreographer for CurioLoop Creator Series
import { ctx, W, H, TAU, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line } from './lib.js';
import { L } from './timing.js';

const PALETTE = {
  shadow: '#0B0F12',
  base: '#1B2429',
  midtone: '#3A4A4F',
  highlight: '#6F7F84',
  accent: '#A9B4B0',
  practical: '#C9B27A',
};

function drawVignette() {
  const g = ctx.createRadialGradient(W / 2, H / 2, 350, W / 2, H / 2, 1100);
  g.addColorStop(0, 'rgba(11, 15, 18, 0)');
  g.addColorStop(0.7, 'rgba(11, 15, 18, 0.65)');
  g.addColorStop(1, 'rgba(0, 0, 0, 0.95)');
  ctx.fillStyle = g;
  ctx.fillRect(-300, -300, W + 600, H + 600);
}

function drawHorrorStage(vt, lt, d, t, sc, idx, total) {
  // Base background in deep dark charcoal
  ctx.fillStyle = PALETTE.shadow;
  ctx.fillRect(-300, -300, W + 600, H + 600);

  const cy = 820;

  if (idx === 0) {
    // School bus interior: dark receding aisle, empty foreground seat, cold window light
    ctx.fillStyle = PALETTE.base;
    ctx.beginPath();
    ctx.moveTo(180, 1180); ctx.lineTo(460, 680); ctx.lineTo(620, 680); ctx.lineTo(900, 1180);
    ctx.closePath();
    ctx.fill();

    // Cold window light shafts from left
    const lg = ctx.createLinearGradient(100, 500, 600, 1100);
    lg.addColorStop(0, 'rgba(111, 127, 132, 0.22)');
    lg.addColorStop(1, 'rgba(11, 15, 18, 0)');
    ctx.fillStyle = lg;
    ctx.beginPath();
    ctx.moveTo(120, 520); ctx.lineTo(540, 520); ctx.lineTo(780, 1150); ctx.lineTo(240, 1150);
    ctx.closePath();
    ctx.fill();

    // Empty seat foreground left (motif_empty_seat)
    ctx.fillStyle = '#1D2A2B';
    rr(140, 780, 260, 360, 16); ctx.fill();
    ctx.strokeStyle = PALETTE.midtone; ctx.lineWidth = 4; ctx.stroke();

    // Silhouettes of seated children several rows back
    for (let c = 0; c < 3; c++) {
      const bx = 450 + c * 70, by = 680 - c * 8;
      circle(bx, by, 16, '#0B0F12');
      rr(bx - 22, by + 12, 44, 48, 8); ctx.fillStyle = '#0B0F12'; ctx.fill();
    }
  } else if (idx === total - 1) {
    // Threshold hallway: pure negative space, figure centered back to camera, cracked door light
    const stripX = 580;
    const dg = ctx.createRadialGradient(stripX, cy, 10, stripX, cy, 320);
    dg.addColorStop(0, 'rgba(201, 178, 122, 0.85)');
    dg.addColorStop(0.3, 'rgba(201, 178, 122, 0.35)');
    dg.addColorStop(1, 'rgba(11, 15, 18, 0)');
    ctx.fillStyle = dg;
    ctx.fillRect(stripX - 250, 480, 500, 680);

    // Vertical slit of practical tungsten light
    ctx.fillStyle = PALETTE.practical;
    rr(stripX - 6, 540, 14, 520, 4); ctx.fill();

    // Narrator back to camera in lower center
    ctx.fillStyle = '#050709';
    circle(540, 890, 48);
    rr(450, 940, 180, 240, 24); ctx.fill();
  } else {
    // Friend's kitchen: single overhead practical lamp cone onto wooden table
    const lampX = 540, lampY = 560;
    const cone = ctx.createRadialGradient(lampX, lampY, 30, lampX, lampY + 280, 360);
    cone.addColorStop(0, 'rgba(201, 178, 122, 0.65)');
    cone.addColorStop(0.6, 'rgba(201, 178, 122, 0.18)');
    cone.addColorStop(1, 'rgba(11, 15, 18, 0)');
    ctx.fillStyle = cone;
    ctx.beginPath();
    ctx.moveTo(lampX, lampY);
    ctx.lineTo(840, 1140);
    ctx.lineTo(240, 1140);
    ctx.closePath();
    ctx.fill();

    // Overhead lamp bulb
    circle(lampX, lampY, 14, PALETTE.practical);
    line([[lampX, 350], [lampX, lampY]], PALETTE.highlight, 3);

    // Wooden table surface beneath
    ctx.fillStyle = '#181E21';
    rr(220, 960, 640, 180, 12); ctx.fill();
    ctx.strokeStyle = PALETTE.midtone; ctx.lineWidth = 3; ctx.stroke();

    // Friend seated opposite in shadow
    ctx.fillStyle = '#0B0F12';
    circle(lampX, 810, 54);
    rr(lampX - 70, 866, 140, 140, 18); ctx.fill();
    ctx.strokeStyle = '#384836'; ctx.lineWidth = 14; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(lampX - 35, 876); ctx.lineTo(lampX + 35, 876); ctx.stroke();
  }

  // Floating dust motes in the stillness
  for (let i = 0; i < 18; i++) {
    const bx = 160 + rnd(i + 3) * 760;
    const by = 1120 - ((t * 40 + rnd(i * 3) * 600) % 650);
    circle(bx, by, 3 + rnd(i) * 3, 'rgba(169, 180, 176, 0.35)');
  }

  // Deep shadow vignette
  drawVignette();

  // Dark stylized HUD / header ribbons (in safe zone >=250)
  const prog = eob(seg(lt, 0.08, 0.36));
  if (sc.headline) {
    ctx.save();
    ctx.globalAlpha = 0.88 * prog;
    ctx.fillStyle = '#10171B';
    rr(340, 276, 400, 52, 10); ctx.fill();
    ctx.strokeStyle = PALETTE.midtone; ctx.lineWidth = 2; ctx.stroke();
    ctx.font = '800 24px Inter'; ctx.fillStyle = PALETTE.accent;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.letterSpacing = '2px';
    ctx.fillText(String(sc.headline).toUpperCase().slice(0, 26), 540, 303);
    ctx.restore();
  }

  // Eerie tension meter strip
  const barW = 580, bx = (W - barW) / 2;
  ctx.fillStyle = 'rgba(27, 36, 41, 0.6)'; rr(bx, 240, barW, 4, 2); ctx.fill();
  ctx.fillStyle = PALETTE.practical;
  rr(bx, 240, Math.max(10, barW * ((idx + clamp(lt / Math.max(0.2, d))) / Math.max(1, total))), 4, 2); ctx.fill();
}

export function buildDynamicStoryShots(script) {
  const S = [], CUES = [];
  const lines = Array.isArray(script?.lines) ? script.lines : [];
  const total = lines.length;
  lines.forEach((ln, i) => {
    const at = i === 0 ? 0 : Math.max(0, L(i) - 0.08);
    const sc = ln.scene || {};
    const vt = sc.visual_type || 'archive_map';
    const zoom = sc.zoom || 0.04;
    S.push({
      id: `S${String(i + 1).padStart(2, '0')}`,
      at,
      cam: [540, 840],
      zoom,
      note: `${vt}: ${sc.headline || ln.text.slice(0, 40)}`,
      draw(lt, d, t) {
        drawHorrorStage(vt, lt, d, t, sc, i, total);
      }
    });
  });
  return { shots: S, cues: CUES };
}
'''
        scenes_file = project_dir / "src" / "core" / "scenes.js"
        scenes_file.write_text(horror_scenes_js, encoding="utf-8")
        logger.info(f"Injected psychological horror scenes choreographer into {scenes_file}")


renderer_adapter = RendererAdapter()
