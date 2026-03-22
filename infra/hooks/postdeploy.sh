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

# Add web app outputs if available
WEB_APP_HOSTNAME=$(azd env get-value WEB_APP_HOSTNAME 2>/dev/null || echo "")
WEB_APP_NAME=$(azd env get-value WEB_APP_NAME 2>/dev/null || echo "")

if [ -n "$WEB_APP_HOSTNAME" ]; then
    echo "WEB_APP_HOSTNAME=$WEB_APP_HOSTNAME" >> "$ENV_FILE"
    echo "WEB_APP_NAME=$WEB_APP_NAME" >> "$ENV_FILE"
    echo "WEB_APP_ORIGIN=https://$WEB_APP_HOSTNAME" >> "$ENV_FILE"
fi

echo "  .env written from azd environment"

# ── Push hook-set App Settings to the Web App ──────────────────────────────
# Connection names are created by postprovision (not Bicep outputs), so they
# are empty in the Bicep-managed App Settings on first provision. Push them
# here so the Web App has all values it needs to run.

if [ -n "$WEB_APP_NAME" ]; then
    RG=$(azd env get-value AZURE_RESOURCE_GROUP 2>/dev/null || echo "")
    ADVISOR_KB_NAME=$(azd env get-value ADVISOR_KNOWLEDGE_BASE_NAME 2>/dev/null || echo "")
    ADVISOR_MCP_CONN=$(azd env get-value ADVISOR_MCP_CONNECTION 2>/dev/null || echo "")
    MCP_TOOLS_CONN=$(azd env get-value MCP_TOOLS_CONNECTION 2>/dev/null || echo "")

    if [ -n "$ADVISOR_KB_NAME" ] && [ -n "$RG" ]; then
        echo "  Pushing connection App Settings to $WEB_APP_NAME..."
        az webapp config appsettings set \
            --name "$WEB_APP_NAME" \
            --resource-group "$RG" \
            --settings \
                ADVISOR_KNOWLEDGE_BASE_NAME="$ADVISOR_KB_NAME" \
                ADVISOR_MCP_CONNECTION="$ADVISOR_MCP_CONN" \
                MCP_TOOLS_CONNECTION="$MCP_TOOLS_CONN" \
            --output none 2>/dev/null || echo "  Warning: could not update Web App settings (app may not exist yet)"

        # Push optional calendar settings if available
        if [ -n "$CALENDAR_ENDPOINT" ]; then
            az webapp config appsettings set \
                --name "$WEB_APP_NAME" \
                --resource-group "$RG" \
                --settings \
                    SCHEDULER_CALENDAR_ENDPOINT="$CALENDAR_ENDPOINT" \
                    SCHEDULER_CALENDAR_CONNECTION="$CALENDAR_CONNECTION" \
                --output none 2>/dev/null || true
        fi
    fi
fi

# ── Register agents via deploy_workflow.py ───────────────────────────────────

echo "  Registering workflow agent and sub-agents..."
python deploy_workflow.py

echo ""
echo "=== postdeploy complete ==="
echo "  Agents registered in Foundry. Test in portal playground or run:"
echo "    uvicorn api.server:app --reload --port 8000"
echo "    cd ui && npm run dev"
