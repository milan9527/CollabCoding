#!/usr/bin/env bash
#
# CodeSpace — Full Deployment Script
# ====================================
# Deploys the collaborative coding platform with:
#   - AgentCore Memory (conversation storage)
#   - AgentCore Runtime (code generation agent + persistent session storage)
#   - Backend API server (FastAPI)
#   - Frontend (React, built as static files)
#
# Prerequisites:
#   - AWS credentials configured (aws configure)
#   - Python 3.12+
#   - Node.js 18+
#   - pip, npm installed
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh              # Full deploy (default region: us-east-1)
#   ./deploy.sh us-west-2    # Deploy to specific region
#   ./deploy.sh --skip-aws   # Skip AWS deployment, local only

set -euo pipefail

REGION="${1:-us-east-1}"
SKIP_AWS=false
if [[ "${1:-}" == "--skip-aws" ]]; then
    SKIP_AWS=true
    REGION="us-east-1"
fi

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo "============================================"
echo "  CodeSpace Deployment"
echo "  Region: $REGION"
echo "============================================"
echo ""

# ============================================================
# Step 1: Check prerequisites
# ============================================================
echo "--- Step 1: Checking prerequisites ---"

command -v python3 >/dev/null 2>&1 || err "python3 not found. Install Python 3.12+"
command -v node >/dev/null 2>&1    || err "node not found. Install Node.js 18+"
command -v npm >/dev/null 2>&1     || err "npm not found. Install npm"
command -v pip3 >/dev/null 2>&1    || err "pip3 not found. Install pip"

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log "Python $PYTHON_VER"
log "Node $(node --version)"

# Check AWS credentials
if [[ "$SKIP_AWS" == false ]]; then
    python3 -c "import boto3; boto3.client('sts').get_caller_identity()" 2>/dev/null \
        || err "AWS credentials not configured. Run: aws configure"
    AWS_ACCOUNT=$(python3 -c "import boto3; print(boto3.client('sts').get_caller_identity()['Account'])")
    log "AWS Account: $AWS_ACCOUNT (Region: $REGION)"
fi

# ============================================================
# Step 2: Install dependencies
# ============================================================
echo ""
echo "--- Step 2: Installing dependencies ---"

# Backend (server + agent deps)
pip3 install -q fastapi uvicorn websockets python-dotenv boto3 pydantic \
    bedrock-agentcore strands-agents strands-agents-tools \
    bedrock-agentcore-starter-toolkit 2>&1 | tail -1
log "Backend Python packages installed"

# Frontend
cd "$FRONTEND_DIR"
npm install --silent 2>&1 | tail -1
log "Frontend npm packages installed"
cd "$PROJECT_DIR"

