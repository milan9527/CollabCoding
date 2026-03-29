"""Application configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AGENTCORE_MEMORY_ID = os.getenv("AGENTCORE_MEMORY_ID", "")
AGENT_RUNTIME_ARN = os.getenv("AGENT_RUNTIME_ARN", "")
WORKSPACE_MOUNT_PATH = os.getenv("WORKSPACE_MOUNT_PATH", "/mnt/workspace")
