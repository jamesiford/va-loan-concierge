# VA Loan Concierge

A multi-agent demo for a VA mortgage lender built on **Microsoft Azure AI Foundry**. The application showcases three distinct Foundry capabilities — **Foundry IQ** (grounded knowledge-base RAG), **MCP** (live tool invocation via a custom Azure Function), and **Work IQ Calendar** (Microsoft-hosted MCP for M365 calendar management) — working together in a coordinated agent workflow.

Two orchestration paths share the same sub-agents:
- **React UI demo** — Python backend with real-time SSE streaming and an Agent Flow Log
- **Copilot Studio / Teams** — Foundry Workflow Agent (declarative YAML, no container needed)

---

## What It Does

A Veteran borrower interacts with a single chat interface. A single query like:

> *"I'm thinking about refinancing — am I eligible for an IRRRL, and can you show me what I'd save and schedule a call for Thursday?"*

…triggers a multi-agent pipeline that:

1. Answers VA loan eligibility questions with **cited, knowledge-base-grounded responses**
2. Collects loan details via a **human-in-the-loop prompt** (with retry loop and skip option)
3. Runs a **live refinance savings calculator** using real amortization math
4. **Books a consultation appointment** with a loan officer
5. Asks for **appointment confirmation** — confirm, reschedule, or decline
6. **Creates a calendar event** on the Veteran's M365 calendar via Work IQ
7. Streams every step of the reasoning — agent activations, tool calls, source citations — to a real-time Agent Flow Log in the UI

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React UI)                        │
│                                                                   │
│  ┌──────────────────────┐   ┌──────────────────────────────────┐ │
│  │      Chat Panel      │   │        Agent Flow Log            │ │
│  │  (conversation)      │   │   (live reasoning trace)         │ │
│  └──────────┬───────────┘   └──────────────────────────────────┘ │
└─────────────┼───────────────────────────────────────────────────┘
              │ POST /api/chat  (SSE stream)
              ▼
┌─────────────────────────┐
│     FastAPI Backend     │   Streams SSE events to the UI
│     (api/server.py)     │
└────────────┬────────────┘
             │
             ▼
┌────────────────────────┐
│      Orchestrator      │   LLM-driven routing via Foundry agent
│  (orchestrator_agent)  │   Foundry portal: va-loan-orchestrator
└────────┬───────────────┘
         │
    ┌────┼──────────┬──────────────┐
    │    │          │              │
    ▼    ▼          ▼              ▼
┌──────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│Advis-│ │Calcul- │ │Scheduler │ │Calendar  │
│ or   │ │ ator   │ │  Agent   │ │  Agent   │
│Agent │ │ Agent  │ │          │ │          │
│      │ │        │ │Custom MCP│ │Work IQ   │
│Fndry │ │Custom  │ │appt_     │ │Calendar  │
│  IQ  │ │  MCP   │ │scheduler │ │CreateEvt │
└──┬───┘ └───┬────┘ └────┬─────┘ └────┬─────┘
   │         │           │            │
   ▼         ▼           ▼            ▼
 Azure AI  Savings    Appointment   M365
 Search KB Calculator Booking      Calendar
 (3 docs)
```

### Agent Roles

| Agent | Foundry Name | Capability | Purpose |
|---|---|---|---|
| Orchestrator | `va-loan-orchestrator` | New Foundry agent (Responses API) | LLM-driven routing — classifies each query and decides which agent(s) to invoke |
| VA Loan Advisor | `va-loan-advisor-iq` | Foundry IQ via MCPTool | Answers eligibility, product, and process questions grounded in 3 knowledge sources |
| Loan Calculator | `va-loan-calculator-mcp` | Custom MCP via MCPTool | Runs refinance savings calculations via Azure-hosted MCP tools |
| Loan Scheduler | `va-loan-scheduler-mcp` | Custom MCP via MCPTool | Books consultation appointments with loan officers via Azure-hosted MCP tools |
| Calendar | `va-loan-calendar-mcp` | Work IQ Calendar via MCPTool | Creates calendar events on the Veteran's M365 calendar after appointment booking |
| Workflow | `va-loan-concierge-workflow` | Foundry Workflow Agent | Declarative orchestration for Copilot Studio / Teams (routes to all sub-agents) |

---

## Getting Started

### Prerequisites

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`az`)
- [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) (`azd`)
- Python 3.12+
- Node.js 18+
- An Azure subscription with permissions to create resources
- An M365 Copilot license (only needed for the Calendar Agent's Work IQ Calendar integration)

### Provision Infrastructure (`azd up`)

The entire Azure infrastructure is defined as code. A single command provisions everything, deploys the MCP server, and registers all Foundry agents.

```bash
# 1. Clone and enter the repo
git clone https://github.com/<org>/va-loan-concierge.git
cd va-loan-concierge

