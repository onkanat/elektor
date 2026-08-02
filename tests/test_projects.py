import pytest
import httpx
import uuid
from api_server import app

@pytest.mark.asyncio
async def test_list_projects():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert "active_project_id" in data
        assert "projects" in data
        assert isinstance(data["projects"], list)

@pytest.mark.asyncio
async def test_create_and_select_project():
    pid = f"test_proj_{uuid.uuid4().hex[:6]}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        # Create new project
        create_resp = await ac.post("/api/projects/create", json={
            "project_id": pid,
            "project_name": "Pytest Dynamic Test Project",
            "input_mode": "book",
            "input_path": "/path/to/pytest.pdf",
            "llm_persona": "Embedded Software Engineer",
            "llm_subject": "RP2040 Hardware"
        })
        assert create_resp.status_code == 200
        cdata = create_resp.json()
        assert cdata["status"] == "created"
        assert cdata["project_id"] == pid

        # Select project
        select_resp = await ac.post("/api/projects/select", json={"project_id": pid})
        assert select_resp.status_code == 200
        sdata = select_resp.json()
        assert sdata["active_project_id"] == pid

        # Verify projects list remembers last accessed
        list_resp = await ac.get("/api/projects")
        assert list_resp.status_code == 200
        ldata = list_resp.json()
        assert ldata["active_project_id"] == pid

@pytest.mark.asyncio
async def test_reset_safety_guard():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        # Attempt reset without confirm_reset should fail with HTTP 400
        fail_resp = await ac.post("/api/pipeline/run", json={
            "command": "pipeline",
            "limit": "5",
            "reset": True,
            "confirm_reset": False
        })
        assert fail_resp.status_code == 400
        assert "GÜVENLİK UYARISI" in fail_resp.json()["detail"]
