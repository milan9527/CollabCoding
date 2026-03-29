#!/usr/bin/env bash
#
# CodeSpace — Teardown Script
# Removes all AWS AgentCore resources created by deploy.sh
#
# Usage:
#   chmod +x teardown.sh
#   ./teardown.sh

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/backend" && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "============================================"
echo "  CodeSpace Teardown"
echo "============================================"
echo ""

# Read config
if [[ -f "$BACKEND_DIR/.env" ]]; then
    source "$BACKEND_DIR/.env"
else
    echo -e "${RED}No .env found. Nothing to tear down.${NC}"
    exit 0
fi

REGION="${AWS_REGION:-us-east-1}"

echo "This will destroy:"
echo "  - AgentCore Runtime agent"
echo "  - AgentCore Memory: ${AGENTCORE_MEMORY_ID:-none}"
echo "  Region: $REGION"
echo ""
read -p "Are you sure? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Destroy agent runtime
echo "Destroying AgentCore Runtime..."
cd "$BACKEND_DIR"
agentcore destroy --force 2>&1 | tail -3 || true
echo -e "${GREEN}[✓]${NC} Runtime destroyed"

# Delete memory
if [[ -n "${AGENTCORE_MEMORY_ID:-}" ]]; then
    echo "Deleting AgentCore Memory: $AGENTCORE_MEMORY_ID..."
    agentcore memory delete "$AGENTCORE_MEMORY_ID" --region "$REGION" --wait 2>&1 | tail -3 || true
    echo -e "${GREEN}[✓]${NC} Memory deleted"
fi

echo ""
echo "Teardown complete."
