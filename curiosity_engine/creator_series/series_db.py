"""Persistent storage layer for CurioLoop Creator Series.

Stores series metadata, episode progression, and execution status
in the local database (firestore_local.json) without disrupting
automatic video records or topic history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.state.db import DatabaseClient, db

logger = logging.getLogger("curiosity_engine.series_db")


class SeriesDatabase:
    """Manages persistent Creator Series and Episode records."""

    def __init__(self, db_client: Optional[DatabaseClient] = None):
        self._db = db_client or db

    def save_series(self, series: SeriesRecord) -> None:
        """Create or update a SeriesRecord in local storage."""
        series.updated_at = datetime.now(timezone.utc).isoformat()
        with self._db.transaction() as state:
            state.setdefault("series", {})
            state["series"][series.series_id] = series.to_dict()
        logger.info(f"Series '{series.series_id}' saved with status '{series.status}'.")

    def get_series(self, series_id: str) -> Optional[SeriesRecord]:
        """Fetch series by ID."""
        self._db._load_local_data()
        raw = self._db._local_data.get("series", {}).get(series_id)
        if not raw:
            return None
        return SeriesRecord.from_dict(raw)

    def get_all_series(self) -> List[SeriesRecord]:
        """Fetch all series records sorted by created_at desc."""
        self._db._load_local_data()
        raw_list = list(self._db._local_data.get("series", {}).values())
        records = [SeriesRecord.from_dict(r) for r in raw_list]
        records.sort(key=lambda s: s.created_at, reverse=True)
        return records

    def get_active_series(self) -> Optional[SeriesRecord]:
        """Return the currently ACTIVE series eligible for publishing, if any."""
        all_s = self.get_all_series()
        for s in all_s:
            if s.status == SeriesStatus.ACTIVE:
                return s
        return None

    def save_episode(self, episode: EpisodeRecord) -> None:
        """Create or update an EpisodeRecord in local storage."""
        episode.updated_at = datetime.now(timezone.utc).isoformat()
        with self._db.transaction() as state:
            state.setdefault("episodes", {})
            state["episodes"][episode.episode_id] = episode.to_dict()
        logger.info(f"Episode '{episode.episode_id}' saved with status '{episode.status}'.")

    def save_series_and_episodes(self, series: SeriesRecord, episodes: List[EpisodeRecord]) -> None:
        """Persist a schedule change and its episode timestamps in one file transaction."""
        now = datetime.now(timezone.utc).isoformat()
        series.updated_at = now
        for episode in episodes:
            episode.updated_at = now
        with self._db.transaction() as state:
            state.setdefault("series", {})[series.series_id] = series.to_dict()
            episode_state = state.setdefault("episodes", {})
            for episode in episodes:
                episode_state[episode.episode_id] = episode.to_dict()

    def get_episode(self, episode_id: str) -> Optional[EpisodeRecord]:
        """Fetch episode by ID."""
        self._db._load_local_data()
        raw = self._db._local_data.get("episodes", {}).get(episode_id)
        if not raw:
            return None
        return EpisodeRecord.from_dict(raw)

    def get_episodes_for_series(self, series_id: str) -> List[EpisodeRecord]:
        """Fetch all episodes belonging to a series, sorted by episode_num."""
        self._db._load_local_data()
        raw_map = self._db._local_data.get("episodes", {})
        matching = [
            EpisodeRecord.from_dict(ep)
            for ep in raw_map.values()
            if ep.get("series_id") == series_id
        ]
        matching.sort(key=lambda x: x.episode_num)
        return matching

    def get_next_eligible_episode(self, series_id: str) -> Optional[EpisodeRecord]:
        """Find the next uncompleted episode in strict sequential order.
        Never skips episodes; a failed or unready episode blocks advancement.
        """
        series = self.get_series(series_id)
        if not series or series.status != SeriesStatus.ACTIVE:
            return None

        episodes = self.get_episodes_for_series(series_id)
        if not episodes:
            return None

        # Look for the episode matching next_episode_num
        for ep in episodes:
            if ep.episode_num == series.next_episode_num:
                if ep.status not in (EpisodeStatus.PUBLISHED, EpisodeStatus.FAILED):
                    return ep
                elif ep.status == EpisodeStatus.FAILED:
                    logger.warning(
                        f"Episode {ep.episode_num} for series '{series_id}' is marked FAILED. Halting advancement."
                    )
                    return None
        return None

    def mark_episode_published(
        self,
        series_id: str,
        episode_id: str,
        youtube_id: str,
        actual_publish_time: Optional[str] = None,
    ) -> None:
        """Mark an episode published, record YouTube ID, and advance series pointer."""
        ep = self.get_episode(episode_id)
        series = self.get_series(series_id)
        if not ep or not series:
            logger.error(f"Cannot mark episode {episode_id} published: record not found.")
            return

        now_iso = actual_publish_time or datetime.now(timezone.utc).isoformat()
        ep.status = EpisodeStatus.PUBLISHED
        ep.upload_status = "PUBLISHED"
        ep.youtube_id = youtube_id
        ep.actual_publication_time = now_iso
        if episode_id not in series.published_episode_ids:
            series.published_episode_ids.append(episode_id)

        # Advance pointer to next episode
        series.next_episode_num = ep.episode_num + 1

        # Check if all planned episodes published
        total_episodes = len(series.episode_ids) or series.planned_episodes
        if ep.episode_num >= total_episodes:
            series.status = SeriesStatus.COMPLETED
            series.completion_state = {
                "completed_at": now_iso,
                "final_episode_id": episode_id,
                "final_youtube_id": youtube_id,
                "total_published": len(series.published_episode_ids),
            }
            logger.info(f"Series '{series_id}' has completed all {total_episodes} episodes!")

        self.save_series_and_episodes(series, [ep])

    def record_episode_failure(self, series_id: str, episode_id: str, reason: str) -> None:
        """Record episode failure without advancing sequence pointer."""
        ep = self.get_episode(episode_id)
        series = self.get_series(series_id)
        if ep:
            ep.status = EpisodeStatus.FAILED
            ep.retry_count += 1
        if series:
            if episode_id not in series.failed_episode_ids:
                series.failed_episode_ids.append(episode_id)
            self.save_series_and_episodes(series, [ep] if ep else [])
        logger.error(f"Recorded failure for episode '{episode_id}' (series '{series_id}'): {reason}")


series_db = SeriesDatabase()
