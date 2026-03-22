// ---------------------------------------------------------------------------
// AI Services Account (next-gen Foundry resource)
// ---------------------------------------------------------------------------
// Replaces the v1 Hub + separate Azure OpenAI resource.
// This single resource provides: OpenAI models, agent hosting, connections,
// and project management.
//
// Resource type: Microsoft.CognitiveServices/accounts (kind: AIServices)
// ---------------------------------------------------------------------------

param environmentName string
param location string
param modelName string = 'gpt-4o'
param modelVersion string = '2024-11-20'
param modelCapacity int = 30
param searchId string
param searchEndpoint string

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'ais-${environmentName}'
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: 'ais-${environmentName}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    allowProjectManagement: true
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

// ── Model deployment ────────────────────────────────────────────────────────

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: modelName
  sku: {
    name: 'Standard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// ── AI Search connection (account-level, shared to all projects) ────────────

resource searchConnection 'Microsoft.CognitiveServices/accounts/connections@2025-04-01-preview' = {
  parent: aiServices
  name: 'search-connection'
  properties: {
    category: 'CognitiveSearch'
    authType: 'AAD'
    isSharedToAll: true
    target: searchEndpoint
    metadata: {
      ResourceId: searchId
    }
  }
}

output aiServicesId string = aiServices.id
output aiServicesName string = aiServices.name
output aiServicesPrincipalId string = aiServices.identity.principalId
output aiServicesEndpoint string = 'https://${aiServices.properties.customSubDomainName}.services.ai.azure.com/'
