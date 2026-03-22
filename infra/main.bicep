// ---------------------------------------------------------------------------
// VA Loan Concierge — Main Bicep orchestrator
// ---------------------------------------------------------------------------
// Provisions all Azure resources for the demo. Called by `azd provision`.
// Naming convention: {abbreviation}{environmentName}  (e.g. ais-valc-demo-abc)
//
// Next-gen Foundry resource model:
//   Microsoft.CognitiveServices/accounts (kind: AIServices)
//     └── /projects/{name}
//     └── /deployments/{model}
//
// No separate Hub, Azure OpenAI, Storage, or Key Vault resources needed
// for the Foundry layer. Storage is only used by the Function App.
// ---------------------------------------------------------------------------

targetScope = 'subscription'

// ── Parameters (prompted by azd) ────────────────────────────────────────────

@minLength(1)
@maxLength(64)
@description('Name of the azd environment (e.g. valc-demo-abc123)')
param environmentName string

@allowed([
  'eastus'
  'eastus2'
  'westus3'
  'swedencentral'
  'northcentralus'
])
@description('Azure region — must support Foundry, AI Search, OpenAI, and Functions')
param location string

@description('GPT model to deploy (e.g. gpt-4o)')
param modelName string = 'gpt-4o'

@description('GPT model version')
param modelVersion string = '2024-11-20'

@description('GPT deployment SKU capacity (in thousands of tokens per minute)')
param modelCapacity int = 30

@description('AI Search SKU')
@allowed(['basic', 'standard', 'standard2'])
param searchSku string = 'basic'

@description('Principal ID of the current user (for RBAC). Populated by azd.')
param principalId string = ''

// ── Resource Group ──────────────────────────────────────────────────────────

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
}

// ── Level 0: Independent foundational resources ─────────────────────────────

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
  }
}

module search 'modules/search.bicep' = {
  name: 'search'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    sku: searchSku
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
  }
}

// ── Level 1: AI Services account (Foundry + OpenAI + connections) ───────────

module aiServices 'modules/ai-services.bicep' = {
  name: 'aiServices'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    searchId: search.outputs.searchId
    searchEndpoint: search.outputs.searchEndpoint
  }
}

// ── Level 2: AI Project (child of AI Services) ──────────────────────────────

module aiProject 'modules/ai-project.bicep' = {
  name: 'aiProject'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    aiServicesName: aiServices.outputs.aiServicesName
  }
}

// ── Level 2: Function App for MCP server ────────────────────────────────────

module functionApp 'modules/function-app.bicep' = {
  name: 'functionApp'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    storageAccountName: storage.outputs.storageAccountName
  }
}

// ── Level 3: RBAC assignments ───────────────────────────────────────────────

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  scope: rg
  params: {
    aiServicesPrincipalId: aiServices.outputs.aiServicesPrincipalId
    projectPrincipalId: aiProject.outputs.projectPrincipalId
    searchPrincipalId: search.outputs.searchPrincipalId
    aiServicesId: aiServices.outputs.aiServicesId
    searchId: search.outputs.searchId
    storageAccountId: storage.outputs.storageAccountId
    projectId: aiProject.outputs.projectId
    userPrincipalId: principalId
  }
}

// ── Outputs (consumed by azd env + hooks) ───────────────────────────────────

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location

// Foundry
output FOUNDRY_PROJECT_ENDPOINT string = aiProject.outputs.projectEndpoint
output FOUNDRY_MODEL_DEPLOYMENT string = modelName
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId
output FOUNDRY_PROJECT_RESOURCE_ID string = aiProject.outputs.projectId

// AI Search / Knowledge Base
output ADVISOR_SEARCH_ENDPOINT string = search.outputs.searchEndpoint
output SEARCH_SERVICE_NAME string = search.outputs.searchName

// MCP Function App
output MCP_TOOLS_ENDPOINT string = functionApp.outputs.functionAppUrl
output FUNCTION_APP_NAME string = functionApp.outputs.functionAppName

// Principal IDs (for hooks)
output PROJECT_PRINCIPAL_ID string = aiProject.outputs.projectPrincipalId
output AI_SERVICES_NAME string = aiServices.outputs.aiServicesName
output STORAGE_ACCOUNT_NAME string = storage.outputs.storageAccountName
output KNOWLEDGE_CONTAINER_NAME string = storage.outputs.knowledgeContainerName
