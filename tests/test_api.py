import pytest
import httpx
from api_server import app

@pytest.mark.asyncio
async def test_health_check():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["port"] == 3456
        assert "config" in data

@pytest.mark.asyncio
async def test_read_config():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "input_mode" in data
        assert "model_analyzer" in data

@pytest.mark.asyncio
async def test_pipeline_status():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/pipeline/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "logs" in data

@pytest.mark.asyncio
async def test_list_datasets():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/datasets")
        assert response.status_code == 200
        data = response.json()
        assert "datasets" in data
        assert isinstance(data["datasets"], list)

@pytest.mark.asyncio
async def test_sqlite_tables():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/db/sqlite/tables")
        assert response.status_code == 200
        data = response.json()
        assert "tables" in data

@pytest.mark.asyncio
async def test_qdrant_info():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/db/qdrant/info")
        assert response.status_code == 200
        data = response.json()
        assert "collection" in data
