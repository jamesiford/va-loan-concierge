"""
Run Foundry evaluations against the VA Loan Concierge agents.

Evaluates the Advisor Agent for:
  - Task adherence (follows instructions, cites sources)
  - Groundedness (answers grounded in KB content)
  - Coherence (well-structured responses)
  - Relevance (addresses the query)
  - Violence (safety check)

Evaluates the Orchestrator for:
  - Task adherence (correct routing classification)

Usage:
    az login
    python evals/run_eval.py                    # run advisor eval
    python evals/run_eval.py --agent orchestrator  # run orchestrator eval
    python evals/run_eval.py --all              # run both

Results appear in the Foundry portal: Build > Evaluations
"""

import argparse
import logging
import os
import sys
import time

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FOUNDRY_PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
MODEL_DEPLOYMENT = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-4.1")

ADVISOR_AGENT_NAME = "va-loan-advisor-iq"
ORCHESTRATOR_AGENT_NAME = "va-loan-orchestrator"

ADVISOR_EVAL_DATASET = os.path.join(os.path.dirname(__file__), "eval_advisor.jsonl")
ORCHESTRATOR_EVAL_DATASET = os.path.join(os.path.dirname(__file__), "eval_orchestrator.jsonl")


def _get_project_client() -> AIProjectClient:
    """Create an authenticated Foundry project client."""
    if not FOUNDRY_PROJECT_ENDPOINT:
        logger.error("FOUNDRY_PROJECT_ENDPOINT not set. Run 'azd up' or check .env.")
        sys.exit(1)
    return AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )


# ---------------------------------------------------------------------------
# Advisor evaluation
# ---------------------------------------------------------------------------

def run_advisor_eval() -> str | None:
    """Run evaluations against the Advisor Agent. Returns the portal report URL."""
    logger.info("=== Running Advisor Agent evaluation ===")
    logger.info("  Agent: %s", ADVISOR_AGENT_NAME)
    logger.info("  Dataset: %s", ADVISOR_EVAL_DATASET)

    project_client = _get_project_client()
    oai = project_client.get_openai_client()

    # 1. Upload the evaluation dataset
    logger.info("  Uploading dataset...")
    with open(ADVISOR_EVAL_DATASET, "rb") as f:
        file_obj = oai.files.create(file=f, purpose="evals")
    logger.info("  Dataset uploaded: %s", file_obj.id)

    # 2. Create the eval definition with testing criteria
    logger.info("  Creating eval definition...")
    eval_obj = oai.evals.create(
        name=f"VA Loan Advisor Quality — {time.strftime('%Y-%m-%d %H:%M')}",
        data_source_config={
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "Task Adherence",
                "evaluator_name": "builtin.task_adherence",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_text}}",
                },
                "initialization_parameters": {
                    "deployment_name": MODEL_DEPLOYMENT,
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "Groundedness",
                "evaluator_name": "builtin.groundedness",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_text}}",
                },
                "initialization_parameters": {
                    "deployment_name": MODEL_DEPLOYMENT,
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "Coherence",
                "evaluator_name": "builtin.coherence",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_text}}",
                },
                "initialization_parameters": {
                    "deployment_name": MODEL_DEPLOYMENT,
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "Relevance",
                "evaluator_name": "builtin.relevance",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_text}}",
                },
                "initialization_parameters": {
                    "deployment_name": MODEL_DEPLOYMENT,
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "Violence",
                "evaluator_name": "builtin.violence",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_text}}",
                },
            },
        ],
    )
    logger.info("  Eval created: %s", eval_obj.id)

    # 3. Create and run the eval run targeting the advisor agent
    logger.info("  Starting eval run (targeting %s)...", ADVISOR_AGENT_NAME)
    run = oai.evals.runs.create(
        eval_id=eval_obj.id,
        name=f"Advisor Run — {time.strftime('%Y-%m-%d %H:%M')}",
        data_source={
            "type": "azure_ai_target_completions",
            "source": {
                "type": "file_id",
                "id": file_obj.id,
            },
            "input_messages": {
                "type": "template",
                "template": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": {
                            "type": "input_text",
                            "text": "{{item.query}}",
                        },
                    },
                ],
            },
            "target": {
                "type": "azure_ai_agent",
                "name": ADVISOR_AGENT_NAME,
            },
        },
    )
    logger.info("  Run started: %s", run.id)

    # 4. Poll for completion
    logger.info("  Waiting for completion...")
    while run.status in ("queued", "in_progress"):
        time.sleep(5)
        run = oai.evals.runs.retrieve(eval_id=eval_obj.id, run_id=run.id)
        logger.info("    Status: %s", run.status)

    if run.status == "completed":
        report_url = getattr(run, "report_url", None)
        logger.info("  Eval complete!")
        if report_url:
            logger.info("  Report: %s", report_url)
        result_counts = getattr(run, "result_counts", None)
        if result_counts:
            logger.info("  Results: %s", result_counts)
        return report_url
    else:
        logger.error("  Eval run failed with status: %s", run.status)
        error = getattr(run, "error", None)
        if error:
            logger.error("  Error: %s", error)
        return None


