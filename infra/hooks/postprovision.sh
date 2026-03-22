#!/bin/bash
# ---------------------------------------------------------------------------
# postprovision hook — runs after `azd provision` completes
# ---------------------------------------------------------------------------
# Creates resources that cannot be provisioned via Bicep:
#   1. Upload knowledge docs to blob storage
#   2. Create AI Search data source, index, and indexer (pulls from blob)
#   3. Create RemoteTool project connections (KB MCP + custom MCP)
# ---------------------------------------------------------------------------

set -euo pipefail

echo "=== postprovision: Setting up knowledge base and Foundry connections ==="

# ── Load outputs from azd env ────────────────────────────────────────────────

PROJECT_RESOURCE_ID=$(azd env get-value FOUNDRY_PROJECT_RESOURCE_ID 2>/dev/null || echo "")
SEARCH_ENDPOINT=$(azd env get-value ADVISOR_SEARCH_ENDPOINT 2>/dev/null || echo "")
SEARCH_SERVICE_NAME=$(azd env get-value SEARCH_SERVICE_NAME 2>/dev/null || echo "")
MCP_TOOLS_ENDPOINT=$(azd env get-value MCP_TOOLS_ENDPOINT 2>/dev/null || echo "")
STORAGE_ACCOUNT_NAME=$(azd env get-value STORAGE_ACCOUNT_NAME 2>/dev/null || echo "")
AI_SERVICES_NAME=$(azd env get-value AI_SERVICES_NAME 2>/dev/null || echo "")
EMBEDDING_MODEL=$(azd env get-value EMBEDDING_MODEL_DEPLOYMENT 2>/dev/null || echo "text-embedding-3-small")
AZURE_RESOURCE_GROUP=$(azd env get-value AZURE_RESOURCE_GROUP 2>/dev/null || echo "")
KNOWLEDGE_CONTAINER=$(azd env get-value KNOWLEDGE_CONTAINER_NAME 2>/dev/null || echo "knowledge-base")

if [ -z "$PROJECT_RESOURCE_ID" ]; then
    echo "ERROR: FOUNDRY_PROJECT_RESOURCE_ID not set. Did azd provision complete?"
    exit 1
fi

# ── Get access token ─────────────────────────────────────────────────────────

