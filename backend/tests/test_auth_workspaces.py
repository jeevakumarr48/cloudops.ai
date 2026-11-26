"""Authentication, roles and workspace isolation (in-memory SQLite)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from core import database
from core.models import AuditEvent, User, UserSession
from core.security import SESSION_COOKIE

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def http_cookies(monkeypatch):
    # TestClient talks plain HTTP; Secure cookies would not be sent back.
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")


def new_client():
    return TestClient(main.app)


def register(client, email, password=PASSWORD, **extra):
    return client.post("/api/auth/register", json={"email": email, "password": password, **extra})


def db():
    return database.session_factory()()


def personal_workspace(client):
    return client.get("/api/auth/me").json()["workspaces"][0]["workspace_id"]


# --- registration and passwords ---------------------------------------------


def test_register_creates_user_session_and_admin_workspace():
    client = new_client()
    response = register(client, "Alice@Example.com", display_name="Alice")
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["workspaces"][0]["role"] == "admin"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/auth/me").status_code == 200


def test_password_is_hashed_with_argon2id_and_token_is_not_stored():
    client = new_client()
    register(client, "a@example.com")
    session = db()
    user = session.scalar(select(User))
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    token = client.cookies.get(SESSION_COOKIE)
    stored = session.scalar(select(UserSession)).token_hash
    assert token and stored != token and len(stored) == 64


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com", "password": "x" * 129},
        {"email": "a@example.com", "password": PASSWORD, "role": "admin"},
    ],
)
def test_register_validation(payload):
    assert new_client().post("/api/auth/register", json=payload).status_code == 422


def test_duplicate_email_is_rejected():
    register(new_client(), "a@example.com")
    assert register(new_client(), "A@example.com").status_code == 409


def test_registration_can_be_closed(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_REGISTRATION_OPEN", "false")
    assert register(new_client(), "a@example.com").status_code == 403


def test_state_changing_routes_require_json():
    response = new_client().post(
        "/api/auth/register",
        content="email=a@example.com&password=xxxxxxxxxxxxxxxx",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415


# --- login, logout, sessions -------------------------------------------------


def test_login_and_logout_revokes_session():
    register(new_client(), "a@example.com")
    client = new_client()
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 200
    token = client.cookies.get(SESSION_COOKIE)
    assert client.post("/api/auth/logout", json={}).status_code == 204
    # The old token no longer works even if replayed.
    replay = new_client()
    replay.cookies.set(SESSION_COOKIE, token)
    assert replay.get("/api/auth/me").status_code == 401


def test_wrong_password_and_unknown_email_look_the_same():
    register(new_client(), "a@example.com")
    wrong = new_client().post("/api/auth/login", json={"email": "a@example.com", "password": "wrong password!"})
    unknown = new_client().post("/api/auth/login", json={"email": "b@example.com", "password": "wrong password!"})
    assert wrong.status_code == unknown.status_code == 401
    strip = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
    assert strip(wrong) == strip(unknown)


def test_login_is_rate_limited_per_email():
    register(new_client(), "a@example.com")
    client = new_client()
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong password!"})
    # Even the right password is refused while the account is throttled.
    blocked = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert blocked.status_code == 429


def test_registration_is_rate_limited_per_ip():
    client = new_client()
    codes = [register(client, "u%d@example.com" % i).status_code for i in range(6)]
    assert codes[:5] == [201] * 5 and codes[5] == 429


def test_anonymous_and_forged_sessions_are_rejected():
    client = new_client()
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, "forged-token")
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/workspaces").status_code == 401


def test_audit_never_contains_password():
    client = new_client()
    register(client, "a@example.com")
    client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong password!"})
    events = db().scalars(select(AuditEvent)).all()
    assert {e.action for e in events} >= {"user.register", "user.login_failed"}
    for event in events:
        assert PASSWORD not in (event.detail or "") and "wrong password" not in (event.detail or "")


# --- workspaces, roles and isolation ----------------------------------------


def test_workspace_isolation_between_users():
    alice, bob = new_client(), new_client()
    register(alice, "alice@example.com")
    register(bob, "bob@example.com")
    alice_ws = personal_workspace(alice)
    bob_ws = personal_workspace(bob)

    assert [w["id"] for w in alice.get("/api/workspaces").json()] == [alice_ws]
    for path in ("/api/workspaces/%s", "/api/workspaces/%s/audit"):
        # Non-members get 404 (not 403) so ids cannot be probed.
        assert alice.get(path % bob_ws).status_code == 404
        assert bob.get(path % alice_ws).status_code == 404
    response = alice.post("/api/workspaces/%s/members" % bob_ws, json={"email": "alice@example.com", "role": "admin"})
    assert response.status_code == 404


def test_admin_adds_viewer_who_cannot_administer():
    alice, bob = new_client(), new_client()
    register(alice, "alice@example.com")
    register(bob, "bob@example.com")
    ws = personal_workspace(alice)

    added = alice.post("/api/workspaces/%s/members" % ws, json={"email": "bob@example.com"})
    assert added.status_code == 201
    assert {m["email"]: m["role"] for m in added.json()["members"]} == {
        "alice@example.com": "admin", "bob@example.com": "viewer",
    }
    assert bob.get("/api/workspaces/%s" % ws).json()["role"] == "viewer"
    assert bob.get("/api/workspaces/%s/audit" % ws).status_code == 403
    assert bob.post("/api/workspaces/%s/members" % ws, json={"email": "bob@example.com", "role": "admin"}).status_code == 403


def test_last_admin_cannot_be_demoted():
    alice = new_client()
    register(alice, "alice@example.com")
    ws = personal_workspace(alice)
    response = alice.post("/api/workspaces/%s/members" % ws, json={"email": "alice@example.com", "role": "viewer"})
    assert response.status_code == 409


def test_adding_unknown_user_is_404():
    alice = new_client()
    register(alice, "alice@example.com")
    ws = personal_workspace(alice)
    assert alice.post("/api/workspaces/%s/members" % ws, json={"email": "nobody@example.com"}).status_code == 404


def test_create_workspace_and_audit_trail():
    alice = new_client()
    register(alice, "alice@example.com")
    created = alice.post("/api/workspaces", json={"name": "Team"})
    assert created.status_code == 201
    ws = created.json()["id"]
    assert len(alice.get("/api/workspaces").json()) == 2
    actions = [e["action"] for e in alice.get("/api/workspaces/%s/audit" % ws).json()]
    assert actions == ["workspace.create"]


def test_legacy_endpoints_stay_anonymous(monkeypatch):
    monkeypatch.setattr(main, "discover_ec2_instances", lambda region=None: [])
    client = new_client()
    assert client.get("/health").status_code == 200
    assert client.get("/api/resources/ec2").json() == {"total_instances": 0, "instances": []}


def test_no_database_on_serverless_gives_clean_503(monkeypatch):
    database.reset()
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = new_client()
    response = register(client, "a@example.com")
    assert response.status_code == 503
    assert "not available" in response.json()["detail"]
    assert client.get("/health").status_code == 200
