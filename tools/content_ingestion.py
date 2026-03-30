"""
Content Understanding ingestion pipeline for VA mortgage news.

This module runs inside the Azure Function App (mcp-server/), triggered either
on a 4-hour timer or via HTTP POST /ingest for manual testing. It uses Azure
Content Understanding (CU) — a GA Foundry Tool — to process RSS feed articles
into structured JSON, then pushes the results to an Azure AI Search index that
is wired into the Foundry IQ Knowledge Base as a second knowledge source.

Pipeline flow:
  RSS feeds ──► feedparser ──► CU (begin_analyze) ──► structured JSON
      ──► Azure AI Search "va-loan-news" index
          ──► Foundry IQ KB (second source, manual portal step)
              ──► Advisor Agent (existing — no code changes needed)

Authentication:
  ContentUnderstandingClient: DefaultAzureCredential → AI Services endpoint
  SearchClient: DefaultAzureCredential → Azure AI Search endpoint
  (Both use the same managed identity / az login credential.)

Required environment variables:
  CU_ENDPOINT                — AI Services endpoint for Content Understanding
                               e.g. https://{ais-name}.services.ai.azure.com/
  CU_COMPLETION_DEPLOYMENT   — GPT deployment for CU field generation (e.g. gpt-4.1)
  CU_MINI_MODEL_DEPLOYMENT   — GPT-mini deployment for CU defaults (e.g. gpt-4.1-mini)
  CU_LARGE_EMBEDDING_DEPLOYMENT — Large embedding for CU defaults (e.g. text-embedding-3-large)
  CU_ANALYZER_NAME           — Name of the CU analyzer resource (e.g. vaMortgageNews)
  CU_NEWS_INDEX_NAME         — Azure AI Search index for ingested articles (e.g. va-loan-news)
  ADVISOR_SEARCH_ENDPOINT    — Azure AI Search service endpoint

Key design decisions:
  - CU is batch/async, not real-time. Articles take seconds to analyze.
  - Deduplication: SHA-256 of article URL as document ID; already-indexed
    articles are skipped before CU analysis to save cost and latency.
  - CU defaults must be set once per resource (3 model keys: gpt-4.1,
    gpt-4.1-mini, text-embedding-3-large). The analyzer itself uses only
    "completion" and "embedding" internal keys.
  - The search index is push-based (no indexer). The Function App writes
    directly via SearchClient.upload_documents().
  - No blob storage for ingested articles — the search index IS the store.
"""

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import feedparser
from azure.ai.contentunderstanding import ContentUnderstandingClient
from azure.ai.contentunderstanding.models import (
    AnalysisInput,
    ContentAnalyzer,
    ContentFieldDefinition,
    ContentFieldSchema,
)
from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

logger = logging.getLogger(__name__)


# ── Field Value Extraction ──────────────────────────────────────────────────────

def _extract_field_value(field_value: Any) -> Any:
    """
    Recursively extract a plain Python value from a CU ContentField object.

    CU SDK 1.0.1 returns typed field objects (StringField, NumberField, ObjectField,
    etc.) with type-specific value attributes instead of a common `.value` property.
    Each type is tried in order; None is returned if the field has no extracted value
    (e.g. an "extract" field where CU couldn't find the content), allowing callers
    to fall back to the original article metadata.
    """
    if field_value is None:
        return None

    # Scalar types — try the most common typed attributes first.
    for attr in (
        "value_string",
        "value_number",
        "value_integer",
        "value_boolean",
        "value_date",
        "value_time",
        "value_phone_number",
        "value_address",
        "value_currency",
        "value_selection_mark",
    ):
        val = getattr(field_value, attr, None)
        if val is not None:
            return val

    # Object field — recurse into each sub-field.
    value_object = getattr(field_value, "value_object", None)
    if value_object is not None:
        return {k: _extract_field_value(v) for k, v in value_object.items()}

    # Array field — recurse into each element.
    value_array = getattr(field_value, "value_array", None)
    if value_array is not None:
        return [_extract_field_value(v) for v in value_array]

    # Generic fallback for future SDK versions that add a unified .value.
    val = getattr(field_value, "value", None)
    if val is not None:
        return val

    # No value found — let the caller fall back to source metadata.
    return None


# ── CU Analyzer Field Schema ───────────────────────────────────────────────────

# Feed sources config lives alongside this file.
_FEED_SOURCES_PATH = Path(__file__).parent / "feed_sources.json"

