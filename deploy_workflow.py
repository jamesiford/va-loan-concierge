"""
Deploy the VA Loan Concierge workflow agent to Azure AI Foundry.

Registers all three sub-agents (orchestrator, advisor, action) and uploads
the workflow YAML as a WorkflowAgentDefinition.

Prerequisites:
  - az login (DefaultAzureCredential uses AzureCliCredential locally)
  - .env populated with all required environment variables
  - MCP Function App deployed (mcp-server/)
  - Knowledge Base created in Foundry portal

Usage:
  python deploy_workflow.py
"""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    MCPTool,
    PromptAgentDefinition,
    WorkflowAgentDefinition,
)
from azure.core.pipeline import PipelineRequest
from azure.core.pipeline.policies import SansIOHTTPPolicy
from azure.identity.aio import DefaultAzureCredential


class _WorkflowPreviewPolicy(SansIOHTTPPolicy):
    """Inject the Foundry-Features header required for workflow agents (preview)."""

    def on_request(self, request: PipelineRequest) -> None:
        request.http_request.headers["Foundry-Features"] = "WorkflowAgents=V1Preview"

from agents.advisor_agent import AdvisorAgent
from agents.action_agent import ActionAgent

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("deploy_workflow")

# ── Workflow-specific orchestrator instructions ─────────────────────────────
# Stricter than the Python backend version: ALWAYS output JSON, never
# conversational text.  The workflow parses this via output.responseObject.

WORKFLOW_ORCHESTRATOR_INSTRUCTIONS = """\
You are a routing classifier for a VA mortgage lender's multi-agent system.

Your ONLY job is to read the Veteran's query and output a JSON routing decision.
You must ALWAYS respond with ONLY a valid JSON object — no explanation, no
markdown, no code fences, no preamble. Just the raw JSON.

Output format (exactly):
{"needs_advisor": <bool>, "needs_action": <bool>}

Routing rules:

  needs_advisor = true when the query involves:
    — eligibility questions, IRRRL qualification, VA loan benefits, entitlement,
      funding fee rules, property requirements, loan process steps, FAQ, myths,
      second-time use, surviving spouse rules, or anything the Veteran needs to
      understand before taking action.

  needs_action = true when the query involves:
    — refinance savings calculations, monthly savings, break-even timelines,
      closing costs, VA net tangible benefit test, or scheduling/booking an
      appointment with a loan officer.

Both may be true for mixed queries (e.g. "Am I eligible AND show me my savings
AND book Thursday").

Default needs_advisor to true if the query is ambiguous or unclear.
"""


async def main() -> None:
    logger.info("Starting workflow deployment...")

    # ── Step 1: Initialize sub-agents (creates ARM connections + registers) ──
    logger.info("Step 1/3: Registering sub-agents...")

    advisor = AdvisorAgent()
    action = ActionAgent()

    await asyncio.gather(
        advisor.initialize(),
        action.initialize(),
    )
    logger.info(
        "Sub-agents registered — advisor=%s, action=%s",
        advisor.agent_version,
        action.agent_id,
    )

    # ── Step 2: Register workflow-specific orchestrator ──────────────────────
    logger.info("Step 2/3: Registering workflow orchestrator...")

    credential = DefaultAzureCredential()
    client = AIProjectClient(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        credential=credential,
        per_call_policies=[_WorkflowPreviewPolicy()],
    )

    orch_version = await client.agents.create_version(
        agent_name="va-loan-orchestrator",
        description="VA Loan Concierge — routing classifier (workflow mode)",
        definition=PromptAgentDefinition(
            model=os.environ["MODEL_DEPLOYMENT_NAME"],
            instructions=WORKFLOW_ORCHESTRATOR_INSTRUCTIONS,
        ),
    )
    logger.info("Orchestrator registered — version=%s", orch_version.version)

    # ── Step 3: Upload workflow ──────────────────────────────────────────────
    logger.info("Step 3/3: Uploading workflow...")

    workflow_yaml = Path("workflow.yaml").read_text(encoding="utf-8")

    workflow_version = await client.agents.create_version(
        agent_name="va-loan-concierge-workflow",
        description="VA Loan Concierge — multi-agent workflow (advisor + action)",
        definition=WorkflowAgentDefinition(workflow=workflow_yaml),
    )
    logger.info(
        "Workflow deployed — name=va-loan-concierge-workflow, version=%s",
        workflow_version.version,
    )

    # ── Cleanup ─────────────────────────────────────────────────────────────
    await advisor.close()
    await action.close()
    await client.close()
    await credential.close()

    logger.info("Deployment complete! Test in the Foundry portal playground.")
    logger.info(
        "Open your project → Build → Agents → va-loan-concierge-workflow → Playground"
    )


if __name__ == "__main__":
    asyncio.run(main())