# ============================================================
# Step 3: Deploy AWS AgentCore resources
# ============================================================
if [[ "$SKIP_AWS" == false ]]; then
    echo ""
    echo "--- Step 3: Deploying AgentCore resources ---"

    # --- 3a: Create AgentCore Memory ---
    echo "Creating AgentCore Memory..."
    MEMORY_ID=$(agentcore memory list --region "$REGION" 2>/dev/null \
        | grep -o 'CodeSpaceMemory-[a-zA-Z0-9]*' | head -1 || true)

    if [[ -z "$MEMORY_ID" ]]; then
        agentcore memory create CodeSpaceMemory \
            --strategies '[{"semanticMemoryStrategy": {"name": "Facts"}}]' \
            --region "$REGION" --wait 2>&1 | tail -3
        MEMORY_ID=$(agentcore memory list --region "$REGION" 2>/dev/null \
            | grep -o 'CodeSpaceMemory-[a-zA-Z0-9]*' | head -1)
        log "Created Memory: $MEMORY_ID"
    else
        log "Memory already exists: $MEMORY_ID"
    fi

    # --- 3b: Configure and deploy agent to AgentCore Runtime ---
    echo "Deploying agent to AgentCore Runtime..."
    cd "$BACKEND_DIR"

    # Remove old config if exists (let CLI generate fresh)
    if [[ -f .bedrock_agentcore.yaml ]]; then
        # Check if agent already deployed
        EXISTING_ARN=$(python3 -c "
import yaml
with open('.bedrock_agentcore.yaml') as f:
    cfg = yaml.safe_load(f)
for name, agent in cfg.get('agents', {}).items():
    arn = agent.get('bedrock_agentcore', {}).get('agent_arn', '')
    if arn: print(arn); break
" 2>/dev/null || true)
    fi

    if [[ -z "${EXISTING_ARN:-}" ]]; then
        rm -f .bedrock_agentcore.yaml
        agentcore configure \
            --entrypoint agent.py \
            --non-interactive \
            --region "$REGION" \
            --disable-memory 2>&1 | tail -3

        # Rename to avoid name conflicts
        AGENT_NAME="codespace_$(date +%s)"
        python3 -c "
import yaml
with open('.bedrock_agentcore.yaml') as f:
    cfg = yaml.safe_load(f)
old_name = cfg['default_agent']
cfg['default_agent'] = '$AGENT_NAME'
agent = cfg['agents'].pop(old_name)
agent['name'] = '$AGENT_NAME'
cfg['agents']['$AGENT_NAME'] = agent
with open('.bedrock_agentcore.yaml', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
"
        agentcore launch 2>&1 | tail -5
        log "Agent deployed"
    else
        agentcore launch --auto-update-on-conflict 2>&1 | tail -5
        log "Agent updated"
    fi

    # Extract agent ARN from config
    AGENT_ARN=$(python3 -c "
import yaml
with open('.bedrock_agentcore.yaml') as f:
    cfg = yaml.safe_load(f)
for name, agent in cfg.get('agents', {}).items():
    arn = agent.get('bedrock_agentcore', {}).get('agent_arn', '')
    if arn: print(arn); break
")
    AGENT_ID=$(echo "$AGENT_ARN" | grep -o '[^/]*$')
    log "Agent ARN: $AGENT_ARN"

    # --- 3c: Add persistent session storage ---
    echo "Configuring persistent session storage..."
    python3 << PYEOF
import boto3, time
client = boto3.client("bedrock-agentcore-control", region_name="$REGION")
rid = "$AGENT_ID"
d = client.get_agent_runtime(agentRuntimeId=rid)
if not d.get("filesystemConfigurations"):
    print("Adding session storage at /mnt/workspace...")
    client.update_agent_runtime(
        agentRuntimeId=rid,
        agentRuntimeArtifact=d["agentRuntimeArtifact"],
        roleArn=d["roleArn"],
        networkConfiguration=d["networkConfiguration"],
        filesystemConfigurations=[{"sessionStorage": {"mountPath": "/mnt/workspace"}}],
    )
    for _ in range(30):
        if client.get_agent_runtime(agentRuntimeId=rid)["status"] == "READY":
            print("Session storage configured.")
            break
        time.sleep(3)
else:
    print("Session storage already configured.")
PYEOF
    log "Session storage ready"

    # --- 3d: Write .env ---
    cat > "$BACKEND_DIR/.env" << EOF
AWS_REGION=$REGION
AGENTCORE_MEMORY_ID=$MEMORY_ID
AGENT_RUNTIME_ARN=$AGENT_ARN
WORKSPACE_MOUNT_PATH=/mnt/workspace
EOF
    log "Backend .env configured"
    cd "$PROJECT_DIR"

else
    echo ""
    echo "--- Step 3: Skipping AWS deployment (--skip-aws) ---"
    warn "Configure backend/.env manually with your AgentCore resource IDs"
fi

# ============================================================
# Step 4: Build frontend
# ============================================================
echo ""
echo "--- Step 4: Building frontend ---"

cd "$FRONTEND_DIR"
npx vite build 2>&1 | tail -3
log "Frontend built to frontend/dist/"
cd "$PROJECT_DIR"

# ============================================================
# Step 5: Summary
# ============================================================
echo ""
echo "============================================"
echo "  Deployment Complete"
echo "============================================"
echo ""
if [[ "$SKIP_AWS" == false ]]; then
    echo "  AgentCore Memory:  $MEMORY_ID"
    echo "  AgentCore Runtime: $AGENT_ARN"
    echo "  Session Storage:   /mnt/workspace"
fi
echo ""
echo "  Start the server:"
echo "    cd backend"
echo "    python3 -m uvicorn main:app --host 0.0.0.0 --port 3000"
echo ""
echo "  Open in browser:"
echo "    http://localhost:3000"
echo ""
echo "  Run tests:"
echo "    pip install pytest pytest-asyncio httpx websockets"
echo "    pytest tests/test_codespace.py -v"
echo ""
echo "============================================"