# This schema defines what CU extracts from each RSS article.
# Three extraction methods are used:
#   extract  — pulls literal values present in the content (title, date)
#   generate — uses the LLM to produce structured output (summary, rate info)
#   classify — categorizes the article into a predefined enum (source type)
_ANALYZER_SCHEMA = ContentFieldSchema(
    name="va-mortgage-news-schema",
    description="Structured extraction schema for VA mortgage news articles",
    fields={
        # ── Extracted fields (literal values from article content) ──────────
        "Title": ContentFieldDefinition(
            method="extract",
            type="string",
            description="The article headline or title",
        ),
        "PublishDate": ContentFieldDefinition(
            method="extract",
            type="date",
            description="The publication date of the article",
        ),
        # ── Classified field (enum categorization) ──────────────────────────
        "SourceType": ContentFieldDefinition(
            method="classify",
            type="string",
            enum=[
                "rate_change",      # Weekly/monthly rate surveys (e.g. Freddie Mac PMMS)
                "policy_update",    # Regulatory or agency policy changes (CFPB, VA)
                "industry_news",    # General mortgage market news
                "va_circular",      # VA-issued circulars and policy letters
                "lender_bulletin",  # Lender-specific announcements
            ],
            description="Category of this news item",
        ),
        # ── Generated fields (LLM-produced structured output) ───────────────
        "Summary": ContentFieldDefinition(
            method="generate",
            type="string",
            description=(
                "A 2-3 sentence summary written for VA-eligible veterans and mortgage "
                "lenders. Highlight what changed, who is affected, and any action required."
            ),
        ),
        "RateInfo": ContentFieldDefinition(
            method="generate",
            type="object",
            description=(
                "If the article contains rate information, extract: "
                "current_rate (float, e.g. 6.72 for 6.72%), "
                "previous_rate (float), "
                "effective_date (ISO date string, e.g. '2026-03-28'), "
                "direction ('up' | 'down' | 'unchanged'). "
                "Return null for all fields if this is not a rate article."
            ),
            properties={
                "current_rate": ContentFieldDefinition(type="number"),
                "previous_rate": ContentFieldDefinition(type="number"),
                "effective_date": ContentFieldDefinition(type="string"),
                "direction": ContentFieldDefinition(
                    type="string",
                    enum=["up", "down", "unchanged"],
                ),
            },
        ),
        "PolicyUpdate": ContentFieldDefinition(
            method="generate",
            type="object",
            description=(
                "If the article describes a policy or regulatory change, extract: "
                "affected_area (e.g. 'VA funding fee', 'IRRRL net tangible benefit test'), "
                "change_description (1-2 sentences describing what changed), "
                "effective_date (ISO date string). "
                "Return null for all fields if this is not a policy article."
            ),
            properties={
                "affected_area": ContentFieldDefinition(type="string"),
                "change_description": ContentFieldDefinition(type="string"),
                "effective_date": ContentFieldDefinition(type="string"),
            },
        ),
        "RelevanceToVeterans": ContentFieldDefinition(
            method="generate",
            type="string",
            description=(
                "One sentence explaining why this news item matters specifically to "
                "VA-eligible veterans or active-duty service members seeking home loans."
            ),
        ),
    },
)


# ═══════════════════════════════════════════════════════════════════════════════
# NewsIngestionPipeline
# ═══════════════════════════════════════════════════════════════════════════════

