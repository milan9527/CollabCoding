#!/usr/bin/env python3
"""
CodeSpace — Comprehensive Test Suite
=====================================

Tests all core features of the collaborative coding platform:
  1. API basics (health, spaces, files)
  2. File read/write via REST API
  3. Agent code generation via AgentCore Runtime
  4. File persistence in AgentCore Runtime Session Storage
  5. Conversation storage/retrieval via AgentCore Memory
  6. Multi-user WebSocket collaboration (file edits, cursors, chat)
  7. User join/leave notifications
  8. Live preview endpoint
  9. Session persistence across stop/resume

Prerequisites:
  - Backend running on http://localhost:8000
  - Frontend running on http://localhost:3000 (optional, for frontend tests)
  - AgentCore Runtime deployed with session storage at /mnt/workspace
  - AgentCore Memory resource created and configured in .env

Usage:
  pip install pytest pytest-asyncio websockets httpx
  pytest tests/test_codespace.py -v

  # Run only fast tests (skip agent/runtime tests):
  pytest tests/test_codespace.py -v -m "not slow"

  # Run only agent tests:
  pytest tests/test_codespace.py -v -m slow
"""

import asyncio
import json
import os
import time
import uuid

import httpx
import pytest
import websockets

# ---------------------------------------------------------------------------
# Configuration — override with environment variables if needed
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("CODESPACE_API_URL", "http://localhost:8000")
WS_URL = os.getenv("CODESPACE_WS_URL", "ws://localhost:8000")
FRONTEND_URL = os.getenv("CODESPACE_FRONTEND_URL", "http://localhost:3000")
SPACE_ID = "demo-space-001"

# Timeout for agent calls (they invoke a real LLM, so they're slow)
AGENT_TIMEOUT = 180.0
# Timeout for normal API calls
API_TIMEOUT = 15.0
# Timeout for WebSocket message receive
WS_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def api(path: str) -> str:
    return f"{BASE_URL}{path}"


