"""Real-time collaboration manager using WebSockets."""
import logging
from datetime import datetime
from typing import Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class CollaborationManager:
    """Manages WebSocket connections and broadcasts for shared spaces."""

    def __init__(self):
        self.active_connections: dict[str, dict[str, dict]] = {}
        self.file_cache: dict[str, dict[str, str]] = {}

    async def connect(
        self, websocket: WebSocket, space_id: str, user_id: str,
        username: str, role: str, avatar_color: str,
    ):
        await websocket.accept()
        if space_id not in self.active_connections:
            self.active_connections[space_id] = {}
        self.active_connections[space_id][user_id] = {
            "ws": websocket, "username": username,
            "role": role, "avatar_color": avatar_color,
        }
        await self.broadcast(space_id, {
            "type": "user_joined", "user_id": user_id,
            "username": username, "role": role,
            "avatar_color": avatar_color,
            "timestamp": datetime.utcnow().isoformat(),
        }, exclude=user_id)
        await websocket.send_json({
            "type": "collaborators_list",
            "collaborators": self.get_collaborators(space_id),
        })

    def disconnect(self, space_id: str, user_id: str):
        if space_id in self.active_connections:
            self.active_connections[space_id].pop(user_id, None)
            if not self.active_connections[space_id]:
                del self.active_connections[space_id]

    def get_collaborators(self, space_id: str) -> list[dict]:
        if space_id not in self.active_connections:
            return []
        return [
            {"user_id": uid, "username": info["username"],
             "role": info["role"], "avatar_color": info["avatar_color"]}
            for uid, info in self.active_connections[space_id].items()
        ]

    async def broadcast(self, space_id: str, message: dict, exclude: Optional[str] = None):
        if space_id not in self.active_connections:
            return
        disconnected = []
        for user_id, info in self.active_connections[space_id].items():
            if user_id == exclude:
                continue
            try:
                await info["ws"].send_json(message)
            except Exception:
                disconnected.append(user_id)
        for uid in disconnected:
            self.disconnect(space_id, uid)

    async def broadcast_file_update(
        self, space_id: str, file_path: str, content: str,
        user_id: str, username: str,
    ):
        if space_id not in self.file_cache:
            self.file_cache[space_id] = {}
        self.file_cache[space_id][file_path] = content
        await self.broadcast(space_id, {
            "type": "file_update", "file_path": file_path,
            "content": content, "user_id": user_id,
            "username": username,
            "timestamp": datetime.utcnow().isoformat(),
        }, exclude=user_id)

    async def broadcast_cursor(
        self, space_id: str, user_id: str, username: str,
        avatar_color: str, file_path: str, line: int, column: int,
    ):
        await self.broadcast(space_id, {
            "type": "cursor_update", "user_id": user_id,
            "username": username, "avatar_color": avatar_color,
            "file_path": file_path, "line": line, "column": column,
        }, exclude=user_id)

    async def broadcast_agent_response(
        self, space_id: str, response: str, files_changed: list[str],
    ):
        await self.broadcast(space_id, {
            "type": "agent_response", "response": response,
            "files_changed": files_changed,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def get_cached_file(self, space_id: str, file_path: str) -> Optional[str]:
        return self.file_cache.get(space_id, {}).get(file_path)


collab_manager = CollaborationManager()
