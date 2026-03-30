// ---------------------------------------------------------------------------
// Storage Account
// ---------------------------------------------------------------------------
// Used by:
//   1. Function App — AzureWebJobsStorage runtime storage
//   2. Foundry IQ Knowledge Base — blob containers for knowledge source documents
//      loan-guidelines  — VA guidelines, lender products, loan process FAQ (static)
//      news-articles    — CU-ingested VA mortgage news markdown files (Phase 14)
//
// Storage names: max 24 chars, lowercase alphanumeric only, no hyphens.
// We strip hyphens from environmentName and prefix with "st".
// ---------------------------------------------------------------------------

param environmentName string
param location string

var cleanName = replace(environmentName, '-', '')
var storageAccountName = take('st${cleanName}', 24)

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

// Blob container for static VA loan knowledge documents (guidelines, products, FAQ)
resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource knowledgeContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: 'loan-guidelines'
  properties: {
    publicAccess: 'None'
  }
}

// Blob container for CU-ingested VA mortgage news markdown files (Phase 14)
// Foundry IQ polls this container and auto-vectorizes new blobs as a KB source.
resource newsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: 'news-articles'
  properties: {
    publicAccess: 'None'
  }
}

// Blob container for Flex Consumption Function App deployment packages
resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: 'deploymentpackage'
  properties: {
    publicAccess: 'None'
  }
}

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
output storageAccountEndpoint string = storageAccount.properties.primaryEndpoints.blob
output knowledgeContainerName string = knowledgeContainer.name
output newsContainerName string = newsContainer.name