# 2. Authenticate with Azure
az login
azd auth login

# 3. Provision + deploy everything
azd up
```

`azd up` will prompt you for:
- **Environment name** — e.g. `valc-demo-abc123` (becomes the suffix for all resource names)
- **Azure subscription** — select from your available subscriptions
- **Azure region** — select from the curated list (eastus, eastus2, westus, westus3, swedencentral)

This creates the following Azure resources:

| Resource | Name | Purpose |
|---|---|---|
| Resource Group | `rg-{env}` | Container for all resources |
| AI Services | `ais-{env}` | Foundry + OpenAI models + connections (next-gen) |
| AI Project | `proj-{env}` | Foundry project (agents live here) |
| AI Search | `srch-{env}` | Knowledge base index + Foundry IQ KB for Advisor Agent |
| Function App | `func-{env}` | Custom MCP server — Flex Consumption (FC1) |
| Storage Account | `st{env}` | KB document blobs + Function App runtime |
| Cosmos DB | `cosmos-{env}` | Persistent conversation state (Serverless NoSQL) |
| App Insights | `appi-{env}` | Monitoring + diagnostics |
| Log Analytics | `log-{env}` | Required by App Insights |

Plus RBAC role assignments (including Cosmos data-plane) and 2 RemoteTool project connections — all automated.

After provisioning completes, `azd up` automatically:
1. Uploads the 3 knowledge documents to blob storage
2. Creates an AI Search data source, index, skillset, and indexer (blob → embeddings → vector index)
3. Provisions RemoteTool connections for the KB MCP and custom MCP endpoints
4. Deploys the MCP server to the Function App via `func azure functionapp publish`
5. Writes `.env` from azd environment values
6. Registers all 6 Foundry agents and uploads the workflow definition

> **Updating knowledge sources:** To add or update documents, upload new files to the `knowledge-base` blob container and re-run the Search indexer. No redeployment needed.

### Manual Step 1: Create Foundry IQ Knowledge Base

The Advisor Agent requires a Foundry IQ Knowledge Base that wraps the AI Search index created by `azd up`. This must be created manually in the Foundry portal because the SDK for programmatic KB creation is in preview and unreliable.

1. Open the [Azure AI Foundry portal](https://ai.azure.com) → your project (`proj-{env}`)
2. Go to **Knowledge** (left sidebar) → **+ New knowledge base**
3. Fill in the following:

| Field | Value |
|---|---|
| **Name** | `kb-va-loan-guidelines` |
| **Description** | `VA Loan Concierge knowledge base for the Advisor Agent. Answers Veteran questions about VA loan eligibility, IRRRL qualification, funding fees, entitlement calculations, lender products, and the homebuying process with cited, grounded responses.` |

4. Under **Knowledge sources**, click **+ Add source** → **Azure AI Search index**:
   - Select the search service (`srch-{env}`) and index (`kb-va-loan-guidelines`)
   - Source description:
     > VA loan knowledge base containing eligibility guidelines, lender product details (IRRRL, Cash-Out Refi, VA Jumbo, VA Renovation), and borrower FAQ covering process steps, myths, and edge cases. Sources: VA guidelines, Valor Home Lending products, loan process FAQ.

5. Under **Retrieval settings**:
   - **Output mode**: `Extractive data`
   - **Reasoning effort**: `Low`
   - **Retrieval instructions**:
     > You are answering questions from Veterans about VA home loans. Always search all knowledge sources to find relevant information. Prioritize VA guidelines for eligibility and regulatory questions. Use lender products for rate, pricing, and product-specific questions. Use the FAQ for process steps, common misconceptions, and edge cases. If multiple sources are relevant, synthesize them into a cohesive answer. Always cite which source supports each claim.
   - **Answer instructions**:
     > Provide clear, accurate answers grounded in the knowledge sources. Use a professional but approachable tone appropriate for Veterans. Structure longer answers with bullet points or numbered lists. When citing sources, reference the document name (e.g., va_guidelines.md). If information is not found in the knowledge base, say so clearly — do not speculate or invent facts. For calculations or scheduling requests, note that those are handled by separate specialist agents.

6. Under **Model configuration**:
   - Select the embedding model deployment (`text-embedding-3-small`)
   - Select the chat model deployment (e.g. `gpt-4.1`)

7. Click **Create**

After creation, verify the KB name in your `.env` matches:
```
ADVISOR_KNOWLEDGE_BASE_NAME=kb-va-loan-guidelines
```

### Manual Step 2: Add News Index as Second Knowledge Source (Phase 14)

After `azd up`, the news ingestion pipeline is running and the `va-loan-news` search index has been created. To make the Advisor Agent aware of live VA mortgage news, add this index as a second knowledge source in the Foundry IQ Knowledge Base.

1. Open the [Azure AI Foundry portal](https://ai.azure.com) → your project → **Knowledge**
2. Select your existing knowledge base (`kb-va-loan-guidelines`)
3. Under **Knowledge sources**, click **+ Add source** → **Azure AI Search index**:

| Field | Value |
|---|---|
| **Search service** | `srch-{env}` |
| **Index** | `va-loan-news` |
| **Source description** | `Live VA mortgage news — VA policy updates, CFPB regulatory changes, weekly rate surveys (Freddie Mac PMMS), and industry news. Ingested every 4 hours. Always cite the source name and publish date when referencing this source.` |

4. Under **Retrieval settings** for the new source:
   - **Output mode**: `Extractive data`
   - **Reasoning effort**: `Low`

5. Click **Save**

After this step, the Advisor Agent will automatically query both the policy docs index and the live news index when answering questions about current rates or recent policy changes. No agent code changes are needed — Foundry IQ handles retrieval from all sources.

> **Triggering a manual ingest:** To populate the news index immediately (without waiting for the 4-hour timer), call the manual trigger:
> ```bash
> curl -X POST https://func-{env}.azurewebsites.net/ingest
> ```

### Manual Step 3: Configure Work IQ Calendar (Optional)

The Calendar Agent requires a Work IQ Calendar connection for M365 calendar integration. This needs an M365 Copilot license and must be configured in the Foundry portal.

1. Open the Foundry portal → your project → **Connections**
2. Click **+ New connection** → **Work IQ Calendar**
3. Follow the OAuth consent flow to authorize calendar access
4. Copy the MCP endpoint URL and connection name, then set them:

```bash
azd env set SCHEDULER_CALENDAR_ENDPOINT <endpoint-url>
azd env set SCHEDULER_CALENDAR_CONNECTION <connection-name>
azd hooks run postprovision    # re-writes .env and re-registers agents with calendar connection
```

### Manual Step 4: Assign Guardrails to Agents (Recommended)

`azd up` creates two guardrail policies (`va-loan-advisor-guardrail` and `va-loan-tools-guardrail`) but they must be assigned to agents in the portal:

1. Open the Foundry portal → your project → **Build > Agents**
2. Select `va-loan-advisor-iq` → **Guardrails** → **Manage** → assign `va-loan-advisor-guardrail`
3. Repeat for `va-loan-calculator-mcp` and `va-loan-scheduler-mcp` → assign `va-loan-tools-guardrail`

This enables per-agent content safety controls including jailbreak detection, PII detection, and tool call scanning.

> **Note:** The demo works without the manual steps partially configured — the Advisor Agent needs the KB to answer questions, but the Calculator and Scheduler agents function independently. The Calendar Agent step is skipped if the Work IQ Calendar connection is not configured. Guardrails add safety controls but agents function without them.

### Run the Demo

After `azd up`, run the demo locally:

```bash
# Install Python dependencies
pip install -r requirements.txt