TOKEN=$(az account get-access-token --query accessToken -o tsv)
STORAGE_TOKEN=$(az account get-access-token --resource https://storage.azure.com/ --query accessToken -o tsv)

# ── 1. Upload knowledge documents to blob storage ────────────────────────────

STORAGE_URL="https://${STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
echo "Uploading knowledge documents to ${STORAGE_URL}/${KNOWLEDGE_CONTAINER}/"

for doc in knowledge/va_guidelines.md knowledge/lender_products.md knowledge/loan_process_faq.md; do
    if [ ! -f "$doc" ]; then
        echo "  WARNING: $doc not found, skipping"
        continue
    fi
    BLOB_NAME=$(basename "$doc")
    curl -s -X PUT "${STORAGE_URL}/${KNOWLEDGE_CONTAINER}/${BLOB_NAME}" \
        -H "Authorization: Bearer $STORAGE_TOKEN" \
        -H "x-ms-blob-type: BlockBlob" \
        -H "Content-Type: text/markdown" \
        -H "x-ms-version: 2023-11-03" \
        --data-binary "@${doc}" \
        -o /dev/null -w "  ${BLOB_NAME}: HTTP %{http_code}\n"
done

# ── 2. Create AI Search data source (points at blob container) ───────────────

KB_NAME="kb-va-loan-guidelines"
DATASOURCE_NAME="${KB_NAME}-datasource"
echo "Creating search data source: $DATASOURCE_NAME"

RESOURCE_ID="/subscriptions/$(azd env get-value AZURE_SUBSCRIPTION_ID)/resourceGroups/$(azd env get-value AZURE_RESOURCE_GROUP)/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}"

cat > /tmp/datasource.json << DSEOF
{
  "name": "${DATASOURCE_NAME}",
  "type": "azureblob",
  "credentials": {
    "connectionString": "ResourceId=${RESOURCE_ID};"
  },
  "container": {
    "name": "${KNOWLEDGE_CONTAINER}"
  }
}
DSEOF

curl -s -X PUT "${SEARCH_ENDPOINT}/datasources/${DATASOURCE_NAME}?api-version=2024-07-01" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/datasource.json \
    -o /dev/null -w "  Data source: HTTP %{http_code}\n"

# ── 3. Create AI Search index (with vector field for hybrid search) ──────────

echo "Creating search index: $KB_NAME"

cat > /tmp/kb-index.json << INDEXEOF
{
  "name": "${KB_NAME}",
  "fields": [
    {"name": "id", "type": "Edm.String", "key": true, "filterable": true},
    {"name": "content", "type": "Edm.String", "searchable": true, "analyzer": "standard.lucene"},
    {"name": "content_vector", "type": "Collection(Edm.Single)", "searchable": true, "dimensions": 1536, "vectorSearchProfile": "default-profile"},
    {"name": "metadata_storage_name", "type": "Edm.String", "filterable": true, "facetable": true},
    {"name": "metadata_storage_path", "type": "Edm.String", "filterable": true}
  ],
  "vectorSearch": {
    "algorithms": [
      {
        "name": "default-algorithm",
        "kind": "hnsw",
        "hnswParameters": {
          "metric": "cosine",
          "m": 4,
          "efConstruction": 400,
          "efSearch": 500
        }
      }
    ],
    "profiles": [
      {
        "name": "default-profile",
        "algorithm": "default-algorithm"
      }
    ]
  },
  "semantic": {
    "defaultConfiguration": "default",
    "configurations": [
      {
        "name": "default",
        "prioritizedFields": {
          "contentFields": [{"fieldName": "content"}],
          "titleField": {"fieldName": "metadata_storage_name"}
        }
      }
    ]
  }
}
INDEXEOF

curl -s -X PUT "${SEARCH_ENDPOINT}/indexes/${KB_NAME}?api-version=2024-07-01" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/kb-index.json \
    -o /dev/null -w "  Index: HTTP %{http_code}\n"

# ── 4. Create AI Search skillset (embedding generation) ─────────────────────

SKILLSET_NAME="${KB_NAME}-skillset"
echo "Creating search skillset: $SKILLSET_NAME (embedding model: $EMBEDDING_MODEL)"

# Build the AI Services resource ID for the skillset
SUBSCRIPTION_ID=$(azd env get-value AZURE_SUBSCRIPTION_ID)

cat > /tmp/skillset.json << SKILLEOF
{
  "name": "${SKILLSET_NAME}",
  "skills": [
    {
      "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
      "name": "content-embedding",
      "description": "Generate embeddings for knowledge base content",
      "context": "/document",
      "modelName": "${EMBEDDING_MODEL}",
      "resourceUri": "https://${AI_SERVICES_NAME}.openai.azure.com",
      "deploymentId": "${EMBEDDING_MODEL}",
      "inputs": [
        {"name": "text", "source": "/document/content"}
      ],
      "outputs": [
        {"name": "embedding", "targetName": "content_vector"}
      ]
    }
  ],
  "cognitiveServices": {
    "@odata.type": "#Microsoft.Azure.Search.CognitiveServicesByIdentity",
    "resourceId": "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${AI_SERVICES_NAME}"
  }
}
SKILLEOF

curl -s -X PUT "${SEARCH_ENDPOINT}/skillsets/${SKILLSET_NAME}?api-version=2024-07-01" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/skillset.json \
    -o /dev/null -w "  Skillset: HTTP %{http_code}\n"

# ── 5. Create AI Search indexer (blob → skillset → index) ───────────────────

INDEXER_NAME="${KB_NAME}-indexer"
echo "Creating search indexer: $INDEXER_NAME"

cat > /tmp/indexer.json << IXEOF
{
  "name": "${INDEXER_NAME}",
  "dataSourceName": "${DATASOURCE_NAME}",
  "skillsetName": "${SKILLSET_NAME}",
  "targetIndexName": "${KB_NAME}",
  "parameters": {
    "configuration": {
      "parsingMode": "text",
      "dataToExtract": "contentAndMetadata"
    }
  },
  "fieldMappings": [
    {"sourceFieldName": "metadata_storage_path", "targetFieldName": "id", "mappingFunction": {"name": "base64Encode"}},
    {"sourceFieldName": "metadata_storage_name", "targetFieldName": "metadata_storage_name"}
  ],
  "outputFieldMappings": [
    {"sourceFieldName": "/document/content_vector", "targetFieldName": "content_vector"}
  ]
}
IXEOF

curl -s -X PUT "${SEARCH_ENDPOINT}/indexers/${INDEXER_NAME}?api-version=2024-07-01" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/indexer.json \
    -o /dev/null -w "  Indexer: HTTP %{http_code}\n"

# Run the indexer immediately
echo "Running indexer..."
curl -s -X POST "${SEARCH_ENDPOINT}/indexers/${INDEXER_NAME}/run?api-version=2024-07-01" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Length: 0" \
    -o /dev/null -w "  Indexer run: HTTP %{http_code}\n"

# ── 6. Create RemoteTool connection for KB MCP ───────────────────────────────

ADVISOR_MCP_CONNECTION="kb-va-loan-demo-mcp"
KB_MCP_URL="${SEARCH_ENDPOINT}/knowledgebases/${KB_NAME}/mcp?api-version=2025-11-01-preview"
echo "Creating RemoteTool connection: $ADVISOR_MCP_CONNECTION"

cat > /tmp/conn-kb.json << CONNEOF
{
  "properties": {
    "category": "RemoteTool",
    "authType": "ProjectManagedIdentity",
    "target": "${KB_MCP_URL}",
    "metadata": {
      "audience": "https://search.azure.com/"
    }
  }
}
CONNEOF

curl -s -X PUT "https://management.azure.com${PROJECT_RESOURCE_ID}/connections/${ADVISOR_MCP_CONNECTION}?api-version=2025-05-01-preview" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/conn-kb.json \
    -o /dev/null -w "  KB MCP connection: HTTP %{http_code}\n"

# ── 7. Create RemoteTool connection for custom MCP server ────────────────────

MCP_TOOLS_CONNECTION="va-loan-action-mcp-conn"
echo "Creating RemoteTool connection: $MCP_TOOLS_CONNECTION"

cat > /tmp/conn-mcp.json << CONNEOF
{
  "properties": {
    "category": "RemoteTool",
    "authType": "None",
    "target": "${MCP_TOOLS_ENDPOINT}"
  }
}
CONNEOF

curl -s -X PUT "https://management.azure.com${PROJECT_RESOURCE_ID}/connections/${MCP_TOOLS_CONNECTION}?api-version=2025-05-01-preview" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @/tmp/conn-mcp.json \
    -o /dev/null -w "  MCP tools connection: HTTP %{http_code}\n"

# ── 8. Save connection names to azd env for use by app ───────────────────────

azd env set ADVISOR_KNOWLEDGE_BASE_NAME "$KB_NAME"
azd env set ADVISOR_MCP_CONNECTION "$ADVISOR_MCP_CONNECTION"
azd env set MCP_TOOLS_CONNECTION "$MCP_TOOLS_CONNECTION"

echo ""
echo "=== postprovision complete ==="
echo ""
echo "MANUAL STEP REQUIRED:"
echo "  Configure Work IQ Calendar connection in the Foundry portal:"
echo "    1. Go to the Foundry project → Connections"
echo "    2. Add a Work IQ Calendar connection"
echo "    3. Set the following env vars:"
echo "       azd env set SCHEDULER_CALENDAR_ENDPOINT <endpoint-url>"
echo "       azd env set SCHEDULER_CALENDAR_CONNECTION <connection-name>"
echo ""
