// ---------------------------------------------------------------------------
// Cosmos DB — Serverless NoSQL (conversation state persistence)
// ---------------------------------------------------------------------------
// Stores HIL conversation state so multi-turn conversations survive server
// restarts. Serverless: pay-per-RU (~$0/month for demo), no capacity planning.
//
// Container design:
//   Partition key: /conversation_id (point reads = 1 RU)
//   TTL: 600 seconds (10 min) — auto-deleted by Cosmos background task
//   Indexing: minimal — only conversation_id + pending_action
//
// Auth: disableLocalAuth=true (RBAC only, no connection strings).
// Data-plane RBAC uses Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments
// (NOT Microsoft.Authorization/roleAssignments).
// ---------------------------------------------------------------------------

param environmentName string
param location string

var cleanName = replace(environmentName, '-', '')
var accountName = take('cosmos${cleanName}', 44)

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      { name: 'EnableServerless' }
    ]
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmosAccount
  name: 'va-loan-concierge'
  properties: {
    resource: {
      id: 'va-loan-concierge'
    }
  }
}

resource container 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'conversation-state'
  properties: {
    resource: {
      id: 'conversation-state'
      partitionKey: {
        paths: [ '/conversation_id' ]
        kind: 'Hash'
        version: 2
      }
      defaultTtl: 600
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/conversation_id/?' }
          { path: '/pending_action/?' }
        ]
        excludedPaths: [
          { path: '/*' }
        ]
      }
    }
  }
}

output cosmosAccountId string = cosmosAccount.id
output cosmosAccountName string = cosmosAccount.name
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
