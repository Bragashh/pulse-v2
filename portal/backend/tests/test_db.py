"""
Tests for the db module.

Each test runs against an in-memory SQLite database — fast, isolated,
no cleanup needed between tests.
"""

import os
import pytest


@pytest.fixture
def db_module(tmp_path, monkeypatch):
    """
    Provides a fresh db module with an isolated database file.
    Each test gets its own temp DB file that's deleted automatically.
    """
    test_db_path = tmp_path / "test_pulse.db"
    monkeypatch.setenv("PULSE_DB_PATH", str(test_db_path))

    # Force a fresh import so DB_PATH is re-read from the env var
    import importlib
    import db
    importlib.reload(db)

    db.init_db()
    yield db


# --- Schema initialization ---

def test_init_creates_tables(db_module):
    """init_db should create all three tables."""
    with db_module.get_connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [t["name"] for t in tables]
        assert "monitored_services" in names
        assert "deployed_services" in names
        assert "deployments" in names


def test_init_is_idempotent(db_module):
    """Calling init_db twice should not raise an error."""
    db_module.init_db()
    db_module.init_db()


# --- monitored_services ---

def test_add_monitored_service_returns_id(db_module):
    """Adding a service returns its new id."""
    sid = db_module.add_monitored_service("Google", "https://www.google.com")
    assert isinstance(sid, int)
    assert sid > 0


def test_list_monitored_services_returns_added(db_module):
    """A service added via add() shows up in list()."""
    db_module.add_monitored_service("Google", "https://www.google.com")
    services = db_module.list_monitored_services()
    assert len(services) == 1
    assert services[0]["name"] == "Google"
    assert services[0]["url"] == "https://www.google.com"


def test_list_monitored_services_empty_initially(db_module):
    """Fresh DB returns empty list."""
    services = db_module.list_monitored_services()
    assert services == []


def test_list_monitored_services_returns_multiple(db_module):
    """Adding multiple services returns all of them."""
    db_module.add_monitored_service("Google", "https://www.google.com")
    db_module.add_monitored_service("GitHub", "https://github.com")
    db_module.add_monitored_service("Gitea", "https://gitea.dev.bodnarescu.ro")

    services = db_module.list_monitored_services()
    assert len(services) == 3


# --- soft delete ---

def test_soft_delete_hides_from_list(db_module):
    """Soft-deleted services should not appear in list()."""
    sid = db_module.add_monitored_service("Google", "https://www.google.com")
    deleted = db_module.soft_delete_monitored_service(sid)
    assert deleted is True

    services = db_module.list_monitored_services()
    assert services == []


def test_soft_delete_returns_false_for_nonexistent(db_module):
    """Soft-deleting a non-existent id returns False."""
    deleted = db_module.soft_delete_monitored_service(999)
    assert deleted is False


def test_soft_delete_returns_false_for_already_deleted(db_module):
    """Soft-deleting an already-deleted service returns False."""
    sid = db_module.add_monitored_service("Google", "https://www.google.com")
    db_module.soft_delete_monitored_service(sid)
    deleted_again = db_module.soft_delete_monitored_service(sid)
    assert deleted_again is False


def test_restore_brings_back_deleted(db_module):
    """Restoring a soft-deleted service makes it visible again."""
    sid = db_module.add_monitored_service("Google", "https://www.google.com")
    db_module.soft_delete_monitored_service(sid)
    restored = db_module.restore_monitored_service(sid)
    assert restored is True

    services = db_module.list_monitored_services()
    assert len(services) == 1
    assert services[0]["name"] == "Google"


# --- partial unique index ---

def test_can_add_service_after_soft_deleting_same_name(db_module):
    """Soft-deleting 'Google' should let us add a new 'Google'."""
    sid1 = db_module.add_monitored_service("Google", "https://www.google.com")
    db_module.soft_delete_monitored_service(sid1)

    # Should not raise an integrity error
    sid2 = db_module.add_monitored_service("Google", "https://www.google.com.au")
    assert sid2 != sid1

    services = db_module.list_monitored_services()
    assert len(services) == 1
    assert services[0]["url"] == "https://www.google.com.au"


def test_cannot_add_two_active_services_with_same_name(db_module):
    """Active services with duplicate names should raise an integrity error."""
    import sqlite3
    db_module.add_monitored_service("Google", "https://www.google.com")
    with pytest.raises(sqlite3.IntegrityError):
        db_module.add_monitored_service("Google", "https://www.google.com.au")