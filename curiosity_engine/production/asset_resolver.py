"""CurioLoop 2.0 Asset Manifest Resolver.
Provides canonical alias resolution, path validation, and procedural fallback generation
to guarantee zero-crash asset loading during 2.5D visual rendering.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "cinematic-hybrid" / "assets"

CANONICAL_ALIASES: Dict[str, str] = {
    "gyro": "mystery/gyro_compass.svg",
    "gyro.svg": "mystery/gyro_compass.svg",
    "gyro_compass": "mystery/gyro_compass.svg",
    "dossier": "mystery/dossier_folder.svg",
    "dossier.svg": "mystery/dossier_folder.svg",
    "dossier_folder": "mystery/dossier_folder.svg",
    "bomber": "mystery/avenger_bomber_silhouette.svg",
    "bomber.svg": "mystery/avenger_bomber_silhouette.svg",
    "avenger_bomber": "mystery/avenger_bomber_silhouette.svg",
    "empty_frame": "history/empty_museum_frame.svg",
    "empty_frame.svg": "history/empty_museum_frame.svg",
    "empty_museum_frame": "history/empty_museum_frame.svg",
    "wax_seal": "history/wax_seal.svg",
    "wax_seal.svg": "history/wax_seal.svg",
    "seal": "history/wax_seal.svg",
    "radar": "extraterrestrial/radar_ppi_scope.svg",
    "radar.svg": "extraterrestrial/radar_ppi_scope.svg",
    "radar_ppi_scope": "extraterrestrial/radar_ppi_scope.svg",
    "telescope": "extraterrestrial/radio_telescope_array.svg",
    "telescope.svg": "extraterrestrial/radio_telescope_array.svg",
    "radio_telescope": "extraterrestrial/radio_telescope_array.svg",
    "ocean": "dimensional-scenes/ocean_depth_stack.svg",
    "ocean_depth": "dimensional-scenes/ocean_depth_stack.svg",
    "forest": "dimensional-scenes/forest_depth_stack.svg",
    "forest_depth": "dimensional-scenes/forest_depth_stack.svg",
}


class AssetManifestResolver:
    """Centralized asset resolver ensuring deterministic, crash-free asset paths."""

    def __init__(self, base_assets_dir: Optional[Path] = None):
        self.base_dir = base_assets_dir or TEMPLATES_DIR

    def resolve(self, asset_ref: str, category: str = "MYSTERY") -> Path:
        """Resolves an asset reference or relative filename to a verified local Path.
        If missing, generates a fallback SVG procedural asset.
        """
        ref_clean = asset_ref.strip().replace("\\", "/").lower()
        if ref_clean.startswith("assets/"):
            ref_clean = ref_clean[len("assets/") :]

        # 1. Check canonical alias map
        if ref_clean in CANONICAL_ALIASES:
            target = self.base_dir / CANONICAL_ALIASES[ref_clean]
            if target.exists():
                return target

        # 2. Direct path relative to base_dir
        direct = self.base_dir / ref_clean
        if direct.exists() and direct.is_file():
            return direct

        # 3. Check within category subdirectory
        cat_sub = category.strip().lower()
        cat_candidate = self.base_dir / cat_sub / ref_clean
        if cat_candidate.exists() and cat_candidate.is_file():
            return cat_candidate

        # 4. Search recursively for matching filename
        filename = Path(ref_clean).name
        matches = list(self.base_dir.rglob(filename))
        if matches:
            return matches[0]

        # 5. Fallback procedural generator if asset is missing
        logger.warning(
            "Asset '%s' not found under %s; generating procedural fallback SVG.",
            asset_ref,
            self.base_dir,
        )
        return self._generate_procedural_fallback(filename, category)

    def _generate_procedural_fallback(self, filename: str, category: str) -> Path:
        """Generates a stylish, minimalist procedural SVG when an asset is missing."""
        fallback_dir = self.base_dir / "generated_fallbacks"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = fallback_dir / f"fallback_{filename}"
        if not fallback_path.name.endswith(".svg"):
            fallback_path = fallback_path.with_suffix(".svg")

        if fallback_path.exists():
            return fallback_path

        # Generate sleek procedural vector
        stem = Path(filename).stem.upper()
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920" width="1080" height="1920">
  <defs>
    <radialGradient id="bgGrad" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#141c2b" stop-opacity="0.8"/>
      <stop offset="100%" stop-color="#070a10" stop-opacity="0.95"/>
    </radialGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="6" result="coloredBlur"/>
      <feMerge>
        <feMergeNode in="coloredBlur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>
  <rect width="1080" height="1920" fill="url(#bgGrad)"/>
  <circle cx="540" cy="960" r="320" fill="none" stroke="#2a4365" stroke-width="2" stroke-dasharray="8 8" opacity="0.6"/>
  <circle cx="540" cy="960" r="220" fill="none" stroke="#3182ce" stroke-width="3" opacity="0.7"/>
  <line x1="540" y1="620" x2="540" y2="1300" stroke="#4299e1" stroke-width="1.5" opacity="0.4"/>
  <line x1="200" y1="960" x2="880" y2="960" stroke="#4299e1" stroke-width="1.5" opacity="0.4"/>
  <text x="540" y="970" font-family="monospace" font-size="28" fill="#e2e8f0" text-anchor="middle" letter-spacing="4" filter="url(#glow)">[{stem}]</text>
  <text x="540" y="1020" font-family="monospace" font-size="16" fill="#90cdf4" text-anchor="middle" opacity="0.7">ANOMALY TELEMETRY / {category.upper()}</text>
</svg>"""
        fallback_path.write_text(svg_content, encoding="utf-8")
        return fallback_path


# Global instance
asset_resolver = AssetManifestResolver()
