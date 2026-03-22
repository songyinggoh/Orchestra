"""Shared test fixtures for Orchestra test suite."""

import pytest


@pytest.fixture(autouse=True)
def isolate_orchestra_db(tmp_path, monkeypatch):
    """Route every test's SQLite store to a per-test temp directory.

    Prevents 'database is locked' errors when tests run in parallel or
    when a previous test left an uncommitted WAL transaction.
    """
    db_path = str(tmp_path / "test_runs.db")
    monkeypatch.setenv("ORCHESTRA_DB_PATH", db_path)
