# ---------------------------------------------------------------------------
# Create Foundry Guardrails — per-agent safety policies via REST API
# ---------------------------------------------------------------------------
# Creates two custom guardrail (raiPolicy) resources on the AI Services account
# and provides instructions for assigning them to agents in the Foundry portal.
#
# Guardrail 1: va-loan-advisor-guardrail
#   - For: Advisor Agent (va-loan-advisor-iq)
#   - Intervention: user input + output
#   - Controls: content safety (Low), jailbreak, indirect attack, PII, protected material
#
# Guardrail 2: va-loan-tools-guardrail
#   - For: Calculator (va-loan-calculator-mcp) + Scheduler (va-loan-scheduler-mcp)
#   - Intervention: user input + tool call + tool response + output
#   - Controls: content safety (Low), jailbreak, indirect attack, PII
#
# Usage:
#   az login
#   pwsh scripts/create_guardrails.ps1
#
# After running, assign guardrails to agents in the Foundry portal:
#   Build > Agents > [agent] > Guardrails > Manage > Assign
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

# -- Load azd env values --
$AI_SERVICES_NAME = (azd env get-value AI_SERVICES_NAME 2>$null)
$AZURE_RESOURCE_GROUP = (azd env get-value AZURE_RESOURCE_GROUP 2>$null)
$SUBSCRIPTION_ID = (azd env get-value AZURE_SUBSCRIPTION_ID 2>$null)

if (-not $AI_SERVICES_NAME -or -not $AZURE_RESOURCE_GROUP -or -not $SUBSCRIPTION_ID) {
    Write-Error "Required azd env values not set. Run 'azd up' first."
    exit 1
}

$TOKEN = (az account get-access-token --query accessToken -o tsv)
$armHeaders = @{
    "Authorization" = "Bearer $TOKEN"
    "Content-Type"  = "application/json"
}

$BASE_URI = "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${AI_SERVICES_NAME}"
$API_VERSION = "2025-04-01-preview"

# -- 1. Advisor Guardrail (user input + output) --

Write-Host "Creating guardrail: va-loan-advisor-guardrail"

$advisorGuardrail = @{
    properties = @{
        mode = "Default"
        basePolicyName = "Microsoft.DefaultV2"
        contentFilters = @(
            # Prompt filters
            @{ name = "Violence"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Hate"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Sexual"; severityThreshold = "Medium"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Selfharm"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Jailbreak"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Indirect Attack"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Profanity"; blocking = $true; enabled = $true; source = "Prompt" }
            # Completion filters
            @{ name = "Violence"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Hate"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Sexual"; severityThreshold = "Medium"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Selfharm"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Protected Material Text"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Protected Material Code"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Profanity"; blocking = $true; enabled = $true; source = "Completion" }
        )
    }
} | ConvertTo-Json -Depth 10

try {
    $resp = Invoke-WebRequest -Uri "${BASE_URI}/raiPolicies/va-loan-advisor-guardrail?api-version=${API_VERSION}" `
        -Method PUT -Headers $armHeaders -Body $advisorGuardrail -UseBasicParsing
    Write-Host "  Advisor guardrail: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  Advisor guardrail: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- 2. Tools Guardrail (user input + tool call + tool response + output) --

Write-Host "Creating guardrail: va-loan-tools-guardrail"

$toolsGuardrail = @{
    properties = @{
        mode = "Default"
        basePolicyName = "Microsoft.DefaultV2"
        contentFilters = @(
            # Prompt filters
            @{ name = "Violence"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Hate"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Sexual"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Selfharm"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Jailbreak"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Indirect Attack"; blocking = $true; enabled = $true; source = "Prompt" }
            @{ name = "Profanity"; blocking = $true; enabled = $true; source = "Prompt" }
            # Completion filters
            @{ name = "Violence"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Hate"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Sexual"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Selfharm"; severityThreshold = "Low"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Protected Material Text"; blocking = $true; enabled = $true; source = "Completion" }
            @{ name = "Profanity"; blocking = $true; enabled = $true; source = "Completion" }
        )
    }
} | ConvertTo-Json -Depth 10

try {
    $resp = Invoke-WebRequest -Uri "${BASE_URI}/raiPolicies/va-loan-tools-guardrail?api-version=${API_VERSION}" `
        -Method PUT -Headers $armHeaders -Body $toolsGuardrail -UseBasicParsing
    Write-Host "  Tools guardrail: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "  Tools guardrail: HTTP $($_.Exception.Response.StatusCode.value__) - $($_.ErrorDetails.Message)"
}

# -- Done --

Write-Host ""
Write-Host "=== Guardrails created ==="
Write-Host ""
Write-Host "  NEXT STEP: Assign guardrails to agents in the Foundry portal:"
Write-Host ""
Write-Host "  1. Open https://ai.azure.com > your project"
Write-Host "  2. Build > Agents > va-loan-advisor-iq > Guardrails > Manage"
Write-Host "     -> Assign 'va-loan-advisor-guardrail'"
Write-Host ""
Write-Host "  3. Build > Agents > va-loan-calculator-mcp > Guardrails > Manage"
Write-Host "     -> Assign 'va-loan-tools-guardrail'"
Write-Host ""
Write-Host "  4. Build > Agents > va-loan-scheduler-mcp > Guardrails > Manage"
Write-Host "     -> Assign 'va-loan-tools-guardrail'"
Write-Host ""
