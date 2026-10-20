"""Isolated Phase C candidate: retry only transient SQLite WAL promotion locks."""
import sqlite3

import pytest

import chatgpt_web2api.orchestrator.store as module


class ConnectionProbe:
    def __init__(self, failures, mode="wal"):
        self.failures = list(failures)
        self.mode = mode
        self.calls = 0

    def execute(self, sql):
        assert sql == "PRAGMA journal_mode=WAL"
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self

    def fetchone(self):
        return (self.mode,)


def error(code):
    result = sqlite3.OperationalError("synthetic SQLite error")
    result.sqlite_errorcode = code
    return result


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
                                 sqlite3.SQLITE_BUSY | (2 << 8)])
def test_wal_promotion_retries_transient_locks_only(code, monkeypatch):
    connection = ConnectionProbe([error(code), error(code)])
    sleeps = []
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    module._enable_wal(connection)
    assert connection.calls == 3
    assert sleeps == [0.01, 0.01]


def test_wal_retry_deadline_is_bounded(monkeypatch):
    failure = error(sqlite3.SQLITE_BUSY)
    connection = ConnectionProbe([failure])
    ticks = iter([0, 11])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    with pytest.raises(sqlite3.OperationalError) as raised:
        module._enable_wal(connection)
    assert raised.value is failure
    assert connection.calls == 1


@pytest.mark.parametrize("code", [sqlite3.SQLITE_NOTADB, None])
def test_nonlock_database_error_never_retried(code):
    failure = error(code)
    connection = ConnectionProbe([failure])
    with pytest.raises(sqlite3.OperationalError) as raised:
        module._enable_wal(connection)
    assert raised.value is failure
    assert connection.calls == 1


def test_refused_wal_mode_is_not_reported_as_success():
    with pytest.raises(ValueError, match="WAL"):
        module._enable_wal(ConnectionProbe([], mode="delete"))
