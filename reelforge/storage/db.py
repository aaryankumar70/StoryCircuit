"""Thread-safe SQLite database for jobs, custom multi-day plans, and topic history."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from reelforge import config
from reelforge.storage.dedup import find_similar_match, normalize_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReelDatabase:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or config.DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    scheduled_date TEXT,
                    slot_num INTEGER,
                    source_mode TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    style TEXT NOT NULL,
                    script_text TEXT NOT NULL,
                    storyboard_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    video_path TEXT,
                    qc_json TEXT,
                    progress_json TEXT,
                    youtube_id TEXT,
                    youtube_url TEXT,
                    publish_at TEXT,
                    simulated INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS topic_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    title TEXT NOT NULL,
                    norm_title TEXT NOT NULL,
                    body_text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_items (
                    id TEXT PRIMARY KEY,
                    planned_date TEXT NOT NULL,
                    slot_num INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'story',
                    style TEXT NOT NULL DEFAULT 'auto',
                    custom_script TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    job_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_date_slot ON jobs(scheduled_date, slot_num);
                CREATE INDEX IF NOT EXISTS idx_plan_date_slot ON plan_items(planned_date, slot_num, status);
                """
            )
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "progress_json" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN progress_json TEXT")
            if "video_format" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN video_format TEXT NOT NULL DEFAULT 'short'")
            if "cleaned_at" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN cleaned_at TEXT")

            pcols = {r["name"] for r in conn.execute("PRAGMA table_info(plan_items)").fetchall()}
            if "publish_time" not in pcols:
                conn.execute("ALTER TABLE plan_items ADD COLUMN publish_time TEXT NOT NULL DEFAULT ''")

    # ------------------------------------------------------------------
    # Anti-repeat history
    # ------------------------------------------------------------------
    def check_duplicate_topic(self, title: str, body_text: str = "") -> Tuple[bool, str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT title, body_text FROM topic_history ORDER BY id DESC LIMIT 500"
            ).fetchall()
        records = [(r["title"], r["body_text"]) for r in rows]
        return find_similar_match(title, body_text, records)

    def record_topic_history(
        self,
        title: str,
        body_text: str,
        category: str = "story",
        job_id: Optional[str] = None,
    ) -> None:
        now = _utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO topic_history (job_id, title, norm_title, body_text, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, title, normalize_text(title), body_text, category, now),
            )

    def list_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, job_id, title, category, created_at FROM topic_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Video jobs
    # ------------------------------------------------------------------
    def create_job(
        self,
        *,
        source_mode: str,
        title: str,
        category: str,
        style: str,
        script_text: str,
        storyboard: Dict[str, Any],
        scheduled_date: Optional[str] = None,
        slot_num: Optional[int] = None,
        status: str = "planned",
        job_id: Optional[str] = None,
        video_format: str = "short",
    ) -> str:
        jid = job_id or f"rf_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        now = _utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, scheduled_date, slot_num, source_mode, title, category, style,
                    script_text, storyboard_json, status, video_format, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    jid, scheduled_date, slot_num, source_mode, title, category, style,
                    script_text, json.dumps(storyboard, ensure_ascii=False), status, video_format, now, now,
                ),
            )
        return jid

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status", "video_path", "qc_json", "progress_json", "youtube_id", "youtube_url",
            "publish_at", "simulated", "error", "scheduled_date", "slot_num",
            "storyboard_json", "title", "style", "video_format", "cleaned_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if "qc_json" in updates and isinstance(updates["qc_json"], dict):
            updates["qc_json"] = json.dumps(updates["qc_json"], ensure_ascii=False)
        if "progress_json" in updates and isinstance(updates["progress_json"], dict):
            updates["progress_json"] = json.dumps(updates["progress_json"], ensure_ascii=False)
        if "storyboard_json" in updates and isinstance(updates["storyboard_json"], dict):
            updates["storyboard_json"] = json.dumps(updates["storyboard_json"], ensure_ascii=False)
        updates["updated_at"] = _utc_now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [job_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", vals)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._decode_job(row) if row else None

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode_job(r) for r in rows]

    def delete_job(self, job_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def mark_job_cleaned(self, job_id: str) -> None:
        now = _utc_now()
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET video_path = NULL, cleaned_at = ?, updated_at = ? WHERE id = ?",
                (now, now, job_id),
            )

    def recover_interrupted_jobs(self) -> int:
        """Reset any jobs left in active state by an unexpected crash/restart."""
        now = _utc_now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = 'Interrupted by server restart — click Retry to regenerate.',
                    updated_at = ?
                WHERE status IN ('rendering', 'uploading')
                """,
                (now,),
            )
            return int(cur.rowcount or 0)

    def get_jobs_for_date(self, date_str: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE scheduled_date = ? ORDER BY slot_num ASC, created_at ASC",
                (date_str,),
            ).fetchall()
        return [self._decode_job(r) for r in rows]

    def count_live_uploads_for_date(self, date_str: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM jobs
                WHERE scheduled_date = ? AND simulated = 0 AND status IN ('uploaded', 'scheduled')
                """,
                (date_str,),
            ).fetchone()
        return int(row["cnt"]) if row else 0

    def claimed_youtube_ids(self) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT youtube_id FROM jobs WHERE youtube_id IS NOT NULL AND youtube_id != ''"
            ).fetchall()
        return {str(r["youtube_id"]) for r in rows}

    @staticmethod
    def _decode_job(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["storyboard"] = json.loads(d.get("storyboard_json") or "{}")
        except json.JSONDecodeError:
            d["storyboard"] = {}
        try:
            d["qc"] = json.loads(d.get("qc_json") or "{}") if d.get("qc_json") else None
        except json.JSONDecodeError:
            d["qc"] = None
        try:
            d["progress"] = json.loads(d.get("progress_json") or "{}") if d.get("progress_json") else None
        except json.JSONDecodeError:
            d["progress"] = None
        return d

    # ------------------------------------------------------------------
    # Custom Multi-Day Plan Queue
    # ------------------------------------------------------------------
    def add_plan_item(
        self,
        *,
        planned_date: str,
        slot_num: int,
        topic: str,
        category: str = "story",
        style: str = "auto",
        custom_script: str = "",
        notes: str = "",
        publish_time: str = "",
    ) -> str:
        pid = f"plan_{uuid.uuid4().hex[:10]}"
        now = _utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO plan_items (
                    id, planned_date, slot_num, publish_time, topic, category, style,
                    custom_script, notes, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    pid, planned_date, int(slot_num), publish_time.strip(),
                    topic.strip(), category, style, custom_script.strip(), notes.strip(), now, now,
                ),
            )
        return pid

    def list_plan_items(self, status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM plan_items WHERE status = ? ORDER BY planned_date ASC, slot_num ASC, publish_time ASC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM plan_items ORDER BY planned_date ASC, slot_num ASC, publish_time ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_plan_item(self, plan_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM plan_items WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def get_due_plan_item(self, planned_date: str, slot_num: int) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM plan_items
                WHERE planned_date <= ? AND slot_num = ? AND status = 'pending'
                ORDER BY planned_date ASC, publish_time ASC LIMIT 1
                """,
                (planned_date, slot_num),
            ).fetchone()
        return dict(row) if row else None

    def update_plan_item(self, plan_id: str, **fields: Any) -> None:
        allowed = {"status", "job_id", "planned_date", "slot_num", "publish_time", "topic", "category", "style", "custom_script", "notes"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _utc_now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [plan_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE plan_items SET {cols} WHERE id = ?", vals)

    def delete_plan_item(self, plan_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM plan_items WHERE id = ?", (plan_id,))
