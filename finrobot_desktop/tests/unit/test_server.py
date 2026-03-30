import pytest
from httpx import ASGITransport, AsyncClient

from finagent.server import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_health_returns_ready_status(self, client):
        data = response = await client.get("/health")
        data = response.json()
        assert data["status"] == "ready"
        assert data["phase"] == "P0"


class TestChatEndpoint:
    async def test_chat_endpoint_exists_and_accepts_post(self, client):
        # Just verify the endpoint exists — a well-formed empty body returns
        # a non-404 response (may be 400/422 without proper Vercel AI payload,
        # but NOT 404 or 405)
        response = await client.post("/chat", json={})
        assert response.status_code != 404
        assert response.status_code != 405
