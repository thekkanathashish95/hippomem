"""Scoped bearer tokens, CORS, bind guard, and IDOR query requirements."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from hippomem.cli import main
from hippomem.server import app as app_module
from hippomem.server.auth import AuthContext


@pytest.fixture
def token_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path}/auth.db")
    monkeypatch.setenv("VECTOR_DIR", str(tmp_path / "vectors"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("HIPPOMEM_API_TOKEN", "admin-secret")
    monkeypatch.setenv("HIPPOMEM_TOKENS", "app:scoped-secret:ns=acme")
    app_module.memory = None
    app_module.llm_client = None
    with TestClient(app_module.app) as c:
        yield c


def test_health_is_public_when_tokens_configured(token_client):
    r = token_client.get("/health")
    assert r.status_code == 200


def test_decode_without_token_is_401(token_client):
    r = token_client.post("/decode", json={"user_id": "acme:u1", "message": "hi"})
    assert r.status_code == 401


def test_scoped_token_cannot_cross_namespace(token_client):
    r = token_client.post(
        "/decode",
        json={"user_id": "other", "message": "hi"},
        headers={"Authorization": "Bearer scoped-secret"},
    )
    assert r.status_code == 403


def test_scoped_token_can_target_own_prefix(token_client):
    r = token_client.post(
        "/decode",
        json={"user_id": "acme:u1", "message": "hi"},
        headers={"Authorization": "Bearer scoped-secret"},
    )
    assert r.status_code == 503  # memory not initialized; auth passed


def test_scoped_token_cannot_patch_config(token_client):
    r = token_client.patch(
        "/config",
        json={"system_prompt": "nope"},
        headers={"Authorization": "Bearer scoped-secret"},
    )
    assert r.status_code == 403


def test_admin_token_can_read_config(token_client):
    r = token_client.get("/config", headers={"Authorization": "Bearer admin-secret"})
    assert r.status_code == 200


def test_delete_requires_admin_and_confirm(token_client):
    r = token_client.delete(
        "/users/acme:u1",
        headers={"Authorization": "Bearer scoped-secret"},
    )
    assert r.status_code == 403
    r = token_client.delete(
        "/users/acme:u1",
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert r.status_code == 400
    r = token_client.delete(
        "/users/acme:u1?confirm=true",
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert r.status_code == 503  # no memory service


def test_trace_detail_requires_user_id(token_client):
    r = token_client.get(
        "/traces/abc",
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert r.status_code == 422


def test_turn_status_requires_user_id(token_client):
    r = token_client.get(
        "/turn-status/turn-1",
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert r.status_code == 422


def test_trace_detail_filters_by_user(token_client):
    mock_svc = MagicMock()
    mock_svc.get_interaction_detail.return_value = None
    app_module.memory = mock_svc
    try:
        r = token_client.get(
            "/traces/abc",
            params={"user_id": "acme:u1"},
            headers={"Authorization": "Bearer scoped-secret"},
        )
        assert r.status_code == 404
        mock_svc.get_interaction_detail.assert_called_once_with("abc", user_id="acme:u1")
    finally:
        app_module.memory = None


def test_cors_allows_localhost_not_arbitrary_origin(token_client):
    r = token_client.options(
        "/decode",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"

    r = token_client.options(
        "/decode",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_allows_user_prefix_rules():
    ctx = AuthContext(name="app", namespace="acme", is_admin=False)
    assert ctx.allows_user("acme")
    assert ctx.allows_user("acme:u1")
    assert not ctx.allows_user("acme-other")
    assert not ctx.allows_user("other")


def test_cli_refuses_wildcard_bind_without_token(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["hippomem", "serve", "--host", "0.0.0.0", "--port", "18719"],
    )
    monkeypatch.delenv("HIPPOMEM_API_TOKEN", raising=False)
    monkeypatch.delenv("HIPPOMEM_TOKENS", raising=False)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
