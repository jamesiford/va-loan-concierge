# ---------------------------------------------------------------------------
# postprovision hook — runs after `azd provision` completes
# ---------------------------------------------------------------------------
# Creates resources that cannot be provisioned via Bicep:
#   1. Upload knowledge docs to blob storage
#   2. Create AI Search data source, index, and indexer (pulls from blob)
#   3. Create RemoteTool project connections (KB MCP + custom MCP)
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

Write-Host "=== postprovision: Setting up knowledge base and Foundry connections ==="

# -- Load outputs from azd env --

$PROJECT_RESOURCE_ID = (azd env get-value FOUNDRY_PROJECT_RESOURCE_ID 2>$null)
$SEARCH_ENDPOINT = (azd env get-value ADVISOR_SEARCH_ENDPOINT 2>$null)
$SEARCH_SERVICE_NAME = (azd env get-value SEARCH_SERVICE_NAME 2>$null)
$MCP_TOOLS_ENDPOINT = (azd env get-value MCP_TOOLS_ENDPOINT 2>$null)
$STORAGE_ACCOUNT_NAME = (azd env get-value STORAGE_ACCOUNT_NAME 2>$null)
$AI_SERVICES_NAME = (azd env get-value AI_SERVICES_NAME 2>$null)
$EMBEDDING_MODEL = (azd env get-value EMBEDDING_MODEL_DEPLOYMENT 2>$null)
if (-not $EMBEDDING_MODEL) { $EMBEDDING_MODEL = "text-embedding-3-small" }
$AZURE_RESOURCE_GROUP = (azd env get-value AZURE_RESOURCE_GROUP 2>$null)
$KNOWLEDGE_CONTAINER = (azd env get-value KNOWLEDGE_CONTAINER_NAME 2>$null)
if (-not $KNOWLEDGE_CONTAINER) { $KNOWLEDGE_CONTAINER = "knowledge-base" }

if (-not $PROJECT_RESOURCE_ID) {
    Write-Error "FOUNDRY_PROJECT_RESOURCE_ID not set. Did azd provision complete?"
    exit 1
}

# -- Get access tokens --

