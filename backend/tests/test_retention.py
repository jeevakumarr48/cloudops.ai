"""Daily retention job and the registered-account cap."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

import main
from core import config, database
from core.models import AuditEvent, Snapshot, UsageCounter, User, UserSession, utcnow
from services import retention

PASSWORD = "correct horse battery"


def db():
    return database.session_factory()()


def add_user(session, email="old@example.com"):
    user = User(email=email, password_hash="x")
    session.add(user)
    session.flush()
    return user


def test_prune_removes_only_rows_past_retention():
    session = db()
    now = utcnow()
    user = add_user(session)
    session.add_all([
        # removed: expired 8 days ago, revoked 10 days ago
        UserSession(user_id=user.id, token_hash="a" * 64, expires_at=now - timedelta(days=8)),
        UserSession(user_id=user.id, token_hash="b" * 64, expires_at=now + timedelta(days=5),
                    revoked_at=now - timedelta(days=10)),
        # kept: live, and just expired (inside the grace period)
        UserSession(user_id=user.id, token_hash="c" * 64, expires_at=now + timedelta(days=5)),
        UserSession(user_id=user.id, token_hash="d" * 64, expires_at=now - timedelta(days=1)),
        UsageCounter(key="old", window_start=now - timedelta(days=41), count=1),
        UsageCounter(key="recent", window_start=now - timedelta(days=30), count=1),
        Snapshot(kind="cost", params_key="p", as_of="2026-01-01", payload={},
                 fetched_at=now - timedelta(days=41)),
        Snapshot(kind="cost", params_key="p", as_of="2026-01-02", payload={},
                 fetched_at=now - timedelta(days=2)),
        AuditEvent(action="old", created_at=now - timedelta(days=181)),
        AuditEvent(action="recent", created_at=now - timedelta(days=10)),
    ])
    session.commit()

    removed = retention.prune(session, now=now)

    assert removed == {"user_sessions": 2, "usage_counters": 1, "snapshots": 1, "audit_events": 1}
    assert sorted(s.token_hash[0] for s in session.scalars(select(UserSession))) == ["c", "d"]
    assert [c.key for c in session.scalars(select(UsageCounter))] == ["recent"]
    assert [s.as_of for s in session.scalars(select(Snapshot))] == ["2026-01-02"]
    assert [a.action for a in session.scalars(select(AuditEvent))] == ["recent"]


def test_maybe_prune_runs_once_a_day():
    session = db()
    assert retention.maybe_prune(session) is not None
    assert retention.maybe_prune(session) is None


def test_maybe_prune_never_fails_the_caller(monkeypatch):
    def boom(session, now=None):
        raise OperationalError("DELETE", {}, Exception("database is locked"))

    monkeypatch.setattr(retention, "prune", boom)
    assert retention.maybe_prune(db()) is None


def test_login_runs_retention(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    calls = []
    monkeypatch.setattr(retention, "maybe_prune", lambda session: calls.append(session))
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD})
    response = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert response.status_code == 200
    assert len(calls) == 1


def test_account_cap_blocks_new_users_but_not_operators(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "owner@example.com")
    session = db()
    existing = session.scalar(select(func.count()).select_from(User)) or 0
    monkeypatch.setenv("CLOUDOPS_MAX_USERS", str(existing + 1))

    first = TestClient(main.app).post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD})
    assert first.status_code == 201
    second = TestClient(main.app).post("/api/auth/register", json={"email": "b@example.com", "password": PASSWORD})
    assert second.status_code == 403
    assert "account limit" in second.json()["detail"]
    owner = TestClient(main.app).post("/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD})
    assert owner.status_code == 201


def test_max_users_parsing(monkeypatch):
    monkeypatch.delenv("CLOUDOPS_MAX_USERS", raising=False)
    assert config.max_users() == 100
    monkeypatch.setenv("CLOUDOPS_MAX_USERS", "nope")
    assert config.max_users() == 100
    monkeypatch.setenv("CLOUDOPS_MAX_USERS", "0")
    assert config.max_users() == 1
    monkeypatch.setenv("CLOUDOPS_MAX_USERS", "250")
    assert config.max_users() == 250
