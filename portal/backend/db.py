"""
Database module for Pulse.

Manages the SQLite database used to track monitored services,
deployed services, and deployment history.

Three tables:
  - monitored_services: external URLs Pulse pings (Google, GitHub, etc.)
  - deployed_services: services Pulse has deployed to Kubernetes
  - deployments: append-only history of every deploy and rollback

Soft deletes are used for service tables. Deployments are never deleted.

The schema is initialized lazily on the first connection — no startup
hook required, works regardless of how the app is launched.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitored_services (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at  TIMESTAMP DEFAULT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_monitored_services_name_active
    ON monitored_services(name) WHERE deleted_at IS NULL;


CREATE TABLE IF NOT EXISTS deployed_services (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    environment  TEXT NOT NULL,
    image        TEXT NOT NULL,
    port         INTEGER NOT NULL,
    replicas     INTEGER NOT NULL DEFAULT 1,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at   TIMESTAMP DEFAULT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_deployed_services_name_env_active
    ON deployed_services(name, environment) WHERE deleted_at IS NULL;


CREATE TABLE IF NOT EXISTS deployments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id      INTEGER NOT NULL,
    image_tag       TEXT NOT NULL,
    environment     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    github_run_id   TEXT,
    deployed_by     TEXT DEFAULT 'system',
    deployed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (service_id) REFERENCES deployed_services(id) ON DELETE CASCADE
);
"""


def _get_db_path() -> str:
    """Read the DB path from env on every call so tests can override it."""
    return os.environ.get("PULSE_DB_PATH", "/data/pulse.db")


# Module-level flag tracking whether the current DB file has been initialized.
# Cleared on reload (so tests using importlib.reload get a fresh state).
_initialized_for_path: Optional[str] = None


def _ensure_initialized():
    """
    Lazily initialize the schema on the first connection per DB path.

    Tracks the initialized path so that if PULSE_DB_PATH changes (e.g. between
    test runs), the new path gets initialized too.
    """
    global _initialized_for_path
    current_path = _get_db_path()

    if _initialized_for_path == current_path:
        return

    # Make sure the directory for the DB file exists
    db_dir = os.path.dirname(current_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Open a raw connection (not via get_connection, to avoid recursion)
    conn = sqlite3.connect(current_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

    _initialized_for_path = current_path


@contextmanager
def get_connection():
    """
    Context manager for SQLite connections.

    Lazily initializes the schema on first use. Ensures the connection is
    properly closed on exit, and rolls back on any exception.

    Usage:
        with get_connection() as conn:
            cursor = conn.execute("SELECT * FROM monitored_services")
            rows = cursor.fetchall()
    """
    _ensure_initialized()

    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """
    Explicit schema initialization.

    Most code doesn't need to call this — get_connection() initializes lazily.
    Provided for tests and for explicit-startup use cases.
    """
    _ensure_initialized()


# --- monitored_services helpers ---

def list_monitored_services() -> list[dict]:
    """Return all non-deleted monitored services."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, url, created_at FROM monitored_services "
            "WHERE deleted_at IS NULL ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]


def add_monitored_service(name: str, url: str) -> int:
    """Insert a new monitored service. Returns the new row's id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO monitored_services (name, url) VALUES (?, ?)",
            (name, url),
        )
        return cursor.lastrowid


def soft_delete_monitored_service(service_id: int) -> bool:
    """Soft-delete a monitored service. Returns True if a row was affected."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE monitored_services SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND deleted_at IS NULL",
            (service_id,),
        )
        return cursor.rowcount > 0


def restore_monitored_service(service_id: int) -> bool:
    """Restore a soft-deleted monitored service. Returns True if a row was affected."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE monitored_services SET deleted_at = NULL "
            "WHERE id = ? AND deleted_at IS NOT NULL",
            (service_id,),
        )
        return cursor.rowcount > 0


# --- deployed_services helpers (skeleton; populated in Phase 3) ---

def list_deployed_services(environment: Optional[str] = None) -> list[dict]:
    """Return non-deleted deployed services, optionally filtered by environment."""
    with get_connection() as conn:
        if environment:
            rows = conn.execute(
                "SELECT * FROM deployed_services "
                "WHERE deleted_at IS NULL AND environment = ? "
                "ORDER BY created_at",
                (environment,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM deployed_services "
                "WHERE deleted_at IS NULL ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]


# --- deployments helpers (skeleton; populated in Phase 3) ---

def list_deployments_for_service(service_id: int, limit: int = 10) -> list[dict]:
    """Return recent deployment history for a service, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM deployments WHERE service_id = ? "
            "ORDER BY deployed_at DESC LIMIT ?",
            (service_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

def add_deployment(
    service_id: int,
    image_tag: str,
    environment: str,
    status: str = "pending",
    github_run_id: str = None,
) -> int:
    """Record a new deployment attempt. Returns the row id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO deployments (service_id, image_tag, environment, status, github_run_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (service_id, image_tag, environment, status, github_run_id),
        )
        return cursor.lastrowid


def update_deployment_status(deployment_id: int, status: str) -> bool:
    """Update the status of an existing deployment."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE deployments SET status = ? WHERE id = ?",
            (status, deployment_id),
        )
        return cursor.rowcount > 0


def add_deployed_service(name: str, environment: str, image: str, port: int, replicas: int = 1) -> int:
    """Insert a new deployed service row. Returns the new row's id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO deployed_services (name, environment, image, port, replicas) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, environment, image, port, replicas),
        )
        return cursor.lastrowid


def get_deployed_service_by_name(name: str, environment: str) -> dict | None:
    """Find a deployed service by name + environment. Returns None if not found or deleted."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM deployed_services "
            "WHERE name = ? AND environment = ? AND deleted_at IS NULL",
            (name, environment),
        ).fetchone()
        return dict(row) if row else None


def soft_delete_deployed_service(service_id: int) -> bool:
    """Soft-delete a deployed service."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE deployed_services SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND deleted_at IS NULL",
            (service_id,),
        )
        return cursor.rowcount > 0