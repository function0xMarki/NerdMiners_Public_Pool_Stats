"""
NerdMiners_Public_Pool_Stats Bot - SQLite Database Module.
Handles all persistent data storage including bot state, worker registry,
hashrate history, session tracking, and hall of fame.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DB_FILE = SCRIPT_DIR / "DB.db"


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS workers (
                internal_id TEXT PRIMARY KEY,
                api_name TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_session_id TEXT,
                last_hashrate REAL DEFAULT 0,
                last_start_time TEXT,
                last_best_diff REAL DEFAULT 0,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS hashrate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id TEXT NOT NULL,
                hashrate REAL NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (worker_id) REFERENCES workers(internal_id)
            );

            CREATE INDEX IF NOT EXISTS idx_hashrate_worker_time
                ON hashrate_history(worker_id, timestamp);

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id TEXT NOT NULL,
                session_id TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                best_difficulty REAL DEFAULT 0,
                FOREIGN KEY (worker_id) REFERENCES workers(internal_id)
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_worker
                ON sessions(worker_id);

            CREATE TABLE IF NOT EXISTS hall_of_fame (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id TEXT NOT NULL,
                difficulty REAL NOT NULL,
                achieved_at TEXT NOT NULL,
                session_id TEXT,
                FOREIGN KEY (worker_id) REFERENCES workers(internal_id)
            );

            CREATE TABLE IF NOT EXISTS pool_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_data TEXT NOT NULL,
                detected_at TEXT NOT NULL
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bot State
# ---------------------------------------------------------------------------

def get_state(key: str, default: str | None = None) -> str | None:
    """Get a value from bot_state."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_state(key: str, value: str) -> None:
    """Set a value in bot_state."""
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

