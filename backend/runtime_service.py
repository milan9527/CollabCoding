"""AgentCore Runtime service for persistent session storage and code generation."""
import json
import logging
import threading
from typing import Optional

import boto3
from config import AWS_REGION, AGENT_RUNTIME_ARN, WORKSPACE_MOUNT_PATH

logger = logging.getLogger(__name__)


class RuntimeService:
    """Manages AgentCore Runtime sessions with persistent filesystem storage.

    File I/O uses 'direct_*' actions that do Python open()/write() on the
    persistent filesystem — no LLM invocation, instant, no concurrency issues.

    Code generation uses 'generate' action which invokes the Strands agent (LLM).
    A per-session lock ensures only one LLM call runs at a time.
    """

    def __init__(self):
        self.region = AWS_REGION
        self.agent_runtime_arn = AGENT_RUNTIME_ARN
        self.mount_path = WORKSPACE_MOUNT_PATH
        self._client = None
        self._session_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    @property
    def client(self):
        if self._client is None:
            from botocore.config import Config
            self._client = boto3.client(
                "bedrock-agentcore",
                region_name=self.region,
                config=Config(
                    read_timeout=300,
                    connect_timeout=10,
                    retries={"max_attempts": 0},
                ),
            )
        return self._client

    def _get_session_lock(self, session_id: str) -> threading.Lock:
        with self._locks_lock:
            if session_id not in self._session_locks:
                self._session_locks[session_id] = threading.Lock()
            return self._session_locks[session_id]

    def _invoke_raw(self, session_id: str, payload: dict) -> dict:
        """Low-level invoke — sends payload, parses response."""
        raw_payload = json.dumps(payload)
        response = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.agent_runtime_arn,
            runtimeSessionId=session_id,
            payload=raw_payload.encode(),
        )
        raw = b"".join(response["response"]).decode()
        return self._parse_agent_response(raw)

    # ---- Code generation (LLM, locked) ------------------------------------

    def invoke_agent(self, session_id: str, prompt: str, space_id: str) -> dict:
        """Invoke the LLM agent for code generation. Locked per-session."""
        lock = self._get_session_lock(session_id)
        lock.acquire()
        try:
            return self._invoke_raw(session_id, {
                "prompt": prompt,
                "session_id": session_id,
                "space_id": space_id,
                "workspace_path": f"{self.mount_path}/{space_id}",
                "action": "generate",
            })
        except Exception as e:
            logger.error(f"Agent invoke failed: {e}")
            return {"response": f"Agent error: {str(e)}", "files_changed": []}
        finally:
            lock.release()

    # ---- Direct file I/O (no LLM, fast) -----------------------------------

    def write_file(self, session_id: str, space_id: str, file_path: str, content: str) -> bool:
        """Write a file to persistent storage. Direct Python I/O, no LLM."""
        lock = self._get_session_lock(session_id)
        lock.acquire()
        try:
            result = self._invoke_raw(session_id, {
                "action": "direct_write",
                "space_id": space_id,
                "file_path": file_path,
                "content": content,
                "workspace_path": f"{self.mount_path}/{space_id}",
            })
            return result.get("response") == "ok"
        except Exception as e:
            logger.error(f"Failed to write file: {e}")
            return False
        finally:
            lock.release()

    def read_file(self, session_id: str, space_id: str, file_path: str) -> Optional[str]:
        """Read a file from persistent storage. Direct Python I/O, no LLM."""
        lock = self._get_session_lock(session_id)
        lock.acquire()
        try:
            result = self._invoke_raw(session_id, {
                "action": "direct_read",
                "space_id": space_id,
                "file_path": file_path,
                "workspace_path": f"{self.mount_path}/{space_id}",
            })
            return result.get("content", "")
        except Exception as e:
            logger.error(f"Failed to read file: {e}")
            return None
        finally:
            lock.release()

    def read_files_batch(self, session_id: str, space_id: str, file_paths: list[str]) -> dict[str, str]:
        """Read multiple files in one call. Direct Python I/O, no LLM."""
        if not file_paths:
            return {}
        lock = self._get_session_lock(session_id)
        lock.acquire()
        try:
            result = self._invoke_raw(session_id, {
                "action": "direct_read_batch",
                "space_id": space_id,
                "file_paths": file_paths,
                "workspace_path": f"{self.mount_path}/{space_id}",
            })
            return result.get("file_contents", {})
        except Exception as e:
            logger.error(f"Failed to batch read: {e}")
            return {}
        finally:
            lock.release()

    def list_files(self, session_id: str, space_id: str) -> list[dict]:
        """List files in persistent storage. Direct Python I/O, no LLM."""
        lock = self._get_session_lock(session_id)
        lock.acquire()
        try:
            result = self._invoke_raw(session_id, {
                "action": "direct_list",
                "space_id": space_id,
                "workspace_path": f"{self.mount_path}/{space_id}",
            })
            return result.get("files", [])
        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            return []
        finally:
            lock.release()

    def stop_session(self, session_id: str):
        """Stop a Runtime session — filesystem is persisted to durable storage."""
        try:
            self.client.stop_runtime_session(
                agentRuntimeArn=self.agent_runtime_arn,
                runtimeSessionId=session_id,
            )
            logger.info(f"Stopped session {session_id}")
        except Exception as e:
            logger.error(f"Failed to stop session: {e}")

    @staticmethod
    def _parse_agent_response(raw: str) -> dict:
        """Parse agent response, handling both direct JSON and LLM-wrapped responses."""
        import re
        try:
            outer = json.loads(raw)
            # Direct actions return clean JSON with known keys — return as-is
            if any(k in outer for k in ("file_contents", "content", "files")):
                return outer
            # LLM responses have a "response" field containing text or nested JSON
            inner_text = outer.get("response", raw)
        except (json.JSONDecodeError, TypeError):
            inner_text = raw

        # Try to extract JSON from markdown code blocks (LLM output)
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", inner_text, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(inner_text)
        except (json.JSONDecodeError, TypeError):
            pass
        return {"response": inner_text, "files_changed": []}


runtime_service = RuntimeService()