# Terminal 1 — start the FastAPI backend
uvicorn api.server:app --reload --port 8000

# Terminal 2 — start the React UI
cd ui
npm install        # first time only
npm run dev
# → Open http://localhost:5173
```

Select a borrower profile (Marcus, Sarah, or James) and click a demo query button to see the full agent pipeline in action.

### Troubleshooting: Storage Account and Cosmos DB Network Access

Azure subscriptions with strict policy enforcement (managed sandboxes, corporate tenants) may automatically disable public network access on Storage Accounts and Cosmos DB accounts overnight or after certain policy compliance cycles. If `azd up` succeeds but the demo fails the next day with blob upload errors, Knowledge Base indexer failures, or Cosmos DB connection errors, verify that public access is still enabled:

1. **Storage Account** (`st{env}` in the Azure portal):
   - Navigate to **Security + networking** → **Networking**
   - Confirm **Public network access** is set to **Enabled from all networks**
   - If it was disabled by policy, re-enable it and re-run:
     ```bash
     azd hooks run postprovision   # re-uploads KB docs and re-runs indexer
     ```

2. **Cosmos DB** (`cosmos{env}` in the Azure portal):
   - Navigate to **Settings** → **Networking**
   - Confirm **Public network access** is set to **All networks**
   - If disabled, re-enable it and restart the backend (`uvicorn api.server:app --reload --port 8000`)

> **Note for Phase 12 (Network Isolation):** When network isolation is implemented, both resources will use private endpoints instead of public access. For now, public access is required for the demo to function.

### Troubleshooting: Cosmos DB Region Capacity

If `azd up` fails with a Cosmos DB `ServiceUnavailable` error mentioning "high demand for zonal redundant accounts," the selected region has hit availability zone capacity limits. Deploy Cosmos DB to a different region while keeping everything else in your primary region:

```bash
azd env set COSMOS_LOCATION eastus2    # or any region with Cosmos capacity
azd up
```

Cosmos DB is a globally distributed service — the region doesn't need to match the rest of the stack. When `COSMOS_LOCATION` is not set, Cosmos deploys to the same region as all other resources (the default and expected behavior).

### Tear Down

```bash
azd down
```

This deletes the resource group and all resources within it. Clean, no orphans.

---

## Alternative: CLI-Only Mode

Run the flagship query end-to-end in the terminal without the UI:

```bash
az login
pip install -r requirements.txt

