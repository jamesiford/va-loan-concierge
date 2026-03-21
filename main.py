"""
VA Loan Concierge — CLI entry point.

Runs the flagship demo query (or a custom --query) against the multi-agent
orchestrator and prints the streaming event log to the terminal.

For the API server, use:
    uvicorn api.server:app --reload --port 8000
"""

import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv

from agents.orchestrator_agent import Orchestrator
from profiles import FLAGSHIP_QUERY

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

# ---------------------------------------------------------------------------
# CLI event renderer
# ---------------------------------------------------------------------------

_EVENT_PREFIXES: dict[str, str] = {
    "orchestrator_start":      "⬡  Orchestrator",
    "orchestrator_route":      "→  Orchestrator",
    "advisor_start":           "📚 Advisor",
    "advisor_source":          "🔍 Advisor",
    "advisor_result":          "✓  Advisor",
    "action_start":            "⚙️  Action",
    "action_tool_call":        "🔧 Action",
    "action_tool_result":      "✓  Action",
    "handoff":                 "⇄  Handoff",
    "orchestrator_synthesize": "⬡  Orchestrator",
    "complete":                "✓  Complete",
    "error":                   "✗  Error",
}

_DIVIDER = "─" * 60


def _print_event(event: dict) -> None:
    etype = event.get("type", "")

    if etype == "final_response":
        print(f"\n{_DIVIDER}")
        print("  VA LOAN CONCIERGE RESPONSE")
        print(_DIVIDER)
        print(event.get("content", ""))
        print(_DIVIDER)
        return

    prefix = _EVENT_PREFIXES.get(etype, f"   {etype}")
    message = event.get("message", "")

    if etype == "action_tool_call":
        inputs = event.get("inputs", {})
        inputs_str = ",  ".join(f"{k}={v}" for k, v in inputs.items())
        print(f"  {prefix}: {message}")
        if inputs_str:
            print(f"           {inputs_str}")
    else:
        print(f"  {prefix}: {message}")


# ---------------------------------------------------------------------------
# CLI main
# ---------------------------------------------------------------------------

async def _cli_main(query: str) -> None:
    print(f"\n{_DIVIDER}")
    print("  VA LOAN CONCIERGE — DEMO")
    print(_DIVIDER)
    print(f"  Query: {query}")
    print(_DIVIDER)
    print()

    orchestrator = Orchestrator()
    try:
        await orchestrator.initialize()
        async for event in orchestrator.run(query):
            _print_event(event)
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VA Loan Concierge — multi-agent demo (CLI mode)"
    )
    parser.add_argument(
        "--query",
        default=FLAGSHIP_QUERY,
        help="Question to send to the concierge (default: flagship IRRRL demo query)",
    )
    args = parser.parse_args()
    asyncio.run(_cli_main(args.query))
