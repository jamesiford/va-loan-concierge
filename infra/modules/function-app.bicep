// ---------------------------------------------------------------------------
// Function App — MCP server (custom tools: calculator + scheduler)
// ---------------------------------------------------------------------------
// Flex Consumption plan (FC1) — serverless, pay-per-execution, separate quota
// from classic App Service tiers (B1/S1/P1v3). Supports VNet integration.
//
// Endpoint will be at /mcp (routePrefix: "" in host.json).
// ---------------------------------------------------------------------------

param environmentName string
param location string
param appInsightsConnectionString string
param storageAccountName string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource flexPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'asp-func-${environmentName}'
  location: location
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: 'func-${environmentName}'
  location: location
  kind: 'functionapp,linux'
  tags: {
    'azd-service-name': 'mcp-server'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: flexPlan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccount.properties.primaryEndpoints.blob}deploymentpackage'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccountName
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
      ]
    }
  }
}

output functionAppId string = functionApp.id
output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}/mcp'
output functionAppPrincipalId string = functionApp.identity.principalId
