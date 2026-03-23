// ---------------------------------------------------------------------------
// Shared App Service Plan — B1 Linux
// ---------------------------------------------------------------------------
// Used by both the Function App (MCP server) and the Web App (FastAPI + React).
// B1 is the minimum SKU that supports VNet integration (Phase 8).
// ---------------------------------------------------------------------------

param environmentName string
param location string

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-${environmentName}'
  location: location
  kind: 'linux'
  properties: {
    reserved: true // required for Linux
  }
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
}

output appServicePlanId string = appServicePlan.id