# Default flagship IRRRL scenario
python main.py

# Custom query
python main.py --query "Can I use my VA loan benefit a second time?"
```

---

## Running Tests

```bash
pytest tests/     # 111 tests — all agents mocked, no Azure calls needed
```

---

## Running Evaluations

Agent evaluations run server-side via the OpenAI Evals API. Queries are sent directly to your registered Foundry agents, evaluated by builtin evaluators, and results appear in the Foundry portal under **Build > Evaluations**.

```bash
az login
python evals/run_eval.py                       # advisor eval (task adherence, groundedness, coherence, relevance)
python evals/run_eval.py --agent orchestrator  # orchestrator eval (task adherence, coherence)
python evals/run_eval.py --all                 # both
python evals/run_eval.py --cleanup             # delete old evals + files
```

The script polls for completion and prints a portal URL linking directly to the results.

---

## Project Structure

```
va-loan-concierge/
├── azure.yaml                   # azd project definition (services + hooks)
├── main.py                      # Thin CLI entry point
├── profiles.py                  # DEMO_PROFILES + context injection helpers
├── workflow.yaml                # Foundry Workflow Agent definition
├── deploy_workflow.py           # Registers sub-agents + uploads workflow
├── requirements.txt
│
├── infra/                       # Infrastructure-as-code (Bicep)
│   ├── main.bicep               # Orchestrator — wires all modules
│   ├── main.parameters.json     # Maps azd env values to Bicep params
│   ├── modules/
│   │   ├── ai-services.bicep    # AI Services account (Foundry + OpenAI + connections)
│   │   ├── ai-project.bicep     # AI Project (child of AI Services)
│   │   ├── search.bicep         # AI Search (aadOrApiKey auth)
│   │   ├── function-app.bicep   # MCP server Function App
│   │   ├── storage.bicep        # Storage (KB blobs + Function App runtime)
│   │   ├── monitoring.bicep     # Log Analytics + App Insights
│   │   └── rbac.bicep           # All role assignments
│   └── hooks/
│       └── postprovision.ps1    # All post-provision: blob upload, Search index, connections, MCP deploy, .env, agent registration
│
├── agents/
│   ├── orchestrator_agent.py    # Orchestrator — LLM routing + sub-agent coordination
│   ├── advisor_agent.py         # Foundry IQ KB via MCPTool
│   ├── calculator_agent.py      # Custom MCP — refi savings calculator
│   ├── scheduler_agent.py       # Custom MCP — appointment booking
│   └── calendar_agent.py        # Work IQ Calendar MCP — M365 calendar events
│
├── api/
│   ├── server.py                # FastAPI — POST /api/chat SSE endpoint
│   ├── telemetry.py             # OpenTelemetry — Azure Monitor exporter, per-agent spans
│   └── conversation_state.py    # Persistent HIL state (Cosmos DB or in-memory fallback)
│
├── tools/                       # Shared pipeline utilities (used by backend + Function App)
│   ├── content_ingestion.py     # NewsIngestionPipeline — CU analyzer + search push (Phase 14)
│   └── feed_sources.json        # RSS feed configs (VA, CFPB, Freddie Mac, MBA)
│
├── mcp-server/                  # Azure Function App — custom MCP server
│   ├── function_app.py          # Entry point — MCP JSON-RPC handler + imports ingest_trigger
│   ├── server.py                # Tool implementations + inputSchema definitions
│   ├── ingest_trigger.py        # Timer (4h) + HTTP /ingest triggers (Phase 14)
│   ├── tools/                   # Copy of repo-root tools/ — synced by postprovision.ps1
│   │   ├── content_ingestion.py #   (do not edit here — edit tools/ at repo root)
│   │   └── feed_sources.json
│   ├── host.json                # routePrefix: "" → endpoint at /mcp
│   └── requirements.txt
│
├── evals/                       # Agent evaluation datasets and runner
│   ├── eval_advisor.jsonl       # 15 test queries for Advisor Agent
│   ├── eval_orchestrator.jsonl  # 10 test queries for Orchestrator routing
│   └── run_eval.py              # OpenAI Evals API runner (server-side)
│
├── scripts/
│   └── create_guardrails.ps1    # Standalone guardrail policy creation
│
├── knowledge/                   # Knowledge base source documents
│   ├── va_guidelines.md         # VA eligibility rules, IRRRL, funding fees
│   ├── lender_products.md       # Lender loan products and overlays
│   └── loan_process_faq.md      # Borrower FAQ and edge cases
│
├── ui/                          # React frontend
│   └── src/
│       ├── App.jsx              # Root layout + borrower profile state
│       ├── components/
│       │   ├── BorrowerProfile.jsx  # Profile selector + detail card
│       │   ├── ChatPanel.jsx        # Conversation thread
│       │   ├── ChatMessage.jsx      # Message bubble (user, assistant, plan, handoff)
│       │   ├── ChatInput.jsx        # Textarea + send button + demo query buttons
│       │   ├── AgentFlowLog.jsx     # Streaming event log panel
│       │   ├── FlowEvent.jsx        # Single log row
│       │   └── StatusDot.jsx        # Header status indicator
│       └── hooks/
│           └── useAgentStream.js    # SSE connection + profile_id injection
│
└── tests/
    ├── conftest.py
    ├── test_advisor_agent.py
    ├── test_calculator_agent.py
    ├── test_scheduler_agent.py
    ├── test_calendar_agent.py
    └── test_orchestrator.py