$TOKEN = (az account get-access-token --query accessToken -o tsv)
$SEARCH_TOKEN = (az account get-access-token --resource https://search.azure.com --query accessToken -o tsv)
$STORAGE_TOKEN = (az account get-access-token --resource https://storage.azure.com/ --query accessToken -o tsv)

# -- 1. Upload knowledge documents to blob storage --

$STORAGE_URL = "https://${STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
Write-Host "Uploading knowledge documents to ${STORAGE_URL}/${KNOWLEDGE_CONTAINER}/"

$docs = @("knowledge/va_guidelines.md", "knowledge/lender_products.md", "knowledge/loan_process_faq.md")
foreach ($doc in $docs) {
    if (-not (Test-Path $doc)) {
        Write-Host "  WARNING: $doc not found, skipping"
        continue
    }
    $BLOB_NAME = Split-Path $doc -Leaf
    $headers = @{
        "Authorization"    = "Bearer $STORAGE_TOKEN"
        "x-ms-blob-type"   = "BlockBlob"
        "Content-Type"     = "text/markdown"
        "x-ms-version"     = "2023-11-03"
    }
    $body = [System.IO.File]::ReadAllBytes((Resolve-Path $doc))
    try {
        $resp = Invoke-WebRequest -Uri "${STORAGE_URL}/${KNOWLEDGE_CONTAINER}/${BLOB_NAME}" `
            -Method PUT -Headers $headers -Body $body -UseBasicParsing
        Write-Host "  ${BLOB_NAME}: HTTP $($resp.StatusCode)"
    } catch {
        Write-Host "  ${BLOB_NAME}: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
    }
}

# -- 2. Create AI Search data source (points at blob container) --

$KB_NAME = "kb-va-loan-guidelines"
$DATASOURCE_NAME = "${KB_NAME}-datasource"
Write-Host "Creating search data source: $DATASOURCE_NAME"

$SUBSCRIPTION_ID = (azd env get-value AZURE_SUBSCRIPTION_ID)
$RESOURCE_ID = "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${STORAGE_ACCOUNT_NAME}"

$datasourceBody = @{
    name = $DATASOURCE_NAME
    type = "azureblob"
    credentials = @{
        connectionString = "ResourceId=${RESOURCE_ID};"
    }
    container = @{
        name = $KNOWLEDGE_CONTAINER
    }
} | ConvertTo-Json -Depth 5

$searchHeaders = @{
    "Authorization" = "Bearer $SEARCH_TOKEN"
    "Content-Type"  = "application/json"
}

try {
    $resp = Invoke-WebRequest -Uri "${SEARCH_ENDPOINT}/datasources/${DATASOURCE_NAME}?api-version=2024-11-01-preview" `
        -Method PUT -Headers $searchHeaders -Body $datasourceBody -UseBasicParsing
    Write-Host "  Data source: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  Data source: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- 3. Create AI Search index (with vector field for hybrid search) --

Write-Host "Creating search index: $KB_NAME"

$indexBody = @{
    name = $KB_NAME
    fields = @(
        @{ name = "id"; type = "Edm.String"; key = $true; filterable = $true }
        @{ name = "content"; type = "Edm.String"; searchable = $true; analyzer = "standard.lucene" }
        @{ name = "content_vector"; type = "Collection(Edm.Single)"; searchable = $true; dimensions = 1536; vectorSearchProfile = "default-profile" }
        @{ name = "metadata_storage_name"; type = "Edm.String"; filterable = $true; facetable = $true }
        @{ name = "metadata_storage_path"; type = "Edm.String"; filterable = $true }
    )
    vectorSearch = @{
        algorithms = @(
            @{
                name = "default-algorithm"
                kind = "hnsw"
                hnswParameters = @{
                    metric = "cosine"
                    m = 4
                    efConstruction = 400
                    efSearch = 500
                }
            }
        )
        profiles = @(
            @{
                name = "default-profile"
                algorithm = "default-algorithm"
            }
        )
    }
    semantic = @{
        defaultConfiguration = "default"
        configurations = @(
            @{
                name = "default"
                prioritizedFields = @{
                    prioritizedContentFields = @(@{ fieldName = "content" })
                    titleField = @{ fieldName = "metadata_storage_name" }
                }
            }
        )
    }
} | ConvertTo-Json -Depth 10

try {
    $resp = Invoke-WebRequest -Uri "${SEARCH_ENDPOINT}/indexes/${KB_NAME}?api-version=2024-11-01-preview" `
        -Method PUT -Headers $searchHeaders -Body $indexBody -UseBasicParsing
    Write-Host "  Index: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  Index: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- 4. Create AI Search skillset (embedding generation) --

$SKILLSET_NAME = "${KB_NAME}-skillset"
Write-Host "Creating search skillset: $SKILLSET_NAME (embedding model: $EMBEDDING_MODEL)"

$skillsetBody = @{
    name = $SKILLSET_NAME
    skills = @(
        @{
            "@odata.type" = "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill"
            name = "content-embedding"
            description = "Generate embeddings for knowledge base content"
            context = "/document"
            modelName = $EMBEDDING_MODEL
            resourceUri = "https://${AI_SERVICES_NAME}.openai.azure.com"
            deploymentId = $EMBEDDING_MODEL
            inputs = @(
                @{ name = "text"; source = "/document/content" }
            )
            outputs = @(
                @{ name = "embedding"; targetName = "content_vector" }
            )
        }
    )
} | ConvertTo-Json -Depth 10

try {
    $resp = Invoke-WebRequest -Uri "${SEARCH_ENDPOINT}/skillsets/${SKILLSET_NAME}?api-version=2024-11-01-preview" `
        -Method PUT -Headers $searchHeaders -Body $skillsetBody -UseBasicParsing
    Write-Host "  Skillset: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  Skillset: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- 5. Create AI Search indexer (blob -> skillset -> index) --

$INDEXER_NAME = "${KB_NAME}-indexer"
Write-Host "Creating search indexer: $INDEXER_NAME"

$indexerBody = @{
    name = $INDEXER_NAME
    dataSourceName = $DATASOURCE_NAME
    skillsetName = $SKILLSET_NAME
    targetIndexName = $KB_NAME
    parameters = @{
        configuration = @{
            parsingMode = "text"
            dataToExtract = "contentAndMetadata"
        }
    }
    fieldMappings = @(
        @{ sourceFieldName = "metadata_storage_path"; targetFieldName = "id"; mappingFunction = @{ name = "base64Encode" } }
        @{ sourceFieldName = "metadata_storage_name"; targetFieldName = "metadata_storage_name" }
    )
    outputFieldMappings = @(
        @{ sourceFieldName = "/document/content_vector"; targetFieldName = "content_vector" }
    )
} | ConvertTo-Json -Depth 10

try {
    $resp = Invoke-WebRequest -Uri "${SEARCH_ENDPOINT}/indexers/${INDEXER_NAME}?api-version=2024-11-01-preview" `
        -Method PUT -Headers $searchHeaders -Body $indexerBody -UseBasicParsing
    Write-Host "  Indexer: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  Indexer: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# Run the indexer immediately
Write-Host "Running indexer..."
try {
    $resp = Invoke-WebRequest -Uri "${SEARCH_ENDPOINT}/indexers/${INDEXER_NAME}/run?api-version=2024-11-01-preview" `
        -Method POST -Headers $searchHeaders -Body "" -UseBasicParsing
    Write-Host "  Indexer run: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  Indexer run: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- 6. Create RemoteTool connection for KB MCP --

$ADVISOR_MCP_CONNECTION = "kb-va-loan-demo-mcp"
$KB_MCP_URL = "${SEARCH_ENDPOINT}/knowledgebases/${KB_NAME}/mcp?api-version=2025-11-01-preview"
Write-Host "Creating RemoteTool connection: $ADVISOR_MCP_CONNECTION"

$connKbBody = @{
    properties = @{
        category = "RemoteTool"
        authType = "ProjectManagedIdentity"
        target = $KB_MCP_URL
        metadata = @{
            audience = "https://search.azure.com/"
        }
    }
} | ConvertTo-Json -Depth 5

$armHeaders = @{
    "Authorization" = "Bearer $TOKEN"
    "Content-Type"  = "application/json"
}

try {
    $resp = Invoke-WebRequest -Uri "https://management.azure.com${PROJECT_RESOURCE_ID}/connections/${ADVISOR_MCP_CONNECTION}?api-version=2025-04-01-preview" `
        -Method PUT -Headers $armHeaders -Body $connKbBody -UseBasicParsing
    Write-Host "  KB MCP connection: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  KB MCP connection: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- 7. Create RemoteTool connection for custom MCP server --

$MCP_TOOLS_CONNECTION = "va-loan-action-mcp-conn"
Write-Host "Creating RemoteTool connection: $MCP_TOOLS_CONNECTION"

$connMcpBody = @{
    properties = @{
        category = "RemoteTool"
        authType = "None"
        target = $MCP_TOOLS_ENDPOINT
    }
} | ConvertTo-Json -Depth 5

try {
    $resp = Invoke-WebRequest -Uri "https://management.azure.com${PROJECT_RESOURCE_ID}/connections/${MCP_TOOLS_CONNECTION}?api-version=2025-04-01-preview" `
        -Method PUT -Headers $armHeaders -Body $connMcpBody -UseBasicParsing
    Write-Host "  MCP tools connection: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  MCP tools connection: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- 8. Create Foundry IQ Knowledge Base (wraps the search index) --

Write-Host ""
Write-Host "=== Creating Foundry IQ Knowledge Base ==="

# Ensure the SDK is installed
pip install --quiet azure-search-documents==11.7.0b2

# Write a temporary .env so create_kb.py can load it
$tempEnv = @"
ADVISOR_SEARCH_ENDPOINT=$SEARCH_ENDPOINT
AI_SERVICES_NAME=$AI_SERVICES_NAME
EMBEDDING_MODEL_DEPLOYMENT=$EMBEDDING_MODEL
"@
Set-Content -Path ".env.kb-temp" -Value $tempEnv
$env:DOTENV_PATH = ".env.kb-temp"

# Set env vars directly for the script
$env:ADVISOR_SEARCH_ENDPOINT = $SEARCH_ENDPOINT
$env:AI_SERVICES_NAME = $AI_SERVICES_NAME
$env:EMBEDDING_MODEL_DEPLOYMENT = $EMBEDDING_MODEL
$env:FOUNDRY_MODEL_DEPLOYMENT = (azd env get-value FOUNDRY_MODEL_DEPLOYMENT 2>$null)

python create_kb.py

Remove-Item ".env.kb-temp" -ErrorAction SilentlyContinue

# -- 9. Save connection names to azd env for use by app --

azd env set ADVISOR_KNOWLEDGE_BASE_NAME $KB_NAME
azd env set ADVISOR_MCP_CONNECTION $ADVISOR_MCP_CONNECTION
azd env set MCP_TOOLS_CONNECTION $MCP_TOOLS_CONNECTION

# -- 9. Deploy MCP server Function App --
# azd service deploy uses storage account keys which are blocked by policy.
# Deploy via az CLI instead (uses Azure AD auth).

$FUNC_APP_NAME = (azd env get-value FUNCTION_APP_NAME 2>$null)

if ($FUNC_APP_NAME -and $AZURE_RESOURCE_GROUP) {
    Write-Host ""
    Write-Host "=== Deploying MCP server to $FUNC_APP_NAME ==="

    Push-Location mcp-server
    func azure functionapp publish $FUNC_APP_NAME --python
    Pop-Location
    Write-Host "  MCP server deployed successfully"
} else {
    Write-Host "  WARNING: FUNCTION_APP_NAME or AZURE_RESOURCE_GROUP not set, skipping MCP deploy"
}

# -- 10. Write .env from azd env values --

Write-Host ""
Write-Host "=== Writing .env from azd environment ==="

$ENV_FILE = ".env"

$envContent = @"
FOUNDRY_PROJECT_ENDPOINT=$(azd env get-value FOUNDRY_PROJECT_ENDPOINT)
FOUNDRY_MODEL_DEPLOYMENT=$(azd env get-value FOUNDRY_MODEL_DEPLOYMENT)
AZURE_SUBSCRIPTION_ID=$(azd env get-value AZURE_SUBSCRIPTION_ID)
FOUNDRY_PROJECT_RESOURCE_ID=$(azd env get-value FOUNDRY_PROJECT_RESOURCE_ID)
ADVISOR_KNOWLEDGE_BASE_NAME=$KB_NAME
ADVISOR_SEARCH_ENDPOINT=$SEARCH_ENDPOINT
ADVISOR_MCP_CONNECTION=$ADVISOR_MCP_CONNECTION
MCP_TOOLS_ENDPOINT=$MCP_TOOLS_ENDPOINT
MCP_TOOLS_CONNECTION=$MCP_TOOLS_CONNECTION
AI_SERVICES_NAME=$AI_SERVICES_NAME
EMBEDDING_MODEL_DEPLOYMENT=$EMBEDDING_MODEL
"@

Set-Content -Path $ENV_FILE -Value $envContent -NoNewline

$CALENDAR_ENDPOINT = (azd env get-value SCHEDULER_CALENDAR_ENDPOINT 2>$null)
$CALENDAR_CONNECTION = (azd env get-value SCHEDULER_CALENDAR_CONNECTION 2>$null)

if ($CALENDAR_ENDPOINT -and $CALENDAR_ENDPOINT -notmatch "^ERROR:") {
    Add-Content -Path $ENV_FILE -Value "`nSCHEDULER_CALENDAR_ENDPOINT=$CALENDAR_ENDPOINT"
    Add-Content -Path $ENV_FILE -Value "SCHEDULER_CALENDAR_CONNECTION=$CALENDAR_CONNECTION"
}

Write-Host "  .env written"

# -- 11. Register Foundry agents --

Write-Host ""
Write-Host "=== Registering Foundry agents ==="
python deploy_workflow.py

Write-Host ""
Write-Host "=== postprovision complete ==="
Write-Host ""
Write-Host "  Test in Foundry portal playground or run locally:"
Write-Host "    uvicorn api.server:app --reload --port 8000"
Write-Host "    cd ui && npm run dev"
Write-Host ""
Write-Host "MANUAL STEP (optional):"
Write-Host "  Configure Work IQ Calendar connection in the Foundry portal:"
Write-Host "    1. Go to the Foundry project -> Connections"
Write-Host "    2. Add a Work IQ Calendar connection"
Write-Host "    3. Set the following env vars:"
Write-Host "       azd env set SCHEDULER_CALENDAR_ENDPOINT <endpoint-url>"
Write-Host "       azd env set SCHEDULER_CALENDAR_CONNECTION <connection-name>"
Write-Host ""
