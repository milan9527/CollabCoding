"""CodeSpace — collaborative coding platform API.

Provides REST endpoints for spaces/files/agent and WebSocket
endpoint for real-time collaboration.
"""
import json
import uuid
import logging
import os
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from models import (
    AgentRequest, AgentResponse, FileUpdate, FileNode,
    Space, User, UserRole, ChatMessage,
)
from collaboration import collab_manager
from memory_service import memory_service
from runtime_service import runtime_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CodeSpace", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory stores (would be DynamoDB in production)
spaces_db: dict[str, dict] = {}
users_db: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Bootstrap: seed a demo space so the UI has something to show immediately
# ---------------------------------------------------------------------------
DEMO_SPACE_ID = "demo-space-001"
DEMO_SESSION_ID = "codespace-demo-session-00000000-0009"
spaces_db[DEMO_SPACE_ID] = {
    "space_id": DEMO_SPACE_ID,
    "name": "Demo Project",
    "description": "A collaborative demo workspace",
    "owner_id": "system",
    "session_id": DEMO_SESSION_ID,
}

# Seed default files for the demo space
_default_files: dict[str, dict] = {
    "index.html": {
        "path": "index.html",
        "name": "index.html",
        "language": "html",
        "is_directory": False,
        "content": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>My Website</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header class="hero">
    <nav>
      <div class="logo">CodeSpace</div>
      <ul>
        <li><a href="#features">Features</a></li>
        <li><a href="#about">About</a></li>
        <li><a href="#contact">Contact</a></li>
      </ul>
    </nav>
    <div class="hero-content">
      <h1>Build Together</h1>
      <p>Collaborative coding for teams that ship fast.</p>
      <button onclick="handleClick()">Get Started</button>
    </div>
  </header>
  <section id="features" class="features">
    <h2>Features</h2>
    <div class="cards">
      <div class="card">
        <h3>Real-time Editing</h3>
        <p>See changes from your team instantly.</p>
      </div>
      <div class="card">
        <h3>AI Assistant</h3>
        <p>Generate code with natural language.</p>
      </div>
      <div class="card">
        <h3>Live Preview</h3>
        <p>Preview your website as you build.</p>
      </div>
    </div>
  </section>
  <script src="app.js"></script>
</body>
</html>""",
    },
    "styles.css": {
        "path": "styles.css",
        "name": "styles.css",
        "language": "css",
        "is_directory": False,
        "content": """* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', system-ui, sans-serif; color: #e2e8f0; background: #0f172a; }
.hero {
  min-height: 80vh; display: flex; flex-direction: column;
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
}
nav {
  display: flex; justify-content: space-between; align-items: center;
  padding: 1.5rem 3rem;
}
.logo { font-size: 1.5rem; font-weight: 700; color: #818cf8; }
nav ul { list-style: none; display: flex; gap: 2rem; }
nav a { color: #94a3b8; text-decoration: none; transition: color 0.2s; }
nav a:hover { color: #e2e8f0; }
.hero-content {
  flex: 1; display: flex; flex-direction: column;
  justify-content: center; align-items: center; text-align: center; padding: 2rem;
}
.hero-content h1 { font-size: 4rem; font-weight: 800; margin-bottom: 1rem; }
.hero-content p { font-size: 1.25rem; color: #94a3b8; margin-bottom: 2rem; }
button {
  padding: 0.875rem 2rem; font-size: 1rem; font-weight: 600;
  background: #6366f1; color: white; border: none; border-radius: 0.5rem;
  cursor: pointer; transition: background 0.2s;
}
button:hover { background: #4f46e5; }
.features { padding: 5rem 3rem; text-align: center; }
.features h2 { font-size: 2.5rem; margin-bottom: 3rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 2rem; }
.card {
  background: #1e293b; padding: 2rem; border-radius: 1rem;
  border: 1px solid #334155; transition: transform 0.2s, border-color 0.2s;
}
.card:hover { transform: translateY(-4px); border-color: #6366f1; }
.card h3 { color: #818cf8; margin-bottom: 0.75rem; font-size: 1.25rem; }
.card p { color: #94a3b8; line-height: 1.6; }""",
    },
    "app.js": {
        "path": "app.js",
        "name": "app.js",
        "language": "javascript",
        "is_directory": False,
        "content": """// CodeSpace — interactive scripts
function handleClick() {
  alert('Welcome to CodeSpace! Start building together.');
}

document.addEventListener('DOMContentLoaded', () => {
  console.log('CodeSpace loaded');
});""",
    },
}

# Pre-populate the collaboration file cache with demo files
collab_manager.file_cache[DEMO_SPACE_ID] = {
    fp: info["content"] for fp, info in _default_files.items()
}


@app.on_event("startup")
async def hydrate_cache_from_runtime():
    """On startup, load files from Runtime persistent storage into the cache.

    This restores previously generated files after a server restart.
    """
    import asyncio
    def _hydrate():
        try:
            session_id = DEMO_SESSION_ID
            rt_files = runtime_service.list_files(session_id, DEMO_SPACE_ID)
            if rt_files:
                file_names = [f["name"] for f in rt_files if not f.get("is_directory")]
                if file_names:
                    contents = runtime_service.read_files_batch(session_id, DEMO_SPACE_ID, file_names)
                    for name, content in contents.items():
                        if content:
                            collab_manager.file_cache[DEMO_SPACE_ID][name] = content
                    logger.info(f"Hydrated {len(contents)} files from Runtime")
        except Exception as e:
            logger.warning(f"Could not hydrate from Runtime (session may be new): {e}")

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _hydrate)


# ---- REST Endpoints -------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "CodeSpace"}


# -- Spaces ------------------------------------------------------------------

@app.post("/api/spaces")
async def create_space(space: Space):
    spaces_db[space.space_id] = space.model_dump()
    return space


@app.get("/api/spaces")
async def list_spaces():
    return list(spaces_db.values())


@app.get("/api/spaces/{space_id}")
async def get_space(space_id: str):
    if space_id not in spaces_db:
        raise HTTPException(404, "Space not found")
    return spaces_db[space_id]


# -- Files -------------------------------------------------------------------

@app.get("/api/spaces/{space_id}/files")
async def list_files(space_id: str):
    """List files — prefer collaboration cache, fall back to Runtime."""
    if space_id in collab_manager.file_cache:
        files = []
        for fp, content in collab_manager.file_cache[space_id].items():
            lang = "html"
            if fp.endswith(".css"):
                lang = "css"
            elif fp.endswith(".js"):
                lang = "javascript"
            elif fp.endswith(".json"):
                lang = "json"
            files.append({"path": fp, "name": fp, "language": lang, "is_directory": False})
        return files

    # Fall back to AgentCore Runtime persistent session
    if space_id in spaces_db:
        session_id = spaces_db[space_id]["session_id"]
        return runtime_service.list_files(session_id, space_id)
    return []


@app.get("/api/spaces/{space_id}/files/{file_path:path}")
async def get_file(space_id: str, file_path: str):
    # Check collaboration cache first
    cached = collab_manager.get_cached_file(space_id, file_path)
    if cached is not None:
        return {"path": file_path, "content": cached}

    # Fall back to Runtime persistent storage
    if space_id in spaces_db:
        session_id = spaces_db[space_id]["session_id"]
        content = runtime_service.read_file(session_id, space_id, file_path)
        if content:
            return {"path": file_path, "content": content}
    raise HTTPException(404, "File not found")


@app.put("/api/spaces/{space_id}/files/{file_path:path}")
async def update_file(space_id: str, file_path: str, update: FileUpdate):
    import asyncio
    # Update collaboration cache (instant, in-memory)
    if space_id not in collab_manager.file_cache:
        collab_manager.file_cache[space_id] = {}
    collab_manager.file_cache[space_id][file_path] = update.content

    # Persist to AgentCore Runtime session storage (direct I/O, no LLM)
    if space_id in spaces_db:
        session_id = spaces_db[space_id]["session_id"]
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None, runtime_service.write_file, session_id, space_id, file_path, update.content
        )

    # Broadcast to collaborators via WebSocket
    username = update.user_id
    await collab_manager.broadcast_file_update(
        space_id, file_path, update.content, update.user_id, username
    )
    return {"status": "ok"}


# -- Agent -------------------------------------------------------------------

@app.post("/api/agent/generate", response_model=AgentResponse)
async def agent_generate(req: AgentRequest):
    """Send a prompt to the coding agent running in AgentCore Runtime.

    The agent writes generated files to the persistent session filesystem.
    Conversation is stored in AgentCore Memory.
    """
    space = spaces_db.get(req.space_id)
    if not space:
        raise HTTPException(404, "Space not found")

    session_id = space["session_id"]

    # Store user message in AgentCore Memory
    memory_service.store_conversation_event(
        session_id=session_id,
        actor_id=req.user_id,
        role="user",
        content=req.prompt,
        space_id=req.space_id,
    )

    # Invoke agent in AgentCore Runtime (persistent session)
    result = runtime_service.invoke_agent(session_id, req.prompt, req.space_id)

    agent_response = result.get("response", "")
    files_changed = result.get("files_changed", [])

    # Normalize file paths — strip the /mnt/workspace/<space_id>/ prefix
    # so they match the short names used in the file list and sidebar
    prefix = f"/mnt/workspace/{req.space_id}/"
    normalized_files = []
    for fp in files_changed:
        short = fp.replace(prefix, "") if fp.startswith(prefix) else fp
        # Also strip any leading slash
        short = short.lstrip("/")
        normalized_files.append(short)
    files_changed = normalized_files

    # Store agent response in Memory — under the SAME user's actor_id
    # so each user has their own private conversation thread
    memory_service.store_conversation_event(
        session_id=session_id,
        actor_id=req.user_id,
        role="assistant",
        content=agent_response,
        space_id=req.space_id,
    )

    # Update file cache with agent results
    file_contents_from_agent = result.get("file_contents", {})
    if req.space_id not in collab_manager.file_cache:
        collab_manager.file_cache[req.space_id] = {}

    # Normalize file_contents keys too
    normalized_contents = {}
    for k, v in file_contents_from_agent.items():
        short_k = k.replace(prefix, "") if k.startswith(prefix) else k
        short_k = short_k.lstrip("/")
        normalized_contents[short_k] = v

    for fp in files_changed:
        if fp in normalized_contents and normalized_contents[fp]:
            collab_manager.file_cache[req.space_id][fp] = normalized_contents[fp]
        else:
            # Mark as needing content
            collab_manager.file_cache[req.space_id].setdefault(fp, "")

    # Batch-read ALL changed files from Runtime to get actual content
    if files_changed:
        try:
            batch = runtime_service.read_files_batch(session_id, req.space_id, files_changed)
            for k, v in batch.items():
                short_k = k.replace(prefix, "").lstrip("/") if k.startswith(prefix) else k.lstrip("/")
                if v:
                    collab_manager.file_cache[req.space_id][short_k] = v
        except Exception as e:
            logger.warning(f"Batch read failed: {e}")

    # Clean up any stale full-path keys
    if req.space_id in collab_manager.file_cache:
        stale_prefix = f"/mnt/workspace/{req.space_id}/"
        stale_keys = [k for k in collab_manager.file_cache[req.space_id] if k.startswith(stale_prefix)]
        for k in stale_keys:
            short_key = k.replace(stale_prefix, "")
            if short_key not in collab_manager.file_cache[req.space_id]:
                collab_manager.file_cache[req.space_id][short_key] = collab_manager.file_cache[req.space_id][k]
            del collab_manager.file_cache[req.space_id][k]

    # Broadcast to all collaborators
    await collab_manager.broadcast_agent_response(
        req.space_id, agent_response, files_changed
    )

    return AgentResponse(
        response=agent_response,
        files_changed=files_changed,
        session_id=session_id,
    )


@app.get("/api/agent/history/{space_id}/{user_id}")
async def get_conversation_history(space_id: str, user_id: str):
    """Retrieve conversation history from AgentCore Memory.

    Each user has their own private conversation thread (both user
    prompts and agent replies stored under the user's actor_id).
    """
    space = spaces_db.get(space_id)
    if not space:
        raise HTTPException(404, "Space not found")
    session_id = space["session_id"]
    events = memory_service.retrieve_conversation(session_id, user_id)
    return {"events": events}


# -- Preview -----------------------------------------------------------------

@app.get("/api/preview/{space_id}")
async def get_preview(space_id: str):
    """Return all files for the live preview iframe."""
    files = collab_manager.file_cache.get(space_id, {})
    return {"files": files}


# ---- WebSocket for real-time collaboration ---------------------------------

@app.websocket("/ws/{space_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket, space_id: str, user_id: str
):
    username = websocket.query_params.get("username", user_id)
    role = websocket.query_params.get("role", "developer")
    avatar_color = websocket.query_params.get("color", "#6366f1")

    await collab_manager.connect(websocket, space_id, user_id, username, role, avatar_color)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "file_update":
                await collab_manager.broadcast_file_update(
                    space_id,
                    data["file_path"],
                    data["content"],
                    user_id,
                    username,
                )
            elif msg_type == "cursor_update":
                await collab_manager.broadcast_cursor(
                    space_id, user_id, username, avatar_color,
                    data.get("file_path", ""),
                    data.get("line", 0),
                    data.get("column", 0),
                )
            elif msg_type == "chat_message":
                msg = {
                    "type": "chat_message",
                    "message_id": str(uuid.uuid4()),
                    "space_id": space_id,
                    "user_id": user_id,
                    "username": username,
                    "role": role,
                    "content": data.get("content", ""),
                    "timestamp": datetime.utcnow().isoformat(),
                    "is_agent": False,
                }
                await collab_manager.broadcast(space_id, msg)
    except WebSocketDisconnect:
        collab_manager.disconnect(space_id, user_id)
        await collab_manager.broadcast(space_id, {
            "type": "user_left",
            "user_id": user_id,
            "username": username,
            "timestamp": datetime.utcnow().isoformat(),
        })

# ---- Serve frontend static files ------------------------------------------
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="static")

    # Catch-all: serve index.html for any non-API route (SPA routing)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index)
