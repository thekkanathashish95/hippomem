"""HTTP contract tests for the daemon (TestClient + HippoMemClient)."""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from hippomem.client import HippoMemClient
from hippomem.decoder.schemas import DecodeResult
from hippomem.server import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path}/http.db")
    monkeypatch.setenv("VECTOR_DIR", str(tmp_path / "vectors"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("HIPPOMEM_API_TOKEN", raising=False)
    monkeypatch.delenv("HIPPOMEM_TOKENS", raising=False)
    app_module.memory = None
    app_module.llm_client = None
    with TestClient(app_module.app) as c:
        yield c


def test_health_ok_when_setup_required(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "setup_required" in body


def test_config_get_masks_or_omits_live_key(client):
    r = client.get("/config")
    assert r.status_code == 200
    key = r.json().get("llm_api_key", "")
    assert key in ("", "sk-****")


def test_decode_without_memory_is_503(client):
    r = client.post("/decode", json={"user_id": "u1", "message": "hello"})
    assert r.status_code == 503


def test_encode_without_memory_is_503(client):
    r = client.post(
        "/encode",
        json={
            "user_id": "u1",
            "user_message": "hi",
            "assistant_response": "hello",
        },
    )
    assert r.status_code == 503


def test_consolidate_without_memory_is_503(client):
    r = client.post("/consolidate", json={"user_id": "u1"})
    assert r.status_code == 503


def test_decode_encode_with_mocked_service(client):
    decode_result = DecodeResult(
        context="## Memory Context\n\nprior work",
        used_engram_ids=["e1"],
        used_entity_ids=[],
        reasoning="test",
        synthesized_context="prior work",
        turn_id="turn-1",
    )
    mock_svc = MagicMock()
    mock_svc.decode = AsyncMock(return_value=decode_result)
    mock_svc.encode = AsyncMock(return_value="turn-1")
    app_module.memory = mock_svc
    try:
        r = client.post("/decode", json={"user_id": "u1", "message": "what was I doing?"})
        assert r.status_code == 200
        assert r.json()["turn_id"] == "turn-1"
        r2 = client.post(
            "/encode",
            json={
                "user_id": "u1",
                "user_message": "what was I doing?",
                "assistant_response": "you were testing",
                "decode_result": r.json(),
            },
        )
        assert r2.status_code == 200
        assert r2.json()["turn_id"] == "turn-1"
    finally:
        app_module.memory = None


@pytest.mark.asyncio
async def test_hippomem_client_maps_decode_and_encode():
    seen: dict[str, str | None] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        if request.url.path == "/decode":
            return httpx.Response(
                200,
                json={
                    "context": "## Memory Context\n\nprior work",
                    "used_engram_ids": ["e1"],
                    "used_entity_ids": [],
                    "reasoning": "test",
                    "synthesized_context": "prior work",
                    "turn_id": "turn-1",
                },
            )
        if request.url.path == "/encode":
            return httpx.Response(200, json={"status": "ok", "turn_id": "turn-1"})
        if request.url.path == "/users/u1/export":
            return httpx.Response(200, json={"schema_version": 1, "user_id": "u1", "engrams": []})
        if request.url.path == "/users/u1":
            return httpx.Response(200, json={"engrams": 0, "faiss_index": 0})
        return httpx.Response(404)

    mem = HippoMemClient("http://test", token="test-token")
    await mem.aclose()
    mem._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
        headers={"Authorization": "Bearer test-token"},
    )
    try:
        got = await mem.decode("u1", "what was I doing?")
        assert got.turn_id == "turn-1"
        encoded = await mem.encode("u1", "q", "a", decode_result=got)
        assert encoded.turn_id == "turn-1"
        exported = await mem.export_user("u1")
        assert exported["schema_version"] == 1
        deleted = await mem.delete_user("u1", confirm=True)
        assert "engrams" in deleted
        assert seen["auth"] == "Bearer test-token"
    finally:
        await mem.aclose()