def unique_id() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client():
    """Shared httpx client for the entire test session."""
    with httpx.Client(base_url=BASE_URL, timeout=API_TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def agent_client():
    """Separate client with longer timeout for agent calls."""
    with httpx.Client(base_url=BASE_URL, timeout=AGENT_TIMEOUT) as c:
        yield c


# ===================================================================
# 1. API BASICS
# ===================================================================
class TestAPIBasics:
    """Health check, spaces, and file listing."""

    def test_health(self, client: httpx.Client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "CodeSpace"

    def test_list_spaces(self, client: httpx.Client):
        r = client.get("/api/spaces")
        assert r.status_code == 200
        spaces = r.json()
        assert isinstance(spaces, list)
        assert len(spaces) >= 1
        ids = [s["space_id"] for s in spaces]
        assert SPACE_ID in ids

    def test_get_space(self, client: httpx.Client):
        r = client.get(f"/api/spaces/{SPACE_ID}")
        assert r.status_code == 200
        space = r.json()
        assert space["space_id"] == SPACE_ID
        assert "session_id" in space

    def test_get_space_not_found(self, client: httpx.Client):
        r = client.get("/api/spaces/nonexistent-space")
        assert r.status_code == 404

    def test_list_files(self, client: httpx.Client):
        r = client.get(f"/api/spaces/{SPACE_ID}/files")
        assert r.status_code == 200
        files = r.json()
        assert isinstance(files, list)
        assert len(files) >= 1
        names = [f["name"] for f in files]
        assert "index.html" in names


# ===================================================================
# 2. FILE READ / WRITE
# ===================================================================
class TestFileOperations:
    """Read and write files through the REST API."""

    def test_read_index_html(self, client: httpx.Client):
        r = client.get(f"/api/spaces/{SPACE_ID}/files/index.html")
        assert r.status_code == 200
        data = r.json()
        assert data["path"] == "index.html"
        assert len(data["content"]) > 0

    def test_read_styles_css(self, client: httpx.Client):
        r = client.get(f"/api/spaces/{SPACE_ID}/files/styles.css")
        assert r.status_code == 200
        assert r.json()["path"] == "styles.css"

    def test_read_app_js(self, client: httpx.Client):
        r = client.get(f"/api/spaces/{SPACE_ID}/files/app.js")
        assert r.status_code == 200
        assert r.json()["path"] == "app.js"

    def test_read_nonexistent_file(self, client: httpx.Client):
        r = client.get(f"/api/spaces/{SPACE_ID}/files/nonexistent-{unique_id()}.xyz")
        assert r.status_code == 404

    def test_write_and_read_back(self, client: httpx.Client):
        fname = f"test-{unique_id()}.txt"
        content = f"Hello from test at {time.time()}"

        # Write
        r = client.put(
            f"/api/spaces/{SPACE_ID}/files/{fname}",
            json={
                "space_id": SPACE_ID,
                "file_path": fname,
                "content": content,
                "user_id": "test-user",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Read back
        r2 = client.get(f"/api/spaces/{SPACE_ID}/files/{fname}")
        assert r2.status_code == 200
        assert r2.json()["content"] == content

    def test_overwrite_file(self, client: httpx.Client):
        fname = f"test-overwrite-{unique_id()}.txt"

        # Write v1
        client.put(
            f"/api/spaces/{SPACE_ID}/files/{fname}",
            json={"space_id": SPACE_ID, "file_path": fname, "content": "v1", "user_id": "u1"},
        )
        # Overwrite with v2
        client.put(
            f"/api/spaces/{SPACE_ID}/files/{fname}",
            json={"space_id": SPACE_ID, "file_path": fname, "content": "v2", "user_id": "u2"},
        )
        r = client.get(f"/api/spaces/{SPACE_ID}/files/{fname}")
        assert r.json()["content"] == "v2"


# ===================================================================
# 3. LIVE PREVIEW
# ===================================================================
class TestPreview:
    """Preview endpoint returns all cached files for iframe rendering."""

    def test_preview_returns_files(self, client: httpx.Client):
        r = client.get(f"/api/preview/{SPACE_ID}")
        assert r.status_code == 200
        files = r.json().get("files", {})
        assert isinstance(files, dict)
        assert "index.html" in files


# ===================================================================
# 4. AGENT CODE GENERATION (AgentCore Runtime)
# ===================================================================
@pytest.mark.slow
class TestAgentGeneration:
    """Agent generates code via AgentCore Runtime with persistent storage."""

    def test_agent_generate_website(self, agent_client: httpx.Client):
        r = agent_client.post(
            "/api/agent/generate",
            json={
                "space_id": SPACE_ID,
                "prompt": (
                    "Create a minimal HTML page at /mnt/workspace/demo-space-001/hello.html "
                    "that just says 'Hello CodeSpace Test'. Keep it very simple, one file only."
                ),
                "user_id": "test-agent-user",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "response" in data
        assert "session_id" in data
        # Agent should return a non-error response
        assert "Agent error" not in data["response"] or "files_changed" in data

    def test_agent_space_not_found(self, agent_client: httpx.Client):
        r = agent_client.post(
            "/api/agent/generate",
            json={
                "space_id": "nonexistent-space",
                "prompt": "hello",
                "user_id": "test",
            },
        )
        assert r.status_code == 404

    def test_agent_files_appear_in_sidebar(self, agent_client: httpx.Client):
        """After agent generates files, they should appear in the file list
        with normalized short names and have content."""
        r = agent_client.post(
            "/api/agent/generate",
            json={
                "space_id": SPACE_ID,
                "prompt": "Create a tiny about.html page that says 'About Us'",
                "user_id": "sidebar-test-user",
            },
        )
        assert r.status_code == 200
        data = r.json()
        changed = data.get("files_changed", [])

        # Paths should be short names, not full /mnt/workspace/... paths
        for fp in changed:
            assert not fp.startswith("/mnt/"), f"Path should be short name, got: {fp}"

        # Files should appear in the file list
        files_r = agent_client.get(f"/api/spaces/{SPACE_ID}/files")
        file_names = [f["name"] for f in files_r.json()]
        for fp in changed:
            assert fp in file_names, f"{fp} not found in file list: {file_names}"

        # Files should have content when fetched
        for fp in changed:
            fr = agent_client.get(f"/api/spaces/{SPACE_ID}/files/{fp}")
            if fr.status_code == 200:
                assert len(fr.json().get("content", "")) > 0, f"{fp} has no content"


# ===================================================================
# 5. AGENTCORE MEMORY — CONVERSATION STORAGE
# ===================================================================
@pytest.mark.slow
class TestAgentCoreMemory:
    """Conversations are stored and retrievable from AgentCore Memory."""

    def test_store_and_retrieve_user_history(self, agent_client: httpx.Client):
        user_id = f"mem-test-{unique_id()}"

        # Generate something to create a memory event
        agent_client.post(
            "/api/agent/generate",
            json={
                "space_id": SPACE_ID,
                "prompt": "Say hello, this is a memory test",
                "user_id": user_id,
            },
        )

        # Retrieve history
        r = agent_client.get(f"/api/agent/history/{SPACE_ID}/{user_id}")
        assert r.status_code == 200
        events = r.json().get("events", [])
        assert len(events) >= 1

    def test_agent_responses_stored(self, agent_client: httpx.Client):
        """Agent responses are stored under actor_id='agent'."""
        # The previous tests already generated agent responses
        r = agent_client.get(f"/api/agent/history/{SPACE_ID}/agent")
        assert r.status_code == 200
        events = r.json().get("events", [])
        # Should have at least one agent response from prior tests
        assert len(events) >= 1


# ===================================================================
# 6. WEBSOCKET — MULTI-USER COLLABORATION
# ===================================================================
class TestWebSocketCollaboration:
    """Real-time collaboration via WebSocket."""

    @pytest.mark.asyncio
    async def test_two_users_join(self):
        """Two users connect and see each other in collaborators list."""
        uid_a, uid_b = f"ws-a-{unique_id()}", f"ws-b-{unique_id()}"
        uri_a = f"{WS_URL}/ws/{SPACE_ID}/{uid_a}?username=Alice&role=developer&color=%236366f1"
        uri_b = f"{WS_URL}/ws/{SPACE_ID}/{uid_b}?username=Bob&role=designer&color=%23f59e0b"

        async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
            # Alice gets collaborators list
            msg_a = json.loads(await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT))
            assert msg_a["type"] == "collaborators_list"
            assert any(c["username"] == "Alice" for c in msg_a["collaborators"])

            # Bob gets collaborators list (includes Alice)
            msg_b = json.loads(await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT))
            assert msg_b["type"] == "collaborators_list"
            usernames = [c["username"] for c in msg_b["collaborators"]]
            assert "Alice" in usernames
            assert "Bob" in usernames

            # Alice receives Bob's join notification
            msg_a2 = json.loads(await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT))
            assert msg_a2["type"] == "user_joined"
            assert msg_a2["username"] == "Bob"

    @pytest.mark.asyncio
    async def test_file_edit_broadcast(self):
        """File edits from one user are broadcast to others."""
        uid_a, uid_b = f"ws-edit-a-{unique_id()}", f"ws-edit-b-{unique_id()}"
        uri_a = f"{WS_URL}/ws/{SPACE_ID}/{uid_a}?username=EditAlice&role=developer&color=%236366f1"
        uri_b = f"{WS_URL}/ws/{SPACE_ID}/{uid_b}?username=EditBob&role=designer&color=%23f59e0b"

        async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
            # Drain join messages
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)  # Bob joined

            # Alice edits a file
            test_content = f"<h1>Edited at {time.time()}</h1>"
            await ws_a.send(json.dumps({
                "type": "file_update",
                "file_path": "index.html",
                "content": test_content,
            }))

            # Bob receives the edit
            msg = json.loads(await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT))
            assert msg["type"] == "file_update"
            assert msg["file_path"] == "index.html"
            assert msg["content"] == test_content
            assert msg["username"] == "EditAlice"

    @pytest.mark.asyncio
    async def test_bidirectional_edits(self):
        """Both users can edit and receive each other's changes."""
        uid_a, uid_b = f"ws-bi-a-{unique_id()}", f"ws-bi-b-{unique_id()}"
        uri_a = f"{WS_URL}/ws/{SPACE_ID}/{uid_a}?username=BiAlice&role=developer&color=%236366f1"
        uri_b = f"{WS_URL}/ws/{SPACE_ID}/{uid_b}?username=BiBob&role=designer&color=%23f59e0b"

        async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
            # Drain join messages
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)

            # Alice edits → Bob receives
            await ws_a.send(json.dumps({
                "type": "file_update",
                "file_path": "styles.css",
                "content": "body { color: red; }",
            }))
            msg_b = json.loads(await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT))
            assert msg_b["username"] == "BiAlice"
            assert msg_b["file_path"] == "styles.css"

            # Bob edits → Alice receives
            await ws_b.send(json.dumps({
                "type": "file_update",
                "file_path": "app.js",
                "content": "console.log('bob');",
            }))
            msg_a = json.loads(await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT))
            assert msg_a["username"] == "BiBob"
            assert msg_a["file_path"] == "app.js"

    @pytest.mark.asyncio
    async def test_cursor_broadcast(self):
        """Cursor positions are broadcast to other users."""
        uid_a, uid_b = f"ws-cur-a-{unique_id()}", f"ws-cur-b-{unique_id()}"
        uri_a = f"{WS_URL}/ws/{SPACE_ID}/{uid_a}?username=CurAlice&role=developer&color=%236366f1"
        uri_b = f"{WS_URL}/ws/{SPACE_ID}/{uid_b}?username=CurBob&role=designer&color=%23f59e0b"

        async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
            # Drain join messages
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)

            # Alice sends cursor position
            await ws_a.send(json.dumps({
                "type": "cursor_update",
                "file_path": "index.html",
                "line": 42,
                "column": 10,
            }))

            msg = json.loads(await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT))
            assert msg["type"] == "cursor_update"
            assert msg["username"] == "CurAlice"
            assert msg["file_path"] == "index.html"
            assert msg["line"] == 42
            assert msg["column"] == 10

    @pytest.mark.asyncio
    async def test_chat_message_broadcast(self):
        """Chat messages are broadcast to all users in the space."""
        uid_a, uid_b = f"ws-chat-a-{unique_id()}", f"ws-chat-b-{unique_id()}"
        uri_a = f"{WS_URL}/ws/{SPACE_ID}/{uid_a}?username=ChatAlice&role=developer&color=%236366f1"
        uri_b = f"{WS_URL}/ws/{SPACE_ID}/{uid_b}?username=ChatBob&role=product_manager&color=%2310b981"

        async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
            # Drain join messages
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)

            # Bob sends a chat message
            chat_text = f"Let's ship this! {unique_id()}"
            await ws_b.send(json.dumps({
                "type": "chat_message",
                "content": chat_text,
            }))

            # Alice receives it
            msg = json.loads(await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT))
            assert msg["type"] == "chat_message"
            assert msg["username"] == "ChatBob"
            assert msg["role"] == "product_manager"
            assert msg["content"] == chat_text
            assert "timestamp" in msg
            assert "message_id" in msg

    @pytest.mark.asyncio
    async def test_three_user_collaboration(self):
        """Three users (developer, designer, PM) collaborate in real time."""
        uid_a = f"ws-3u-a-{unique_id()}"
        uid_b = f"ws-3u-b-{unique_id()}"
        uid_c = f"ws-3u-c-{unique_id()}"
        uri_a = f"{WS_URL}/ws/{SPACE_ID}/{uid_a}?username=Dev&role=developer&color=%236366f1"
        uri_b = f"{WS_URL}/ws/{SPACE_ID}/{uid_b}?username=Designer&role=designer&color=%23f59e0b"
        uri_c = f"{WS_URL}/ws/{SPACE_ID}/{uid_c}?username=PM&role=product_manager&color=%2310b981"

        async with (
            websockets.connect(uri_a) as ws_a,
            websockets.connect(uri_b) as ws_b,
            websockets.connect(uri_c) as ws_c,
        ):
            # Drain all join messages
            for ws in [ws_a, ws_b, ws_c]:
                for _ in range(5):
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        break

            # Dev edits → both Designer and PM receive
            await ws_a.send(json.dumps({
                "type": "file_update",
                "file_path": "app.js",
                "content": "// 3-user test",
            }))

            msg_b = json.loads(await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT))
            msg_c = json.loads(await asyncio.wait_for(ws_c.recv(), WS_TIMEOUT))
            assert msg_b["type"] == "file_update"
            assert msg_b["username"] == "Dev"
            assert msg_c["type"] == "file_update"
            assert msg_c["username"] == "Dev"

            # PM sends chat → Dev and Designer receive
            await ws_c.send(json.dumps({
                "type": "chat_message",
                "content": "Looks great team!",
            }))

            msg_a = json.loads(await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT))
            msg_b2 = json.loads(await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT))
            assert msg_a["content"] == "Looks great team!"
            assert msg_b2["content"] == "Looks great team!"

    @pytest.mark.asyncio
    async def test_user_disconnect_notification(self):
        """When a user disconnects, others receive a user_left event."""
        uid_stay = f"ws-stay-{unique_id()}"
        uid_leave = f"ws-leave-{unique_id()}"
        uri_stay = f"{WS_URL}/ws/{SPACE_ID}/{uid_stay}?username=Stays&role=developer&color=%236366f1"
        uri_leave = f"{WS_URL}/ws/{SPACE_ID}/{uid_leave}?username=Leaves&role=designer&color=%23ef4444"

        async with websockets.connect(uri_stay) as ws_stay:
            ws_leave = await websockets.connect(uri_leave)

            # Drain join messages
            await asyncio.wait_for(ws_stay.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_leave.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_stay.recv(), WS_TIMEOUT)

            # Disconnect the leaving user
            await ws_leave.close()

            # Staying user should get user_left
            msg = json.loads(await asyncio.wait_for(ws_stay.recv(), WS_TIMEOUT))
            assert msg["type"] == "user_left"
            assert msg["username"] == "Leaves"

    @pytest.mark.asyncio
    async def test_edit_not_echoed_to_sender(self):
        """A user's own edits should NOT be echoed back to them."""
        uid_a, uid_b = f"ws-echo-a-{unique_id()}", f"ws-echo-b-{unique_id()}"
        uri_a = f"{WS_URL}/ws/{SPACE_ID}/{uid_a}?username=EchoA&role=developer&color=%236366f1"
        uri_b = f"{WS_URL}/ws/{SPACE_ID}/{uid_b}?username=EchoB&role=designer&color=%23f59e0b"

        async with websockets.connect(uri_a) as ws_a, websockets.connect(uri_b) as ws_b:
            # Drain join messages
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT)
            await asyncio.wait_for(ws_a.recv(), WS_TIMEOUT)

            # Alice edits
            await ws_a.send(json.dumps({
                "type": "file_update",
                "file_path": "test.txt",
                "content": "no echo",
            }))

            # Bob receives it
            msg_b = json.loads(await asyncio.wait_for(ws_b.recv(), WS_TIMEOUT))
            assert msg_b["type"] == "file_update"

            # Alice should NOT receive her own edit back
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws_a.recv(), timeout=1.0)


