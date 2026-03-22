#!/bin/bash
# ---------------------------------------------------------------------------
# postdeploy hook — runs after `azd deploy` completes
# ---------------------------------------------------------------------------
# Registers all Foundry agents (sub-agents + workflow agent).
# ---------------------------------------------------------------------------

set -euo pipefail

echo "=== postdeploy: Registering Foundry agents ==="

# ── Write .env from azd env values so deploy_workflow.py can load it ─────────

ENV_FILE=".env"

cat > "$ENV_FILE" << ENVEOF
FOUNDRY_PROJECT_ENDPOINT=$(azd env get-value FOUNDRY_PROJECT_ENDPOINT)
FOUNDRY_MODEL_DEPLOYMENT=$(azd env get-value FOUNDRY_MODEL_DEPLOYMENT)
AZURE_SUBSCRIPTION_ID=$(azd env get-value AZURE_SUBSCRIPTION_ID)
FOUNDRY_PROJECT_RESOURCE_ID=$(azd env get-value FOUNDRY_PROJECT_RESOURCE_ID)
ADVISOR_KNOWLEDGE_BASE_NAME=$(azd env get-value ADVISOR_KNOWLEDGE_BASE_NAME)
ADVISOR_SEARCH_ENDPOINT=$(azd env get-value ADVISOR_SEARCH_ENDPOINT)
ADVISOR_MCP_CONNECTION=$(azd env get-value ADVISOR_MCP_CONNECTION)
MCP_TOOLS_ENDPOINT=$(azd env get-value MCP_TOOLS_ENDPOINT)
MCP_TOOLS_CONNECTION=$(azd env get-value MCP_TOOLS_CONNECTION)
ENVEOF

# Add optional calendar vars if set
CALENDAR_ENDPOINT=$(azd env get-value SCHEDULER_CALENDAR_ENDPOINT 2>/dev/null || echo "")
CALENDAR_CONNECTION=$(azd env get-value SCHEDULER_CALENDAR_CONNECTION 2>/dev/null || echo "")

if [ -n "$CALENDAR_ENDPOINT" ]; then
    echo "SCHEDULER_CALENDAR_ENDPOINT=$CALENDAR_ENDPOINT" >> "$ENV_FILE"
    echo "SCHEDULER_CALENDAR_CONNECTION=$CALENDAR_CONNECTION" >> "$ENV_FILE"
fi

echo "  .env written from azd environment"

# ── Register agents via deploy_workflow.py ───────────────────────────────────

echo "  Registering workflow agent and sub-agents..."
python deploy_workflow.py

echo ""
echo "=== postdeploy complete ==="
echo "  Agents registered in Foundry. Test in portal playground or run:"
echo "    uvicorn api.server:app --reload --port 8000"
echo "    cd ui && npm run dev"
