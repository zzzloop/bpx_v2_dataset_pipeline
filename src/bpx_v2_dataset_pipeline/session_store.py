from __future__ import annotations

import pathlib
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from bpx_v2_dataset_pipeline.models import AttemptMetadata, AttemptStatus


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    """Durable monotonic attempt registry backed by SQLite."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_en TEXT NOT NULL,
                    task_zh TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    layout_id TEXT NOT NULL,
                    embodiment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT NOT NULL,
                    failure_reason TEXT NOT NULL DEFAULT '',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    ended_at TEXT
                )
                """
            )

    def recover_interrupted(self) -> int:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE attempts SET status = ?, ended_at = ? WHERE status = ?",
                (AttemptStatus.INTERRUPTED, _utc_now(), AttemptStatus.RECORDING),
            )
            return cursor.rowcount

    def begin_attempt(self, metadata: AttemptMetadata) -> int:
        values = asdict(metadata)
        values["embodiment"] = metadata.embodiment.value
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO attempts (
                    session_id, task_en, task_zh, operator_id, layout_id,
                    embodiment, status, note, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["session_id"],
                    values["task_en"],
                    values["task_zh"],
                    values["operator_id"],
                    values["layout_id"],
                    values["embodiment"],
                    AttemptStatus.RECORDING,
                    values["note"],
                    _utc_now(),
                ),
            )
            connection.execute("COMMIT")
            return int(cursor.lastrowid)

    def finish_attempt(
        self,
        attempt_id: int,
        status: AttemptStatus,
        *,
        failure_reason: str = "",
        note: str = "",
        artifact_path: str = "",
    ) -> None:
        if status not in {AttemptStatus.SUCCESS, AttemptStatus.FAILURE, AttemptStatus.INTERRUPTED}:
            raise ValueError(f"Invalid terminal status: {status}")
        stored_failure_reason = failure_reason.strip() if status is AttemptStatus.FAILURE else ""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE attempts
                SET status = ?, failure_reason = ?, note = ?, artifact_path = ?, ended_at = ?
                WHERE attempt_id = ? AND status = ?
                """,
                (
                    status,
                    stored_failure_reason,
                    note.strip(),
                    artifact_path,
                    _utc_now(),
                    attempt_id,
                    AttemptStatus.RECORDING,
                ),
            )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise ValueError(f"Attempt {attempt_id} is missing or no longer recording")
            connection.execute("COMMIT")

    def get_attempt(self, attempt_id: int) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        return dict(row)

    def recent_attempts(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM attempts ORDER BY attempt_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def distinct_values(self, column: str, limit: int = 50) -> list[str]:
        """Return recent non-empty values for a whitelisted UI option column."""
        if column not in {"operator_id", "layout_id"}:
            raise ValueError(f"Unsupported option column: {column}")
        if limit < 1:
            raise ValueError("limit must be positive")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {column}, MAX(attempt_id) AS latest
                FROM attempts
                WHERE {column} != ''
                GROUP BY {column}
                ORDER BY latest DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [str(row[column]) for row in rows]
