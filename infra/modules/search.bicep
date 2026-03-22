// ---------------------------------------------------------------------------
// Azure AI Search
// ---------------------------------------------------------------------------
// Auth mode set to aadOrApiKey (required for Foundry IQ KB managed identity).
// ---------------------------------------------------------------------------

param environmentName string
param location string

@allowed(['basic', 'standard', 'standard2'])
param sku string = 'basic'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: 'srch-${environmentName}'
  location: location
  sku: {
    name: sku
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hostingMode: 'default'
    partitionCount: 1
    replicaCount: 1
    publicNetworkAccess: 'enabled'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

output searchId string = search.id
output searchName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchPrincipalId string = search.identity.principalId