# ---------------------------------------------------------------------------
# Orchestrator evaluation
# ---------------------------------------------------------------------------

def run_orchestrator_eval() -> str | None:
    """Run evaluations against the Orchestrator Agent. Returns the portal report URL."""
    logger.info("=== Running Orchestrator Agent evaluation ===")
    logger.info("  Agent: %s", ORCHESTRATOR_AGENT_NAME)
    logger.info("  Dataset: %s", ORCHESTRATOR_EVAL_DATASET)

    project_client = _get_project_client()
    oai = project_client.get_openai_client()

    # 1. Upload dataset
    logger.info("  Uploading dataset...")
    with open(ORCHESTRATOR_EVAL_DATASET, "rb") as f:
        file_obj = oai.files.create(file=f, purpose="evals")
    logger.info("  Dataset uploaded: %s", file_obj.id)

    # 2. Create eval
    logger.info("  Creating eval definition...")
    eval_obj = oai.evals.create(
        name=f"VA Loan Orchestrator Routing — {time.strftime('%Y-%m-%d %H:%M')}",
        data_source_config={
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "expected_route": {"type": "string"},
                },
                "required": ["query", "expected_route"],
            },
        },
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "Task Adherence",
                "evaluator_name": "builtin.task_adherence",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_text}}",
                },
                "initialization_parameters": {
                    "deployment_name": MODEL_DEPLOYMENT,
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "Coherence",
                "evaluator_name": "builtin.coherence",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_text}}",
                },
                "initialization_parameters": {
                    "deployment_name": MODEL_DEPLOYMENT,
                },
            },
        ],
    )
    logger.info("  Eval created: %s", eval_obj.id)

    # 3. Run
    logger.info("  Starting eval run (targeting %s)...", ORCHESTRATOR_AGENT_NAME)
    run = oai.evals.runs.create(
        eval_id=eval_obj.id,
        name=f"Orchestrator Run — {time.strftime('%Y-%m-%d %H:%M')}",
        data_source={
            "type": "azure_ai_target_completions",
            "source": {
                "type": "file_id",
                "id": file_obj.id,
            },
            "input_messages": {
                "type": "template",
                "template": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": {
                            "type": "input_text",
                            "text": "{{item.query}}",
                        },
                    },
                ],
            },
            "target": {
                "type": "azure_ai_agent",
                "name": ORCHESTRATOR_AGENT_NAME,
            },
        },
    )
    logger.info("  Run started: %s", run.id)

    # 4. Poll
    logger.info("  Waiting for completion...")
    while run.status in ("queued", "in_progress"):
        time.sleep(5)
        run = oai.evals.runs.retrieve(eval_id=eval_obj.id, run_id=run.id)
        logger.info("    Status: %s", run.status)

    if run.status == "completed":
        report_url = getattr(run, "report_url", None)
        logger.info("  Eval complete!")
        if report_url:
            logger.info("  Report: %s", report_url)
        result_counts = getattr(run, "result_counts", None)
        if result_counts:
            logger.info("  Results: %s", result_counts)
        return report_url
    else:
        logger.error("  Eval run failed with status: %s", run.status)
        error = getattr(run, "error", None)
        if error:
            logger.error("  Error: %s", error)
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run Foundry agent evaluations")
    parser.add_argument(
        "--agent",
        choices=["advisor", "orchestrator"],
        default="advisor",
        help="Which agent to evaluate (default: advisor)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run evaluations for all agents",
    )
    args = parser.parse_args()

    if args.all:
        run_advisor_eval()
        print()
        run_orchestrator_eval()
    elif args.agent == "advisor":
        run_advisor_eval()
    elif args.agent == "orchestrator":
        run_orchestrator_eval()


if __name__ == "__main__":
    main()
