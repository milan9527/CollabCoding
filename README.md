# CodeSpace — Collaborative Coding Platform

"Google Docs for coding" — real-time collaborative code editing with AI-powered
code generation, built on AWS Bedrock AgentCore.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (React + Monaco)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  Code     │  │  Live    │  │  Team    │  │  AI Agent     │  │
│  │  Editor   │  │  Preview │  │  Chat    │  │  Panel        │  │
│  └────┬─────┘  └──────────┘  └────┬─────┘  └──────┬────────┘  │
│       │ WebSocket (collab)        │               │ REST       │
└───────┼───────────────────────────┼───────────────┼────────────┘
        │                           │               │
┌───────┴───────────────────────────┴───────────────┴────────────┐
│                    Backend (FastAPI + uvicorn)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Collaboration │  │  Memory      │  │  Runtime Service     │  │
│  │ Manager (WS)  │  │  Service     │  │  (File I/O + Agent)  │  │
│  └──────────────┘  └──────┬───────┘  └──────────┬───────────┘  │
└────────────────────────────┼────────────────────┼──────────────┘
                             │                    │
                    ┌────────┴────────┐  ┌────────┴────────────┐
                    │ AgentCore Memory│  │ AgentCore Runtime    │
                    │ (Conversations) │  │ (Persistent Session  │
                    │ STM + Semantic  │  │  Storage @ /mnt/     │
                    └─────────────────┘  │  workspace)          │
                                         │ ┌──────────────────┐ │
                                         │ │ Strands Agent     │ │
                                         │ │ (Code Generation) │ │
                                         │ └──────────────────┘ │
                                         │ ┌──────────────────┐ │
                                         │ │ Direct File I/O  │ │
                                         │ │ (Save/Read, no   │ │
                                         │ │  LLM needed)     │ │
                                         │ └──────────────────┘ │
                                         └──────────────────────┘
```

## Features

- **Real-time collaborative editing** — Monaco editor with WebSocket sync,
  cursor presence, and multi-user awareness
- **AI code generation** — Natural language → code via Strands agent in
  AgentCore Runtime
- **Persistent file storage** — Files survive session stop/resume via
  AgentCore Runtime Session Storage (`/mnt/workspace`)
- **Conversation memory** — Chat history stored in AgentCore Memory (STM +
  semantic search), restored on login
- **Live preview** — Instant website preview with HTML file selector
- **Ctrl+S save** — Explicit save to persistent storage with visual feedback
- **Role-based collaboration** — Developer, Designer, and Product Manager roles
- **Team chat** — Real-time messaging alongside the code editor

## Prerequisites

- AWS account with Bedrock AgentCore access
- Python 3.12+
- Node.js 18+
- AWS credentials configured (`aws configure`)

## Quick Start (Automated)

```bash
# Clone and deploy everything
chmod +x deploy.sh
./deploy.sh              # Uses us-east-1 by default
./deploy.sh us-west-2    # Or specify a region

# Start the server
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 3000

# Open http://localhost:3000
```

The deploy script will:
1. Install all Python and Node.js dependencies
2. Create an AgentCore Memory resource with semantic strategy
3. Deploy the coding agent to AgentCore Runtime
4. Configure persistent session storage at `/mnt/workspace`
5. Build the React frontend
6. Write the `.env` config file

## Manual Setup

### 1. Install Dependencies

```bash
# Backend
pip install fastapi uvicorn websockets python-dotenv boto3 pydantic \
    bedrock-agentcore strands-agents strands-agents-tools \
    bedrock-agentcore-starter-toolkit

# Frontend
cd frontend && npm install && cd ..
```

### 2. Create AgentCore Memory

```bash
agentcore memory create CodeSpaceMemory \
    --strategies '[{"semanticMemoryStrategy": {"name": "Facts"}}]' \
    --region us-east-1 --wait
```

Save the returned memory ID (e.g. `CodeSpaceMemory-abc123`).

### 3. Deploy the Coding Agent

```bash
cd backend

# Configure (generates .bedrock_agentcore.yaml)
agentcore configure --entrypoint agent.py --non-interactive \
    --region us-east-1 --disable-memory

# Deploy to AgentCore Runtime
agentcore launch
```

### 4. Add Persistent Session Storage

```python
import boto3
client = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
# Use the agent runtime ID from the deploy output
client.update_agent_runtime(
    agentRuntimeId="your-agent-id",
    agentRuntimeArtifact=...,  # from get_agent_runtime()
    roleArn=...,               # from get_agent_runtime()
    networkConfiguration=...,  # from get_agent_runtime()
    filesystemConfigurations=[{"sessionStorage": {"mountPath": "/mnt/workspace"}}],
)
```

### 5. Configure Environment

```bash
cp backend/.env.example backend/.env
# Edit with your resource IDs:
#   AGENTCORE_MEMORY_ID=CodeSpaceMemory-abc123
#   AGENT_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:...:runtime/...
```

### 6. Build Frontend & Start

```bash
cd frontend && npx vite build && cd ..
cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 3000
```

Open http://localhost:3000.

## How It Works

### Shared Spaces
Each space maps to an AgentCore Runtime session. Multiple users connect via
WebSocket and see each other's edits, cursors, and chat in real time.

### AI Agent (AgentCore Runtime)
When a user sends a prompt (e.g. "Create a search page"), the backend invokes
the Strands agent in AgentCore Runtime. The agent writes files to the
persistent session filesystem at `/mnt/workspace/<space_id>/`. The agent
creates self-contained HTML files with inline CSS/JS to avoid session storage
write buffer limits.

### File Save (Direct I/O)
Editor saves use `direct_write` actions — plain Python `open().write()` on the
Runtime filesystem. No LLM invocation, instant (~10ms), no concurrency issues
with the agent.

### Conversation Memory (AgentCore Memory)
Every user message and agent response is stored in AgentCore Memory with
STM + semantic search. Conversations persist across sessions — logging in
with the same username restores your full chat history.

### Persistent Session Storage
Files on `/mnt/workspace` are asynchronously replicated to durable storage.
Even if the session stops, resuming restores all files exactly as they were.

## Testing

```bash
pip install pytest pytest-asyncio httpx websockets

# All tests (29 total)
pytest tests/test_codespace.py -v

# Fast tests only — no AWS calls (23 tests, ~10s)
pytest tests/test_codespace.py -v -m "not slow"

# Agent/Runtime/Memory tests only (6 tests, ~30s)
pytest tests/test_codespace.py -v -m slow
```

## Teardown

```bash
chmod +x teardown.sh
./teardown.sh
```

Removes the AgentCore Runtime agent and Memory resource.

## Project Structure

```
├── deploy.sh                  # Automated deployment script
├── teardown.sh                # Resource cleanup script
├── backend/
│   ├── main.py                # FastAPI server (API + WebSocket + static files)
│   ├── agent.py               # Strands agent (deployed to AgentCore Runtime)
│   ├── runtime_service.py     # AgentCore Runtime client (agent + direct I/O)
│   ├── memory_service.py      # AgentCore Memory client
│   ├── collaboration.py       # WebSocket collaboration manager
│   ├── models.py              # Pydantic schemas
│   ├── config.py              # Environment config
│   ├── requirements.txt       # Agent dependencies (for Runtime deploy)
│   └── server_requirements.txt # Backend server dependencies
├── frontend/
│   ├── src/App.jsx            # Main React app (editor, preview, chat, agent)
│   ├── src/api.js             # API client
│   ├── src/useWebSocket.js    # WebSocket hook
│   └── dist/                  # Built static files (served by backend)
└── tests/
    └── test_codespace.py      # 29 tests covering all features
```