class NewsIngestionPipeline:
    """
    Orchestrates the full VA mortgage news ingestion pipeline:

      1. ensure_analyzer()  — create CU analyzer if it doesn't exist (idempotent)
      2. fetch_feeds()      — parse all configured RSS feeds into article dicts
      3. analyze_article()  — submit each article to CU, get structured fields
      4. push_to_index()    — upsert the structured doc into Azure AI Search

    Designed to run from either:
      - The 4-hour timer trigger (automated, uses ManagedIdentityCredential)
      - The POST /ingest HTTP trigger (manual testing, same credential)
      - Local Python invocation (uses DefaultAzureCredential via az login)

    Usage:
        pipeline = NewsIngestionPipeline()
        pipeline.ensure_analyzer()   # one-time idempotent setup
        stats = pipeline.run()       # returns {fetched, analyzed, indexed, skipped, errors}
    """

    def __init__(self, credential: TokenCredential | None = None) -> None:
        # Accept an explicit credential for production (ManagedIdentityCredential)
        # or fall back to DefaultAzureCredential for local dev / testing.
        self._credential = credential or DefaultAzureCredential()
        self._cu_client: ContentUnderstandingClient | None = None
        self._search_client: SearchClient | None = None

    # ── Client Accessors (lazy init, cached per pipeline instance) ─────────────

    def _get_cu_client(self) -> ContentUnderstandingClient:
        """Return a cached ContentUnderstandingClient pointed at CU_ENDPOINT."""
        if self._cu_client is None:
            # CU_ENDPOINT must be the services.ai.azure.com format, not cognitiveservices.azure.com
            endpoint = os.environ["CU_ENDPOINT"].rstrip("/")
            self._cu_client = ContentUnderstandingClient(
                endpoint=endpoint,
                credential=self._credential,
            )
        return self._cu_client

    def _get_search_client(self) -> SearchClient:
        """Return a cached SearchClient pointed at the news index."""
        if self._search_client is None:
            self._search_client = SearchClient(
                endpoint=os.environ["ADVISOR_SEARCH_ENDPOINT"],
                index_name=os.environ["CU_NEWS_INDEX_NAME"],
                credential=self._credential,
            )
        return self._search_client

    # ── Analyzer Management ────────────────────────────────────────────────────

    def ensure_analyzer(self) -> None:
        """
        Create the CU analyzer if it does not already exist.
        Idempotent — safe to call on every Function App startup.

        CU setup requires two steps before the first analyzer can be created:
          1. update_defaults() — maps the three required model names to deployment names.
             Keys must be exact model names ("gpt-4.1", "gpt-4.1-mini",
             "text-embedding-3-large"), not generic keys like "completion".
             This is a one-time resource-level setup that persists across sessions.
          2. begin_create_analyzer() — creates the named analyzer with the field
             schema. The analyzer's models dict uses CU's internal "completion" /
             "embedding" keys, which reference the deployment names set in step 1.
        """
        cu = self._get_cu_client()
        analyzer_name = os.environ["CU_ANALYZER_NAME"]

        # Skip creation if the analyzer already exists.
        try:
            existing = cu.get_analyzer(analyzer_name)
            logger.info(
                "content_ingestion: analyzer '%s' already exists (status=%s)",
                analyzer_name, existing.status,
            )
            return
        except Exception:
            pass  # 404 Not Found — proceed to create.

        logger.info("content_ingestion: creating CU analyzer '%s'", analyzer_name)

        # Step 1: Set resource-level model defaults.
        # CU uses these to route "gpt-4.1" → the actual deployment name in your project.
        # All three are required even if only gpt-4.1 is used by this analyzer.
        completion_deployment = os.environ["CU_COMPLETION_DEPLOYMENT"]
        mini_deployment = os.environ["CU_MINI_MODEL_DEPLOYMENT"]
        large_embedding = os.environ["CU_LARGE_EMBEDDING_DEPLOYMENT"]

        cu.update_defaults(model_deployments={
            "gpt-4.1":                completion_deployment,
            "gpt-4.1-mini":           mini_deployment,
            "text-embedding-3-large": large_embedding,
        })
        logger.info(
            "content_ingestion: CU defaults set — "
            "gpt-4.1=%s, gpt-4.1-mini=%s, text-embedding-3-large=%s",
            completion_deployment, mini_deployment, large_embedding,
        )

        # Step 2: Create the analyzer.
        # base_analyzer_id="prebuilt-document" handles HTML and plain text input.
        # models uses CU's internal "completion"/"embedding" keys — not model names.
        analyzer = ContentAnalyzer(
            analyzer_id=analyzer_name,
            description="VA mortgage news structured extraction analyzer",
            base_analyzer_id="prebuilt-document",
            field_schema=_ANALYZER_SCHEMA,
            models={
                "completion": completion_deployment,
                "embedding":  large_embedding,
            },
        )

        poller = cu.begin_create_analyzer(
            analyzer_id=analyzer_name,
            resource=analyzer,
        )
        result = poller.result()
        logger.info(
            "content_ingestion: analyzer '%s' created (status=%s)",
            analyzer_name, result.status,
        )

    # ── Search Index Management ────────────────────────────────────────────────

    def ensure_search_index(self) -> None:
        """
        Create the va-loan-news Azure AI Search index if it does not exist.
        Idempotent — no-op if the index already exists.

        The postprovision.ps1 hook also creates this index at deploy time, so
        this method is primarily for local development and disaster recovery.
        """
        index_name = os.environ["CU_NEWS_INDEX_NAME"]
        search_endpoint = os.environ["ADVISOR_SEARCH_ENDPOINT"]
        index_client = SearchIndexClient(
            endpoint=search_endpoint,
            credential=self._credential,
        )

        existing_names = [idx.name for idx in index_client.list_indexes()]
        if index_name in existing_names:
            logger.info("content_ingestion: search index '%s' already exists", index_name)
            return

        logger.info("content_ingestion: creating search index '%s'", index_name)

        # Index schema mirrors the CU field schema plus search-specific metadata.
        # content_vector uses HNSW (1536 dims = text-embedding-3-small/-large compatible).
        index = SearchIndex(
            name=index_name,
            fields=[
                SimpleField(name="id",                    type=SearchFieldDataType.String,         key=True,  filterable=True),
                SimpleField(name="url",                   type=SearchFieldDataType.String,         filterable=True),
                SimpleField(name="source_name",           type=SearchFieldDataType.String,         filterable=True, facetable=True),
                SimpleField(name="source_type",           type=SearchFieldDataType.String,         filterable=True, facetable=True),
                SimpleField(name="ingested_at",           type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
                SearchField(name="title",                 type=SearchFieldDataType.String,         searchable=True),
                SearchField(name="publish_date",          type=SearchFieldDataType.String,         searchable=False, filterable=True),
                SearchField(name="summary",               type=SearchFieldDataType.String,         searchable=True),
                SearchField(name="relevance_to_veterans", type=SearchFieldDataType.String,         searchable=True),
                SearchField(name="rate_info",             type=SearchFieldDataType.String,         searchable=True),
                SearchField(name="policy_update",         type=SearchFieldDataType.String,         searchable=True),
                SearchField(
                    name="content_vector",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=1536,
                    vector_search_profile_name="va-news-vector-profile",
                ),
            ],
            vector_search=VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="va-news-hnsw")],
                profiles=[VectorSearchProfile(
                    name="va-news-vector-profile",
                    algorithm_configuration_name="va-news-hnsw",
                )],
            ),
            semantic_search=SemanticSearch(
                configurations=[SemanticConfiguration(
                    name="va-news-semantic",
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="title"),
                        content_fields=[
                            SemanticField(field_name="summary"),
                            SemanticField(field_name="relevance_to_veterans"),
                        ],
                    ),
                )]
            ),
        )
        index_client.create_index(index)
        logger.info("content_ingestion: search index '%s' created", index_name)

    # ── Feed Fetching ──────────────────────────────────────────────────────────

    def fetch_feeds(self) -> list[dict[str, Any]]:
        """
        Parse all RSS feeds from feed_sources.json and return a flat list of articles.

        Each article dict contains:
            url           — canonical article URL (used as deduplication key)
            title         — article title from the feed
            published     — publication date string from the feed entry
            content_html  — full HTML body if available, else the summary snippet
            source_name   — human-readable feed name (e.g. "CFPB Newsroom")
            source_type   — feed-level category (e.g. "policy_update")
        """
        sources = json.loads(_FEED_SOURCES_PATH.read_text())
        articles: list[dict[str, Any]] = []

        for source in sources:
            try:
                feed = feedparser.parse(source["url"])
                logger.info(
                    "content_ingestion: fetched '%s' — %d entries",
                    source["name"], len(feed.entries),
                )
                for entry in feed.entries:
                    url = entry.get("link", "")
                    if not url:
                        continue  # Skip entries with no canonical URL.

                    # Prefer full HTML content if available (some feeds include it);
                    # fall back to the summary snippet.
                    content_html = ""
                    if entry.get("content"):
                        content_html = entry["content"][0].get("value", "")
                    if not content_html:
                        content_html = entry.get("summary", "")

                    articles.append({
                        "url":          url,
                        "title":        entry.get("title", ""),
                        "published":    entry.get("published", ""),
                        "content_html": content_html,
                        "source_name":  source["name"],
                        "source_type":  source["source_type"],
                    })
            except Exception as exc:
                logger.warning(
                    "content_ingestion: failed to fetch feed '%s': %s",
                    source["name"], exc,
                )

        logger.info("content_ingestion: %d total articles fetched across all feeds", len(articles))
        return articles

    # ── CU Analysis ───────────────────────────────────────────────────────────

    def analyze_article(self, article: dict[str, Any]) -> dict[str, Any] | None:
        """
        Submit one article to Content Understanding and return extracted fields.

        The article HTML (or title fallback) is sent to the CU analyzer as
        text/html. CU runs gpt-4.1 to extract, classify, and generate the
        7 fields defined in _ANALYZER_SCHEMA.

        Returns a dict of field name → Python value, or None if analysis fails.
        Per-article failures are logged and skipped — they do not abort the batch.
        """
        cu = self._get_cu_client()
        analyzer_name = os.environ["CU_ANALYZER_NAME"]

        content = article["content_html"] or article["title"]
        if not content:
            logger.warning(
                "content_ingestion: skipping article with no content: %s", article["url"]
            )
            return None

        try:
            poller = cu.begin_analyze(
                analyzer_id=analyzer_name,
                inputs=[
                    AnalysisInput(
                        data=content.encode("utf-8"),
                        mime_type="text/html",
                        name="article",
                    )
                ],
                string_encoding="utf8",
            )
            result = poller.result()
        except Exception as exc:
            logger.warning(
                "content_ingestion: CU analysis failed for '%s': %s",
                article["url"], exc,
            )
            return None

        # Extract the 7 schema fields from the first (and only) content item.
        fields: dict[str, Any] = {}
        if result.contents:
            raw_fields = result.contents[0].fields or {}
            for field_name, field_value in raw_fields.items():
                fields[field_name] = _extract_field_value(field_value)

        return fields

    # ── Search Index Push ──────────────────────────────────────────────────────

    def _article_id(self, url: str) -> str:
        """
        Stable, URL-safe document ID derived from the article URL.
        SHA-256 truncated to 32 hex chars — collision probability negligible
        for the expected volume of a few thousand articles.
        """
        return hashlib.sha256(url.encode()).hexdigest()[:32]

    def is_already_indexed(self, url: str) -> bool:
        """
        Return True if this article URL is already in the search index.
        Uses a point-read by document ID (1 RU equivalent) for efficiency.
        """
        search = self._get_search_client()
        doc_id = self._article_id(url)
        try:
            search.get_document(key=doc_id)
            return True
        except Exception:
            return False  # Document not found.

    def push_to_index(
        self,
        article: dict[str, Any],
        cu_fields: dict[str, Any],
    ) -> None:
        """
        Upsert one structured article into the Azure AI Search news index.

        CU "extract" fields (Title, PublishDate) may return None if the content
        didn't contain those values — in that case we fall back to the original
        RSS feed metadata (article["title"], article["published"]).

        Object fields (RateInfo, PolicyUpdate) are serialized to JSON strings
        since the search index stores them as Edm.String for flexibility.
        """
        search = self._get_search_client()

        rate_info = cu_fields.get("RateInfo")
        policy_update = cu_fields.get("PolicyUpdate")

        document = {
            "id":                    self._article_id(article["url"]),
            "url":                   article["url"],
            "source_name":           article["source_name"],
            "source_type":           cu_fields.get("SourceType") or article["source_type"],
            "ingested_at":           datetime.now(UTC).isoformat(),
            "title":                 cu_fields.get("Title") or article["title"],
            "publish_date":          cu_fields.get("PublishDate") or article["published"],
            "summary":               cu_fields.get("Summary") or "",
            "relevance_to_veterans": cu_fields.get("RelevanceToVeterans") or "",
            "rate_info":             json.dumps(rate_info)    if rate_info    else "",
            "policy_update":         json.dumps(policy_update) if policy_update else "",
        }

        search.upload_documents(documents=[document])
        logger.info(
            "content_ingestion: indexed '%s' (%s)",
            document["title"][:60], article["url"],
        )

    # ── Full Pipeline ──────────────────────────────────────────────────────────

    def run(self) -> dict[str, int]:
        """
        Execute the full ingestion pipeline end-to-end.

        For each article across all configured feeds:
          1. Skip if already indexed (deduplication by URL hash)
          2. Analyze with Content Understanding
          3. Push structured result to Azure AI Search

        Returns a summary dict: {fetched, analyzed, indexed, skipped, errors}
        """
        stats = {"fetched": 0, "analyzed": 0, "indexed": 0, "skipped": 0, "errors": 0}

        articles = self.fetch_feeds()
        stats["fetched"] = len(articles)

        for article in articles:
            url = article["url"]

            # Deduplication check — skip articles already in the index.
            if self.is_already_indexed(url):
                logger.debug("content_ingestion: already indexed, skipping: %s", url)
                stats["skipped"] += 1
                continue

            # Analyze with CU — skip this article on failure, continue the batch.
            cu_fields = self.analyze_article(article)
            if cu_fields is None:
                stats["errors"] += 1
                continue
            stats["analyzed"] += 1

            # Push to search index.
            try:
                self.push_to_index(article, cu_fields)
                stats["indexed"] += 1
            except Exception as exc:
                logger.warning(
                    "content_ingestion: push failed for '%s': %s", url, exc
                )
                stats["errors"] += 1

        logger.info("content_ingestion: pipeline complete — %s", stats)
        return stats