def get_worker(internal_id: str) -> dict | None:
    """Get a worker by internal ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM workers WHERE internal_id = ?", (internal_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_workers() -> list[dict]:
    """Get all registered workers."""
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT * FROM workers").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_worker(
    internal_id: str,
    api_name: str,
    session_id: str | None = None,
    hashrate: float = 0,
    start_time: str | None = None,
    best_diff: float = 0,
    last_seen: str | None = None,
) -> None:
    """Insert or update a worker record."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        existing = conn.execute(
            "SELECT internal_id FROM workers WHERE internal_id = ?",
            (internal_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE workers SET
                    last_session_id = ?,
                    last_hashrate = ?,
                    last_start_time = ?,
                    last_best_diff = ?,
                    last_seen = ?
                WHERE internal_id = ?""",
                (session_id, hashrate, start_time, best_diff, last_seen, internal_id),
            )
        else:
            conn.execute(
                """INSERT INTO workers
                    (internal_id, api_name, first_seen, last_session_id,
                     last_hashrate, last_start_time, last_best_diff, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (internal_id, api_name, now, session_id, hashrate,
                 start_time, best_diff, last_seen),
            )
        conn.commit()
    finally:
        conn.close()


def resolve_worker_id(
    api_name: str,
    session_id: str,
    hashrate: float,
    all_api_workers: list[dict],
    claimed_ids: set[str] | None = None,
) -> str:
    """
    Map an API worker to an internal ID.

    For unique API names (only one worker with that name in the current API
    response), the internal_id equals the api_name.

    For duplicate API names (multiple workers with the same name, e.g. all
    named "worker"), the bot assigns incremental IDs: worker_1, worker_2, etc.
    Re-identification is attempted by matching session_id first, then by
    similar hashrate (±50%).

    ``claimed_ids`` tracks IDs already assigned in the current batch to
    prevent two API workers from resolving to the same internal ID.
    """
    if claimed_ids is None:
        claimed_ids = set()

    # Count how many workers in the current API response share this api_name.
    # Sanitise raw names the same way identify_workers() does so that
    # None / non-string values map to the same api_name ("Unknown").
    same_name_count = sum(
        1 for w in all_api_workers
        if (w.get("name") if isinstance(w.get("name"), str) else "Unknown") == api_name
    )

    # If this api_name is unique in the current batch, use it directly
    if same_name_count <= 1:
        return api_name

    # Duplicate name scenario: try to match to an existing known worker
    conn = _get_connection()
    try:
        known = conn.execute(
            "SELECT * FROM workers WHERE api_name = ? ORDER BY internal_id",
            (api_name,),
        ).fetchall()

        # Try match by session_id (skip already-claimed IDs)
        for row in known:
            if row["last_session_id"] == session_id and row["internal_id"] not in claimed_ids:
                return row["internal_id"]

        # Try match by similar hashrate (±50%), skip already-claimed IDs
        if hashrate > 0:
            for row in known:
                if row["internal_id"] in claimed_ids:
                    continue
                saved_hr = row["last_hashrate"] or 0
                if saved_hr > 0:
                    ratio = hashrate / saved_hr
                    if 0.5 <= ratio <= 1.5:
                        return row["internal_id"]

        # No match found: assign new incremental ID (skip claimed ones)
        max_suffix = 0
        for row in known:
            iid = row["internal_id"]
            if "_" in iid:
                try:
                    suffix = int(iid.rsplit("_", 1)[1])
                    max_suffix = max(max_suffix, suffix)
                except ValueError:
                    pass
        # Also check claimed_ids for the highest suffix
        for cid in claimed_ids:
            if cid.startswith(f"{api_name}_"):
                try:
                    suffix = int(cid.rsplit("_", 1)[1])
                    max_suffix = max(max_suffix, suffix)
                except ValueError:
                    pass
        new_id = f"{api_name}_{max_suffix + 1}"
        return new_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Hashrate History
# ---------------------------------------------------------------------------

def add_hashrate_sample(worker_id: str, hashrate: float) -> None:
    """Record a hashrate sample."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO hashrate_history (worker_id, hashrate, timestamp) VALUES (?, ?, ?)",
            (worker_id, hashrate, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_avg_hashrate(worker_id: str, hours: int = 24) -> float | None:
    """Calculate average hashrate over the last N hours. Returns None if no data."""
    conn = _get_connection()
    try:
        row = conn.execute(
            """SELECT AVG(hashrate) as avg_hr, COUNT(*) as cnt
            FROM hashrate_history
            WHERE worker_id = ?
              AND timestamp >= datetime('now', ? || ' hours')""",
            (worker_id, f"-{hours}"),
        ).fetchone()
        if row and row["cnt"] > 0:
            return row["avg_hr"]
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def get_current_session(worker_id: str) -> dict | None:
    """Get the current (open) session for a worker."""
    conn = _get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM sessions
            WHERE worker_id = ? AND end_time IS NULL
            ORDER BY id DESC LIMIT 1""",
            (worker_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def close_session(worker_id: str, best_difficulty: float = 0) -> dict | None:
    """
    Close the current open session for a worker.
    Returns the closed session data or None if no open session.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        current = conn.execute(
            """SELECT * FROM sessions
            WHERE worker_id = ? AND end_time IS NULL
            ORDER BY id DESC LIMIT 1""",
            (worker_id,),
        ).fetchone()

        if current:
            conn.execute(
                """UPDATE sessions SET end_time = ?, best_difficulty = ?
                WHERE id = ?""",
                (now, best_difficulty, current["id"]),
            )
            conn.commit()
            return dict(current)
        return None
    finally:
        conn.close()


def open_session(
    worker_id: str, session_id: str, start_time: str
) -> None:
    """Open a new session for a worker."""
    conn = _get_connection()
    try:
        conn.execute(
            """INSERT INTO sessions (worker_id, session_id, start_time)
            VALUES (?, ?, ?)""",
            (worker_id, session_id, start_time),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_time_best(worker_id: str) -> float:
    """Get the best difficulty ever achieved by a worker across all sessions."""
    conn = _get_connection()
    try:
        # Check closed sessions
        row = conn.execute(
            "SELECT MAX(best_difficulty) as best FROM sessions WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        session_best = row["best"] if row and row["best"] else 0

        # Also check current worker record (current session best)
        worker = conn.execute(
            "SELECT last_best_diff FROM workers WHERE internal_id = ?",
            (worker_id,),
        ).fetchone()
        current_best = worker["last_best_diff"] if worker and worker["last_best_diff"] else 0

        # Also check hall of fame
        hof_row = conn.execute(
            "SELECT MAX(difficulty) as best FROM hall_of_fame WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        hof_best = hof_row["best"] if hof_row and hof_row["best"] else 0

        return max(session_best, current_best, hof_best)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Hall of Fame
# ---------------------------------------------------------------------------

def update_hall_of_fame(
    worker_id: str, difficulty: float, session_id: str | None = None
) -> bool:
    """
    Try to add an entry to the Hall of Fame (top 10).
    Returns True if the entry was added.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        # Check if this exact difficulty is already recorded for this worker
        existing = conn.execute(
            """SELECT id FROM hall_of_fame
            WHERE worker_id = ? AND difficulty = ?""",
            (worker_id, difficulty),
        ).fetchone()
        if existing:
            return False

        entries = conn.execute(
            "SELECT * FROM hall_of_fame ORDER BY difficulty DESC"
        ).fetchall()

        if len(entries) < 10:
            conn.execute(
                """INSERT INTO hall_of_fame
                    (worker_id, difficulty, achieved_at, session_id)
                VALUES (?, ?, ?, ?)""",
                (worker_id, difficulty, now, session_id),
            )
            conn.commit()
            return True

        # Check if this beats the lowest entry
        lowest = entries[-1]
        if difficulty > lowest["difficulty"]:
            conn.execute("DELETE FROM hall_of_fame WHERE id = ?", (lowest["id"],))
            conn.execute(
                """INSERT INTO hall_of_fame
                    (worker_id, difficulty, achieved_at, session_id)
                VALUES (?, ?, ?, ?)""",
                (worker_id, difficulty, now, session_id),
            )
            conn.commit()
            return True

        return False
    finally:
        conn.close()


def get_hall_of_fame(limit: int = 10) -> list[dict]:
    """Get the Hall of Fame entries sorted by difficulty descending."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM hall_of_fame ORDER BY difficulty DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pool Blocks
# ---------------------------------------------------------------------------

def get_known_pool_block_heights() -> set[int]:
    """Get all known pool block heights."""
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT block_data FROM pool_blocks").fetchall()
        heights = set()
        for r in rows:
            try:
                data = json.loads(r["block_data"])
                if isinstance(data, dict) and "height" in data:
                    heights.add(data["height"])
            except (json.JSONDecodeError, TypeError):
                pass
        return heights
    finally:
        conn.close()


def save_pool_block(block_data: dict) -> None:
    """Save a newly found pool block."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO pool_blocks (block_data, detected_at) VALUES (?, ?)",
            (json.dumps(block_data), now),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

def purge_old_data(days: int) -> int:
    """Delete hashrate history older than N days. Returns rows deleted."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM hashrate_history WHERE timestamp < datetime('now', ? || ' days')",
            (f"-{days}",),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
