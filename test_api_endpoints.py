import uuid
import pytest
from fastapi.testclient import TestClient
import random
import string
from unittest.mock import patch
from app.agent.llm_provider import StreamChunk

from app.main import app

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def random_string():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_auth_flow(client, random_string):
    username = f"testuser_{random_string}"
    password = "password123"
    
    # Register
    res = client.post("/api/v1/auth/register", json={
        "username": username,
        "password": password
    })
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    token = data["access_token"]
    
    # Login
    res = client.post("/api/v1/auth/login", json={
        "username": username,
        "password": password
    })
    assert res.status_code == 200
    assert "access_token" in res.json()
    
    # Get Me
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["username"] == username

def test_session_and_file_flow(client, random_string):
    username = f"testuser_{random_string}"
    password = "password123"
    
    res = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Create Session
    res = client.post("/api/v1/sessions", json={"title": "Test Session"}, headers=headers)
    assert res.status_code == 201
    session_id = res.json()["id"]
    
    # 2. List Sessions
    res = client.get("/api/v1/sessions", headers=headers)
    assert res.status_code == 200
    assert any(s["id"] == session_id for s in res.json())
    
    # 3. Rename Session
    res = client.patch(f"/api/v1/sessions/{session_id}", json={"title": "Renamed Session"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["title"] == "Renamed Session"
    
    # 4. Upload File
    files = {"file": ("test.txt", b"Hello World", "text/plain")}
    data = {"description": "A test file"}
    res = client.post(f"/api/v1/sessions/{session_id}/files", files=files, data=data, headers=headers)
    assert res.status_code == 201
    file_id = res.json()["id"]
    
    # 5. List Files
    res = client.get(f"/api/v1/sessions/{session_id}/files", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) >= 1
    
    # 6. Get File info
    res = client.get(f"/api/v1/sessions/{session_id}/files/{file_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == file_id
    
    # 7. Get File download url
    res = client.get(f"/api/v1/sessions/{session_id}/files/{file_id}/download", headers=headers, follow_redirects=False)
    assert res.status_code in [200, 302, 307] # Usually redirect
    
    # 8. Delete File
    res = client.delete(f"/api/v1/sessions/{session_id}/files/{file_id}", headers=headers)
    assert res.status_code == 204
    
    # 9. Get Messages (should be empty initially)
    res = client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    
    # 10. Delete Session
    res = client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
    assert res.status_code == 204

def test_targets_api(client, random_string):
    username = f"testuser_{random_string}"
    password = "password123"
    
    res = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # List Targets
    res = client.get("/api/v1/targets", headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)

class MockProvider:
    async def stream(self, messages, tools=None):
        yield StreamChunk(type="text", content="Hello, this is a mock streamed response!")

def test_chat_sse_stream(client, random_string):
    username = f"testuser_{random_string}"
    password = "password123"
    
    res = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Create Session
    res = client.post("/api/v1/sessions", json={"title": "Chat Session"}, headers=headers)
    session_id = res.json()["id"]

    # 2. Test SSE Chat endpoint
    with patch("app.services.chat_service.get_default_provider", return_value=MockProvider()):
        with client.stream(
            "POST", 
            "/api/v1/chat", 
            json={"session_id": session_id, "content": "Hello agent!"}, 
            headers=headers
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
            
            events = []
            for line in response.iter_lines():
                if line.startswith("data: "):
                    events.append(line[6:])
                    
            assert len(events) > 0
            assert events[-1] == "[DONE]"
            
            # Verify basic event structure
            assert '"event": "message_start"' in events[0]
            assert '"event": "content_delta"' in "".join(events)
            assert "mock streamed response!" in "".join(events)
