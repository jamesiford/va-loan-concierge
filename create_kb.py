"""
Create the Foundry IQ Knowledge Base for the VA Loan Advisor Agent.

Sets up:
  1. A SearchIndex knowledge source wrapping our existing 'kb-va-loan-guidelines' index
  2. A Knowledge Base that references that source with our embedding model

Prerequisites:
  - .env populated (ADVISOR_SEARCH_ENDPOINT, AI_SERVICES_NAME, EMBEDDING_MODEL_DEPLOYMENT)
  - The search index 'kb-va-loan-guidelines' must already exist (created by postprovision)
  - azure-search-documents==11.7.0b2

Usage:
  python create_kb.py
"""

import logging
import os

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizerParameters,
    KnowledgeBase,
    KnowledgeBaseAzureOpenAIModel,
    KnowledgeRetrievalLowReasoningEffort,
    KnowledgeRetrievalOutputMode,
    KnowledgeSourceReference,
    SearchIndexKnowledgeSource,
    SearchIndexKnowledgeSourceParameters,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("create_kb")

# ── Configuration ────────────────────────────────────────────────────────────

SEARCH_ENDPOINT = os.environ["ADVISOR_SEARCH_ENDPOINT"]
AI_SERVICES_NAME = os.environ.get("AI_SERVICES_NAME", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL_DEPLOYMENT", "text-embedding-3-small")
CHAT_MODEL = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-4.1")

INDEX_NAME = "kb-va-loan-guidelines"
KB_NAME = INDEX_NAME  # KB shares the same name as the index

# Azure OpenAI endpoint for the embedding model (on the AI Services account)
AOAI_ENDPOINT = f"https://{AI_SERVICES_NAME}.openai.azure.com" if AI_SERVICES_NAME else ""


def main() -> None:
    logger.info("Creating Foundry IQ Knowledge Base: %s", KB_NAME)

    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(
        endpoint=SEARCH_ENDPOINT,
        credential=credential,
    )

    # ── Step 1: Create Knowledge Source (wraps the existing search index) ─────

    logger.info("Step 1/2: Creating knowledge source wrapping index '%s'", INDEX_NAME)

    knowledge_source = SearchIndexKnowledgeSource(
        name=INDEX_NAME,
        description=(
            "VA loan knowledge base containing eligibility guidelines, "
            "lender product details (IRRRL, Cash-Out Refi, VA Jumbo, VA Renovation), "
            "and borrower FAQ covering process steps, myths, and edge cases. "
            "Sources: VA guidelines, Valor Home Lending products, loan process FAQ."
        ),
        search_index_parameters=SearchIndexKnowledgeSourceParameters(
            search_index_name=INDEX_NAME,
        ),
    )

    index_client.create_or_update_knowledge_source(knowledge_source)
    logger.info("  Knowledge source '%s' created", INDEX_NAME)

    # ── Step 2: Create Knowledge Base ────────────────────────────────────────

    logger.info("Step 2/2: Creating knowledge base '%s'", KB_NAME)

    aoai_params = AzureOpenAIVectorizerParameters(
        resource_url=AOAI_ENDPOINT,
        deployment_name=CHAT_MODEL,
        model_name=CHAT_MODEL,
    )

    kb = KnowledgeBase(
        name=KB_NAME,
        description=(
            "VA Loan Concierge knowledge base for the Advisor Agent. "
            "Answers Veteran questions about VA loan eligibility, IRRRL qualification, "
            "funding fees, entitlement calculations, lender products, and the "
            "homebuying process with cited, grounded responses."
        ),
        retrieval_instructions=(
            "You are answering questions from Veterans about VA home loans. "
            "Always search all knowledge sources to find relevant information. "
            "Prioritize VA guidelines for eligibility and regulatory questions. "
            "Use lender products for rate, pricing, and product-specific questions. "
            "Use the FAQ for process steps, common misconceptions, and edge cases. "
            "If multiple sources are relevant, synthesize them into a cohesive answer. "
            "Always cite which source supports each claim."
        ),
        answer_instructions=(
            "Provide clear, accurate answers grounded in the knowledge sources. "
            "Use a professional but approachable tone appropriate for Veterans. "
            "Structure longer answers with bullet points or numbered lists. "
            "When citing sources, reference the document name (e.g., va_guidelines.md). "
            "If information is not found in the knowledge base, say so clearly — "
            "do not speculate or invent facts. "
            "For calculations or scheduling requests, note that those are handled "
            "by separate specialist agents."
        ),
        output_mode=KnowledgeRetrievalOutputMode.ANSWER_SYNTHESIS,
        knowledge_sources=[
            KnowledgeSourceReference(name=INDEX_NAME),
        ],
        models=[KnowledgeBaseAzureOpenAIModel(azure_open_ai_parameters=aoai_params)],
        retrieval_reasoning_effort=KnowledgeRetrievalLowReasoningEffort(),
    )

    index_client.create_or_update_knowledge_base(kb)
    logger.info("  Knowledge base '%s' created", KB_NAME)

    logger.info("Done! KB should now appear in the Foundry portal under Knowledge.")


if __name__ == "__main__":
    main()