```

---

## Key Features

### Foundry IQ — Grounded Knowledge Base (Advisor Agent)

The Advisor Agent connects to an **Azure AI Search Knowledge Base** via MCP with `ProjectManagedIdentity` auth — no API keys.

**Knowledge sources (3 documents):**
- `va_guidelines.md` — VA eligibility rules, COE requirements, IRRRL rules, funding fee tables
- `lender_products.md` — Lender loan products, IRRRL, Cash-Out Refi, VA Jumbo, overlays
- `loan_process_faq.md` — Borrower FAQ, process steps, myths, edge cases

Every factual claim includes a **citation marker** (`【idx†source】`) resolved to a filename and streamed to the UI as a source chip.

### Custom MCP Server — Live Tool Invocation (Calculator + Scheduler)

An **Azure Function App** (`mcp-server/`) implements the MCP JSON-RPC protocol over HTTP. No `mcp` Python package required.

**`refi_savings_calculator`** — Real amortization math:
- Monthly payment delta, annual savings, break-even timeline, lifetime savings net of closing costs
- Applies VA IRRRL closing cost structure ($4,050 base + 0.5% funding fee, waived if disability-exempt)
- Reports whether the **VA net tangible benefit test** passes (break-even ≤ 36 months)

**`appointment_scheduler`** — Books a consultation slot:
- Normalizes fuzzy inputs ("morning", "afternoon", "thurs")
- Returns confirmed slot with loan officer name, calendar date, and confirmation number
- Appointment type is context-aware: "IRRRL review and rate lock" vs. "VA Loan Consultation"

### Human-in-the-Loop — Multi-Turn Conversations

The orchestrator supports **multi-turn conversations** where it pauses to collect user input before proceeding. Session state is persisted in **Cosmos DB** (production) or an in-memory fallback (local dev/tests), with a 10-minute TTL. State survives server restarts in production.

**Calculator HIL — Loan Details Collection:**
When no borrower profile is loaded and the calculator is needed, the orchestrator pauses with a 5-field prompt (balance, current rate, new rate, remaining term, fee exemption). If the calculator can't run with the provided details, it retries up to 3 times — or the user can say "skip" to move on.

**Appointment Confirmation HIL:**
After the Scheduler books an appointment, the orchestrator pauses for confirmation. The user can:
- **Confirm** — Calendar Agent creates an M365 calendar event
- **Reschedule** — Scheduler re-runs with the new preference, then asks again
- **Decline** — Calendar step skipped, appointment still confirmed
- **Unrecognized input** — moves on gracefully without creating a calendar event

Both HIL patterns work in the Python orchestrator (React UI) and the Foundry Workflow Agent (Copilot Studio / Teams), using `GotoAction` loops and `ConditionGroup` branching in the declarative YAML. All HIL pause points include graceful fallbacks for unrecognized input.

### Memory Architecture — Two Layers

The system is designed around **two distinct memory layers** that serve different purposes:

| Layer | Technology | Purpose | Scope |
|---|---|---|---|
| **Session State** | Cosmos DB (Phase 13) | Track orchestration flow within a conversation | Single session, 10-min TTL |
| **Long-Term Memory** | Foundry Memory Stores (Phase 16 — planned) | Remember Veterans across conversations | Cross-session, persistent |

**Session state** is structured and deterministic — routing flags, retry counts, pending actions, accumulated agent results. The Python orchestrator writes state at 11 mutation points; the Workflow Agent uses built-in workflow runtime variables. Both paths maintain behavioral parity.

**Long-term memory** (planned) will use Foundry Memory Stores — a preview feature where the LLM automatically extracts and recalls semantic facts across conversations. Example: after Marcus refinances via IRRRL, the system remembers his rate, fee exemption status, and scheduling preferences. When he returns weeks later for a cash-out question, his context is already loaded — no re-collection needed. Memory Stores are per-agent and shared across both orchestration paths (React UI and Teams).

### Content Understanding — VA Mortgage News Pipeline (Phase 14)

An Azure Content Understanding (CU) pipeline ingests live VA mortgage news from RSS feeds every 4 hours, processes each article into structured fields, and pushes the results to a separate Azure AI Search index (`va-loan-news`). This index is wired into the Foundry IQ Knowledge Base as a second knowledge source, making the Advisor Agent's answers automatically more timely.

**How it works:**
1. An **Azure Functions timer trigger** (`ingest_timer`) runs every 4 hours
2. `feedparser` fetches articles from 4 configured RSS feeds (VA Home Loans, CFPB, Freddie Mac PMMS, MBA Mortgage News)
3. Each article is submitted to a **custom CU analyzer** (`vaMortgageNews`) that uses `gpt-4.1` to extract 7 structured fields:
   - `Title`, `PublishDate` (extracted), `SourceType` (classified into 5 categories)
   - `Summary`, `RateInfo`, `PolicyUpdate`, `RelevanceToVeterans` (generated)
4. Structured results are pushed directly to the `va-loan-news` search index (no indexer needed)
5. The Advisor Agent queries both the policy docs index and the news index automatically

**CU model requirements:** CU requires three deployed models on the AI Services account — `gpt-4.1`, `gpt-4.1-mini`, and `text-embedding-3-large`. All three are deployed by `azd up` via `ai-services.bicep`.

**Manual trigger for testing:**
```bash
curl -X POST https://func-{env}.azurewebsites.net/ingest
# Returns: {"fetched": N, "analyzed": N, "indexed": N, "skipped": N, "errors": N}
```

**Deduplication:** SHA-256 of article URL is used as the document ID. Articles already in the index are skipped before CU analysis — second and subsequent runs complete in seconds.

**Code layout:**
- `tools/content_ingestion.py` — `NewsIngestionPipeline` class (source of truth)
- `tools/feed_sources.json` — RSS feed configurations
- `mcp-server/ingest_trigger.py` — Azure Function timer + HTTP triggers
- `mcp-server/tools/` — copy of the above, synced by `postprovision.ps1` before deploy

> **Keeping `mcp-server/tools/` in sync:** The Function App cannot import from parent directories, so `tools/content_ingestion.py` is copied to `mcp-server/tools/` automatically by `postprovision.ps1` before each Function App publish. Never edit `mcp-server/tools/` directly — edit `tools/content_ingestion.py` at the repo root instead. Running `azd up` keeps everything synchronized.

### Work IQ Calendar — M365 Integration (Calendar Agent)

After the Scheduler confirms an appointment and the user confirms, the Calendar Agent calls `CreateEvent` on the **Work IQ Calendar MCP server** to place it on the Veteran's M365 calendar.

### Demo Borrower Profiles

Three selectable profiles inject personalized context into every agent query:

| Profile | Background | Demo Scenario |
|---|---|---|
| **Marcus T.** | Army Veteran, 10% disability, existing VA loan at 6.8% | IRRRL flagship — fee exempt, full savings calc + booking |
| **Sarah K.** | Navy Veteran, first-time buyer, no existing loan | Purchase eligibility — blocked from IRRRL, gets "VA Loan Consultation" |
| **Lt. James R.** | Active duty, OCONUS deployed, second VA loan use | Second-use eligibility + refi on higher balance |

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| API server | FastAPI + uvicorn (SSE streaming) |
| Foundry SDK | `azure-ai-projects >= 2.0.1` (new-agent API) |
| Auth | `azure-identity` (`DefaultAzureCredential`) |
| MCP server | Azure Functions v2 (plain HTTP trigger) |
| Observability | OpenTelemetry + Azure Monitor exporter → App Insights |
| Infrastructure | Bicep + Azure Developer CLI (`azd`) |
| Tests | `pytest` — 111 tests across all agents |

### Frontend

| Component | Technology |
|---|---|
| Framework | React 18 + Vite |
| Styling | Tailwind CSS v3 |
| Streaming | Native `fetch` with SSE parsing |
| Fonts | Poppins (header) + DM Sans (body) |
| Dev proxy | Vite → FastAPI on port 8000 |

---

## What This Demo Proves

| Capability | Demonstrated By |
|---|---|
| Foundry IQ / grounded RAG | Advisor Agent answering from 3 knowledge sources with inline citations |
| Custom MCP server | Azure Function App implementing MCP JSON-RPC — no SDK dependency |
| Work IQ Calendar | Calendar Agent creating M365 events via Microsoft-hosted MCP |
| Multi-agent orchestration | Single query routed to four specialized agents, responses synthesized |
| LLM-driven routing | Orchestrator Foundry agent classifies intent via Responses API |
| New Foundry agent API | All five agents registered via `create_version` + `PromptAgentDefinition` |
| Real-time streaming | Every agent step streamed to the browser as SSE events |
| Infrastructure-as-code | `azd up` provisions everything; `azd down` tears it all down |
| Human-in-the-loop | Multi-turn conversations with calculator retry loops and appointment confirmation |
| Persistent session state | Cosmos DB preserves HIL conversation state across server restarts (dual-backend with in-memory fallback) |
| Profile-aware responses | Borrower context injected per-query; calculator uses real loan parameters |
| Governed, citable AI | Every factual claim traces back to a specific knowledge document |
| Workflow agent | Declarative YAML orchestration for Copilot Studio / Teams — hardened with HIL parity, graceful fallbacks, and isolated agent contexts |
| Guardrails & content safety | Four defense layers: per-agent Foundry guardrails (tool call + PII scanning), content filter IaC, agent instruction rules, MCP input validation |
| Agent evaluations | OpenAI Evals API targeting registered agents server-side — task adherence, groundedness, coherence, relevance; results visible in Foundry portal (Build > Evaluations) |
| Observability | Two-layer tracing: Foundry portal (LLM I/O, tool calls, tokens) + App Insights (HTTP requests, agent timing, routing decisions) via OpenTelemetry |
| Agent Framework best practices | Orchestration uses `agent_reference` + Responses API — the canonical Microsoft Agent Framework pattern. ConnectedAgentTool (deprecated, classic API), A2APreviewTool (cross-system only), and Microsoft Agent Framework OSS (overkill for sequential pipeline) intentionally not used |
| Content Understanding | Azure Content Understanding GA Foundry Tool — custom CU analyzer extracts structured fields from RSS articles using `gpt-4.1`; timer-triggered Azure Function ingests VA mortgage news every 4 hours; Advisor cites live news with dates alongside static KB sources |

---

## Roadmap

### Completed

| Phase | Name | What It Does |
|---|---|---|
| 1 | Foundation | Refactored orchestrator, profiles, CLI entry point |
| 2 | Agents + HIL | Multi-turn calculator retry loops, appointment confirm/reschedule/decline |
| 3 | Foundry IQ Knowledge Base | Advisor Agent grounded in Azure AI Search KB via MCP (3 knowledge sources, cited responses) |
| 4 | Azure-Hosted MCP Server | Calculator + Scheduler agents calling tools via custom Azure Function App MCP endpoint |
| 5 | Workflow Agent | Declarative YAML orchestration for Copilot Studio / Teams — simplified 740→289 lines, Power Fx fixes, conversationId isolation, general query handling, graceful HIL fallbacks |
| 6 | Infrastructure-as-Code | Full `azd up` / `azd down` flow — Bicep modules, hooks, 15 RBAC assignments; two manual portal steps (KB + calendar) |
| 7 | Guardrails & Content Safety | Four defense layers: Foundry guardrails (per-agent, tool call scanning, PII), content filter IaC (Bicep raiPolicy), agent instruction safety rules, MCP input validation |
| 8 | Agent Evaluations | OpenAI Evals API targeting registered agents server-side — task adherence, groundedness, coherence, relevance; results in Foundry portal (Build > Evaluations) |
| 10 | Observability | Two-layer tracing: Foundry portal (automatic) + App Insights via OpenTelemetry (per-agent spans, routing timing, conversation audit), 90-day retention |
| 13 | Persistent State (Cosmos DB) | HIL conversations survive server restarts — Cosmos DB NoSQL Serverless with dual-backend (in-memory fallback for tests), async SDK, TTL-based expiry, data-plane RBAC |
| 14 | Content Understanding | Live VA mortgage news ingestion — CU analyzer + timer-triggered Azure Function → `va-loan-news` AI Search index → Foundry IQ KB second source; `gpt-4.1` generates summaries, rate info, policy updates, veteran relevance; 4-hour timer + HTTP manual trigger |

### Up Next (independent — can start now)

| Phase | Name | Goal | Key Changes |
|---|---|---|---|
| **15** | **Newsletter Agent** | On-demand email summaries of VA news to Veterans or loan officers | New outbound agent — Azure Communication Services email via MCP tool; orchestrator routes "send me the latest" queries; wired into existing `va-loan-news` index from Phase 14 |

### Planned (blocked on Phase 9)

| Phase | Name | Goal | Blocker |
|---|---|---|---|
| **9** | **Web App Deployment** | Deploy to Azure App Service | Subscription VM quota is 0 — demo runs locally |
| **11** | **Authentication** | Entra ID Easy Auth | Requires Phase 9 (App Service) |
| **12** | **Network Isolation** | VNet + private endpoints | Requires Phase 9 (VNet integration) |
| **16** | **Foundry Memory Stores** | Cross-session Veteran memory — returning borrowers get personalized context | Requires Phase 11 (Auth) — needs authenticated user identity to associate memories |

---

## Teams / M365 Copilot Publishing

The workflow agent can be published to Microsoft Teams and M365 Copilot from the Foundry portal.

### Prerequisites

- **Microsoft 365 Copilot license** (full, not Basic) — required for custom agents in M365 Copilot. Copilot Chat (Basic) shows the agent but returns a generic error when invoked.
- **Same Entra tenant** — the Foundry project, M365 Copilot license, and Teams users must all be in the same Entra tenant. Cross-tenant access requires guest user invitations and RBAC, which may be blocked by tenant policies.
- **Azure AI User role** — users accessing the agent through Teams must have the `Azure AI User` built-in role on the AI Services account/project.

### Publishing Steps

1. In the Foundry portal, navigate to **Build → Agents → va-loan-concierge-workflow**
2. Click **Publish** → **Publish to Teams and M365 Copilot**
3. Fill in the required fields (name, description, icons) and select **Individual** scope
4. The portal auto-creates a Bot Service resource and Entra ServiceIdentity
5. After publishing, the agent appears in M365 Copilot (requires full license)
6. To install in Teams directly, download the **manifest zip** from the publish screen and sideload it via Teams → Apps → Manage your apps → Upload a custom app

### Known Limitations

- **Duplicate responses in Bot Web Chat** — each bot response appears twice. This is a platform-level issue with the activity protocol, not the workflow YAML (Foundry playground shows single responses).
- **ServiceIdentity type** — the auto-created Bot Service identity cannot be changed to MultiTenant and does not support client secret generation for OAuth configuration.
- **Embedding deployment stability** — the `text-embedding-3-small` deployment can enter a broken state where it returns `OperationNotSupported`. Fix by deleting and recreating the deployment via CLI:
  ```bash
  az cognitiveservices account deployment delete --name <ai-services-name> --resource-group <rg-name> --deployment-name text-embedding-3-small
  az cognitiveservices account deployment create --name <ai-services-name> --resource-group <rg-name> --deployment-name text-embedding-3-small --model-name text-embedding-3-small --model-version 1 --model-format OpenAI --sku-name Standard --sku-capacity 30
  ```
- **Cross-tenant not supported** — if the Foundry project and M365 tenant are different, the Foundry OAuth flow returns 500 errors. Deploy everything in the same tenant.

### Bot Web Chat (Alternative Demo Channel)

If M365 Copilot is unavailable, the Bot Service "Test in Web Chat" in the Azure portal provides a working external channel. Navigate to the Bot Service resource → Test in Web Chat.
