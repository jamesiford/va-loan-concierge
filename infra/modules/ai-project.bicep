// ---------------------------------------------------------------------------
// AI Project (child of AI Services account)
// ---------------------------------------------------------------------------
// Resource type: Microsoft.CognitiveServices/accounts/projects
// ---------------------------------------------------------------------------

param environmentName string
param location string
param aiServicesName string

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: aiServicesName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: aiServices
  name: 'proj-${environmentName}'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    description: 'VA Loan Concierge'
  }
}

output projectId string = project.id
output projectName string = project.name
output projectPrincipalId string = project.identity.principalId
output projectEndpoint string = 'https://${aiServices.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
