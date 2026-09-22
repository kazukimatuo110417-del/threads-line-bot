import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from config import get_settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> Path:
    path = Path(get_settings().database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS candidate_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidates_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                target_category TEXT NOT NULL,
                post_category TEXT NOT NULL,
                posted_at TEXT NOT NULL,
                threads_post_id TEXT NOT NULL,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                analysis_score REAL NOT NULL DEFAULT 0,
                last_metrics_at TEXT
            );
            """
        )


def get_state(key: str, default: Any = None) -> Any:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return json.loads(row["value"])


def set_state(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, payload, utc_now_iso()),
        )


def save_candidate_batch(candidates: list[dict[str, str]]) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO candidate_batches (candidates_json, created_at) VALUES (?, ?)",
            (json.dumps(candidates, ensure_ascii=False), utc_now_iso()),
        )
        return int(cur.lastrowid)


def get_candidate_batch(batch_id: int) -> list[dict[str, str]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT candidates_json FROM candidate_batches WHERE id = ?", (batch_id,)
        ).fetchone()
    if row is None:
        return []
    return json.loads(row["candidates_json"])


def save_post(
    body: str,
    target_category: str,
    post_category: str,
    threads_post_id: str,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO posts
                (body, target_category, post_category, posted_at, threads_post_id, metrics_json)
            VALUES (?, ?, ?, ?, ?, '{}')
            """,
            (body, target_category, post_category, utc_now_iso(), threads_post_id),
        )
        return int(cur.lastrowid)


def list_posts(limit: int = 50) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM posts ORDER BY posted_at DESC LIMIT ?", (limit,)
        ).fetchall()


def list_posts_for_metrics() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM posts ORDER BY posted_at DESC").fetchall()


def update_post_metrics(post_id: int, metrics: dict[str, int], score: float) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE posts
            SET metrics_json = ?, analysis_score = ?, last_metrics_at = ?
            WHERE id = ?
            """,
            (json.dumps(metrics, ensure_ascii=False), score, utc_now_iso(), post_id),
        )
