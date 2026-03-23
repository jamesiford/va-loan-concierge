// ---------------------------------------------------------------------------
// Web App — FastAPI backend + React static frontend
// ---------------------------------------------------------------------------
// App Service (Linux, Python 3.12) on a B1 plan. B1 is the minimum SKU that
// supports VNet integration (required for Phase 8 network isolation).
//
// The React UI is built during predeploy and served as static files from the
// same App Service via FastAPI's StaticFiles mount.
// ---------------------------------------------------------------------------

param environmentName string
param location string
param appInsightsConnectionString string

// ── Foundry / agent env vars (passed through as App Settings) ─────────────
param foundryProjectEndpoint string
param foundryModelDeployment string
param azureSubscriptionId string
param foundryProjectResourceId string

// ── KB / MCP connection names (set by postprovision hook, stored in azd env) ─
param advisorKnowledgeBaseName string = ''
param advisorSearchEndpoint string = ''
param advisorMcpConnection string = ''
param mcpToolsEndpoint string = ''
param mcpToolsConnection string = ''

// ── Optional: Work IQ Calendar ────────────────────────────────────────────
param schedulerCalendarEndpoint string = ''
param schedulerCalendarConnection string = ''

// ── Shared App Service Plan (from app-service-plan module) ────────────────
param appServicePlanId string

// ── App Service ───────────────────────────────────────────────────────────

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: 'app-${environmentName}'
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlanId
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'uvicorn api.server:app --host 0.0.0.0 --port 8000'
      appSettings: [
        // ── Build ─────────────────────────────────────────────────────────
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        // ── Observability ─────────────────────────────────────────────────
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        {
          name: 'OTEL_SERVICE_NAME'
          value: 'va-loan-concierge'
        }
        // ── Foundry Project ───────────────────────────────────────────────
        {
          name: 'FOUNDRY_PROJECT_ENDPOINT'
          value: foundryProjectEndpoint
        }
        {
          name: 'FOUNDRY_MODEL_DEPLOYMENT'
          value: foundryModelDeployment
        }
        {
          name: 'AZURE_SUBSCRIPTION_ID'
          value: azureSubscriptionId
        }
        {
          name: 'FOUNDRY_PROJECT_RESOURCE_ID'
          value: foundryProjectResourceId
        }
        // ── KB / Advisor ──────────────────────────────────────────────────
        {
          name: 'ADVISOR_KNOWLEDGE_BASE_NAME'
          value: advisorKnowledgeBaseName
        }
        {
          name: 'ADVISOR_SEARCH_ENDPOINT'
          value: advisorSearchEndpoint
        }
        {
          name: 'ADVISOR_MCP_CONNECTION'
          value: advisorMcpConnection
        }
        // ── MCP Tools ─────────────────────────────────────────────────────
        {
          name: 'MCP_TOOLS_ENDPOINT'
          value: mcpToolsEndpoint
        }
        {
          name: 'MCP_TOOLS_CONNECTION'
          value: mcpToolsConnection
        }
        // ── Calendar (optional) ───────────────────────────────────────────
        {
          name: 'SCHEDULER_CALENDAR_ENDPOINT'
          value: schedulerCalendarEndpoint
        }
        {
          name: 'SCHEDULER_CALENDAR_CONNECTION'
          value: schedulerCalendarConnection
        }
        // ── CORS (same-origin in prod, but allow local dev) ───────────────
        {
          name: 'WEB_APP_ORIGIN'
          value: 'https://app-${environmentName}.azurewebsites.net'
        }
      ]
    }
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────

output webAppId string = webApp.id
output webAppName string = webApp.name
output webAppPrincipalId string = webApp.identity.principalId
output webAppHostname string = webApp.properties.defaultHostName
output appServicePlanId string = appServicePlanId
