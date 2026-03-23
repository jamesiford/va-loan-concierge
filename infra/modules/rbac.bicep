// ---------------------------------------------------------------------------
// RBAC role assignments (15 total)
// ---------------------------------------------------------------------------
// All role assignments needed for the multi-agent demo to function.
//
// Principals:
//   1. AI Services managed identity — model access, agent execution
//   2. Project managed identity     — agent execution, KB queries
//   3. Search managed identity      — KB indexing (calls OpenAI embeddings)
//   4. Current user                 — local dev, azd hooks, agent registration
//   5. Function App managed identity — MI-based storage access (no shared keys)
// ---------------------------------------------------------------------------

param aiServicesPrincipalId string
param projectPrincipalId string
param searchPrincipalId string
param aiServicesId string
param searchId string
param storageAccountId string
param projectId string
param userPrincipalId string = ''
param functionAppPrincipalId string = ''

// ── Well-known role definition IDs ──────────────────────────────────────────

var roles = {
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

// ═══════════════════════════════════════════════════════════════════════════
// AI SERVICES MANAGED IDENTITY
// ═══════════════════════════════════════════════════════════════════════════

// AI Services → AI Search (KB queries via MCP — read)
resource aiServicesSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchId, aiServicesPrincipalId, roles.searchIndexDataReader)
  scope: resourceGroup()
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader)
    principalType: 'ServicePrincipal'
  }
}

// AI Services → AI Search (KB indexing / embedding updates — write)
resource aiServicesSearchContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchId, aiServicesPrincipalId, roles.searchIndexDataContributor)
  scope: resourceGroup()
  properties: {
    principalId: aiServicesPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
    principalType: 'ServicePrincipal'
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// PROJECT MANAGED IDENTITY
// ═══════════════════════════════════════════════════════════════════════════

// Project → AI Search (KB queries via MCP — read)
resource projectSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchId, projectPrincipalId, roles.searchIndexDataReader)
  scope: resourceGroup()
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader)
    principalType: 'ServicePrincipal'
  }
}

// Project → AI Search (KB indexing — write)
resource projectSearchContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchId, projectPrincipalId, roles.searchIndexDataContributor)
  scope: resourceGroup()
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
    principalType: 'ServicePrincipal'
  }
}

// Project → AI Services (Responses API calls for all agents)
resource projectOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServicesId, projectPrincipalId, roles.cognitiveServicesOpenAIUser)
  scope: resourceGroup()
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalType: 'ServicePrincipal'
  }
}

// Project → AI Services (Cognitive Services User — agent management)
resource projectCognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServicesId, projectPrincipalId, roles.cognitiveServicesUser)
  scope: resourceGroup()
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
    principalType: 'ServicePrincipal'
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// SEARCH MANAGED IDENTITY
// ═══════════════════════════════════════════════════════════════════════════

// Search → AI Services (generate embeddings during KB indexing)
resource searchOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServicesId, searchPrincipalId, roles.cognitiveServicesOpenAIUser)
  scope: resourceGroup()
  properties: {
    principalId: searchPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalType: 'ServicePrincipal'
  }
}

// Search → Storage (indexer reads knowledge docs from blob container)
resource searchStorageReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccountId, searchPrincipalId, roles.storageBlobDataReader)
  scope: resourceGroup()
  properties: {
    principalId: searchPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataReader)
    principalType: 'ServicePrincipal'
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// CURRENT USER (local dev + azd hooks)
// ═══════════════════════════════════════════════════════════════════════════

// User → AI Services (DefaultAzureCredential for local uvicorn + agent init)
resource userOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(aiServicesId, userPrincipalId, roles.cognitiveServicesOpenAIUser)
  scope: resourceGroup()
  properties: {
    principalId: userPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalType: 'User'
  }
}

// User → AI Services (Cognitive Services User — agent management via data plane)
resource userCognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(aiServicesId, userPrincipalId, roles.cognitiveServicesUser)
  scope: resourceGroup()
  properties: {
    principalId: userPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
    principalType: 'User'
  }
}

// User → AI Search (postprovision.sh creates KB index + uploads documents)
resource userSearchContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(searchId, userPrincipalId, roles.searchIndexDataContributor)
  scope: resourceGroup()
  properties: {
    principalId: userPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
    principalType: 'User'
  }
}

// User → Storage (postprovision.sh uploads knowledge docs to blob container)
resource userStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(storageAccountId, userPrincipalId, roles.storageBlobDataContributor)
  scope: resourceGroup()
  properties: {
    principalId: userPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
    principalType: 'User'
  }
}

// User → Resource Group Contributor (ARM PUT for RemoteTool connections)
resource userProjectContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  name: guid(projectId, userPrincipalId, roles.contributor)
  scope: resourceGroup()
  properties: {
    principalId: userPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
    principalType: 'User'
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// FUNCTION APP MANAGED IDENTITY
// ═══════════════════════════════════════════════════════════════════════════
// MI-based storage access (subscription policy blocks shared key access).

// Function App → Storage (blob — deployment packages + runtime state)
resource funcAppStorageOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(functionAppPrincipalId)) {
  name: guid(storageAccountId, functionAppPrincipalId, roles.storageBlobDataOwner)
  scope: resourceGroup()
  properties: {
    principalId: functionAppPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataOwner)
    principalType: 'ServicePrincipal'
  }
}

// Function App → Storage (queues — Functions runtime uses queues internally)
resource funcAppStorageQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(functionAppPrincipalId)) {
  name: guid(storageAccountId, functionAppPrincipalId, roles.storageQueueDataContributor)
  scope: resourceGroup()
  properties: {
    principalId: functionAppPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageQueueDataContributor)
    principalType: 'ServicePrincipal'
  }
}

