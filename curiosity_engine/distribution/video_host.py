"""Video Hosting Abstraction for Instagram Reels Ingestion.
Enforces strict ₹0 budget and disables unverified external providers.
Simulation mode is active by default.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from curiosity_engine.config import VIDEO_HOST_PROVIDER

logger = logging.getLogger("curiosity_engine.distribution.video_host")


class BaseVideoHost(ABC):
    """Abstract interface for video hosting required by Instagram Reels."""

    @abstractmethod
    def host_video(self, video_path: Path) -> str:
        """Provide a publicly accessible or simulated HTTPS video URL."""
        pass

    @abstractmethod
    def cleanup(self, hosted_url: str) -> None:
        """Purge hosted video after ingestion completes."""
        pass


class SimulationVideoHost(BaseVideoHost):
    """Local simulation video host for zero-cost offline verification."""

    def host_video(self, video_path: Path) -> str:
        if not video_path.exists():
            raise FileNotFoundError(f"Video file does not exist: {video_path}")
        mock_url = f"https://simulation.curioloop.local/videos/{video_path.name}"
        logger.info(f"[SIMULATION HOST] Generated simulated video ingestion URL: {mock_url}")
        return mock_url

    def cleanup(self, hosted_url: str) -> None:
        logger.info(f"[SIMULATION HOST] Cleanup called for: {hosted_url}")


class CloudflareR2VideoHost(BaseVideoHost):
    """Cloudflare R2 Video Host.
    DISABLED: Awaiting account verification, zero-cost API audit, and authorization.
    """

    def __init__(self, allow_external: bool = False):
        self.allow_external = allow_external
        if not self.allow_external:
            raise PermissionError(
                "Cloudflare R2 hosting is currently disabled pending external account verification "
                "and strict ₹0 billing validation. Keep simulation mode active."
            )

    def host_video(self, video_path: Path) -> str:
        raise NotImplementedError("Cloudflare R2 hosting is disabled.")

    def cleanup(self, hosted_url: str) -> None:
        pass


class FirebaseStorageVideoHost(BaseVideoHost):
    """Firebase Storage Spark Plan Host.
    DISABLED: Awaiting account verification and hard-cap confirmation.
    """

    def __init__(self, allow_external: bool = False):
        self.allow_external = allow_external
        if not self.allow_external:
            raise PermissionError(
                "Firebase Storage hosting is currently disabled pending external account verification "
                "and hard-cap confirmation. Keep simulation mode active."
            )

    def host_video(self, video_path: Path) -> str:
        raise NotImplementedError("Firebase Storage hosting is disabled.")

    def cleanup(self, hosted_url: str) -> None:
        pass


def get_video_host(provider: Optional[str] = None) -> BaseVideoHost:
    """Factory to retrieve configured video host. Defaults to SimulationVideoHost."""
    target_provider = (provider or VIDEO_HOST_PROVIDER or "simulation").lower()

    if target_provider == "simulation":
        return SimulationVideoHost()
    elif target_provider == "cloudflare_r2":
        return CloudflareR2VideoHost(allow_external=False)
    elif target_provider == "firebase":
        return FirebaseStorageVideoHost(allow_external=False)
    else:
        logger.warning(
            f"Unknown video host provider '{target_provider}'. Defaulting to SimulationVideoHost."
        )
        return SimulationVideoHost()