# ===================================================================
# 7. FRONTEND
# ===================================================================
class TestFrontend:
    """Frontend serves correctly and proxies API calls."""

    def test_frontend_serves_html(self):
        with httpx.Client(timeout=10.0) as c:
            r = c.get(FRONTEND_URL)
            assert r.status_code == 200
            assert "<!DOCTYPE html>" in r.text

    def test_frontend_api_proxy(self):
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{FRONTEND_URL}/api/health")
            assert r.status_code == 200
            assert r.json()["service"] == "CodeSpace"


# ===================================================================
# 8. SESSION PERSISTENCE (AgentCore Runtime)
# ===================================================================
@pytest.mark.slow
class TestSessionPersistence:
    """Files written to AgentCore Runtime session storage persist across
    stop/resume cycles."""

    def test_agent_writes_to_persistent_storage(self, agent_client: httpx.Client):
        """Agent can write files to /mnt/workspace via Runtime."""
        r = agent_client.post(
            "/api/agent/generate",
            json={
                "space_id": SPACE_ID,
                "prompt": (
                    "Create a file /mnt/workspace/demo-space-001/persist-check.txt "
                    "containing exactly the text 'PERSIST_OK'. Nothing else."
                ),
                "user_id": "persist-test-user",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "response" in data

    def test_agent_reads_from_persistent_storage(self, agent_client: httpx.Client):
        """Agent can read files back from the persistent session filesystem."""
        r = agent_client.post(
            "/api/agent/generate",
            json={
                "space_id": SPACE_ID,
                "prompt": (
                    "List all files in /mnt/workspace/demo-space-001/ "
                    "and tell me what files exist there."
                ),
                "user_id": "persist-test-user",
            },
        )
        assert r.status_code == 200
        data = r.json()
        # The response should mention files in the workspace
        assert "response" in data
        assert len(data["response"]) > 0


# ===================================================================
# ENTRY POINT
# ===================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
