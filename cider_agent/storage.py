"""SQLite-backed persistence for cider_agent."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .errors import PreferenceStoreError


class PreferenceStore:
    """Store explicit audio preferences in SQLite."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    category TEXT,
                    value TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_preferences_unique
                ON preferences(kind, COALESCE(category, ''), value)
                """
            )

    def list_preferences(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, kind, category, value, weight, note, created_at, updated_at
                FROM preferences
                ORDER BY kind ASC, category ASC, value ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def remember_preference(
        self,
        *,
        kind: str,
        value: str,
        category: str | None = None,
        weight: float = 1.0,
        note: str | None = None,
    ) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                existing = connection.execute(
                    """
                    SELECT id FROM preferences
                    WHERE kind = ? AND COALESCE(category, '') = COALESCE(?, '') AND value = ?
                    """,
                    (kind, category, value),
                ).fetchone()
                if existing is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO preferences(kind, category, value, weight, note)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (kind, category, value, weight, note),
                    )
                    preference_id = int(cursor.lastrowid)
                else:
                    preference_id = int(existing["id"])
                    connection.execute(
                        """
                        UPDATE preferences
                        SET weight = ?, note = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (weight, note, preference_id),
                    )
        except sqlite3.Error as exc:
            raise PreferenceStoreError(f"Could not save preference: {exc}") from exc
        return self.get_preference(preference_id)

    def delete_preference(self, preference_id: int) -> bool:
        try:
            with self._connect() as connection:
                cursor = connection.execute("DELETE FROM preferences WHERE id = ?", (preference_id,))
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise PreferenceStoreError(f"Could not delete preference: {exc}") from exc

    def get_preference(self, preference_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, kind, category, value, weight, note, created_at, updated_at
                FROM preferences
                WHERE id = ?
                """,
                (preference_id,),
            ).fetchone()
        if row is None:
            raise PreferenceStoreError(f"Preference {preference_id} was not found.")
        return dict(row)
