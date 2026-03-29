"""AgentCore Memory service for storing user conversations."""
import logging
from datetime import datetime
from typing import Optional

from bedrock_agentcore.memory import MemoryClient
from config import AWS_REGION, AGENTCORE_MEMORY_ID

logger = logging.getLogger(__name__)


class MemoryService:
    """Manages conversation storage using AgentCore Memory (STM + semantic)."""

    def __init__(self):
        self.memory_id = AGENTCORE_MEMORY_ID
        self.region = AWS_REGION
        self._client = None

    @property
    def client(self) -> MemoryClient:
        if self._client is None:
            self._client = MemoryClient(region_name=self.region)
        return self._client

    def store_conversation_event(
        self,
        session_id: str,
        actor_id: str,
        role: str,
        content: str,
        space_id: str,
    ):
        """Store a conversation event in AgentCore Memory."""
        try:
            msg_role = "USER" if role == "user" else "ASSISTANT"
            self.client.create_event(
                memory_id=self.memory_id,
                actor_id=actor_id,
                session_id=session_id,
                messages=[(content, msg_role)],
            )
            logger.info(f"Stored event for session={session_id}, actor={actor_id}")
        except Exception as e:
            logger.error(f"Failed to store memory event: {e}")

    def retrieve_conversation(
        self, session_id: str, actor_id: str, limit: int = 50
    ) -> list[dict]:
        """Retrieve conversation history from AgentCore Memory."""
        try:
            events = self.client.list_events(
                memory_id=self.memory_id,
                actor_id=actor_id,
                session_id=session_id,
                max_results=limit,
            )
            return events
        except Exception as e:
            logger.error(f"Failed to retrieve conversation: {e}")
            return []

    def search_knowledge(
        self, query: str, namespace: str, top_k: int = 5
    ) -> list[dict]:
        """Search semantic memory for relevant knowledge."""
        try:
            results = self.client.retrieve_memories(
                memory_id=self.memory_id,
                namespace=namespace,
                query=query,
                top_k=top_k,
            )
            return results
        except Exception as e:
            logger.error(f"Failed to search memory: {e}")
            return []


memory_service = MemoryService()
