"""
VA Loan Concierge — Borrower profiles and context helpers.

DEMO_PROFILES defines three demo borrowers used throughout the application.
The context helpers build structured blocks that are injected into agent
queries so agents can give personalised, contextually accurate answers.
"""

# ---------------------------------------------------------------------------
# Demo scenario — flagship query
# ---------------------------------------------------------------------------

FLAGSHIP_QUERY = (
    "I'm thinking about refinancing my VA loan. Am I eligible for an IRRRL, "
    "and can you show me what I'd save and schedule a call for Thursday?"
)

# ---------------------------------------------------------------------------
# Demo borrower profiles
# ---------------------------------------------------------------------------

DEMO_PROFILES: dict[str, dict] = {
    "marcus": {
        "name": "Marcus T.",
        "service": "U.S. Army, 8 years, honorably discharged (2018)",
        "disability": "Service-connected disability rating: 10% — funding fee exempt",
        "loan_type": "Existing VA loan — IRRRL refinance candidate",
        "balance": 320000,
        "current_rate": 6.8,
        "new_rate": 6.1,
        "remaining_term": 27,
        "funding_fee_exempt": True,
        "preferred_day": "Thursday",
        "preferred_time": "2:00 PM",
    },
    "sarah": {
        "name": "Sarah K.",
        "service": "U.S. Navy, 4 years active duty, honorably discharged (2021)",
        "disability": "No service-connected disability",
        "loan_type": "First VA loan — home purchase",
        "balance": 350000,
        "current_rate": None,
        "new_rate": 6.25,
        "remaining_term": 30,
        "funding_fee_exempt": False,
        "preferred_day": "Monday",
        "preferred_time": "10:00 AM",
    },
    "james": {
        "name": "Lt. James R.",
        "service": "U.S. Army, active duty (currently deployed — OCONUS)",
        "disability": "No service-connected disability",
        "loan_type": "Second VA loan use — entitlement restored after first home sold",
        "balance": 400000,
        "current_rate": 7.1,
        "new_rate": 6.3,
        "remaining_term": 29,
        "funding_fee_exempt": False,
        "preferred_day": "Friday",
        "preferred_time": "3:00 PM",
    },
}


def _profile_context_block(profile_id: str | None) -> str:
    """
    Return a structured borrower context block to prepend to every query.

    When no profile is selected the agents are told to gather personal
    information conversationally rather than assuming default values.
    """
    if not profile_id or profile_id not in DEMO_PROFILES:
        return (
            "[Context: No borrower profile is loaded. For questions that require "
            "the Veteran's personal details — such as service history, current loan "
            "information, or disability status — please ask for those details "
            "conversationally before making assumptions.]"
        )
    p = DEMO_PROFILES[profile_id]
    lines = [
        f"[Borrower Profile — {p['name']}]",
        f"  Service:  {p['service']}",
        f"  Disability: {p['disability']}",
        f"  Loan: {p['loan_type']}",
    ]
    if p.get("balance"):
        lines.append(f"  Loan balance: ${p['balance']:,}")
    if p.get("current_rate"):
        lines.append(f"  Current rate: {p['current_rate']}%")
    if p.get("new_rate"):
        lines.append(f"  Quoted new rate: {p['new_rate']}%")
    if p.get("remaining_term"):
        lines.append(f"  Remaining term: {p['remaining_term']} years")
    return "\n".join(lines)


def _demo_context_block(query: str, profile_id: str | None = None) -> str:
    """
    Build a structured tool-parameter block for the Action Agent.

    Uses the selected borrower profile's loan data when available;
    falls back to hardcoded demo defaults otherwise.
    """
    q = query.lower()
    p = DEMO_PROFILES.get(profile_id or "", {})
    parts: list[str] = []

    current_rate = p.get("current_rate")
    if any(kw in q for kw in ("calculat", "saving", "save", "how much", "refinanc", "irrrl")):
        if current_rate is None:
            # Profile has no existing loan (e.g. first-time buyer) — can't run refi calc.
            parts.append(
                "[Note: This borrower has no existing VA loan, so the refi_savings_calculator "
                "cannot be used. Inform them that IRRRL refinancing requires an existing VA loan.]"
            )
        else:
            balance = p.get("balance", 320000)
            new_rate = p.get("new_rate", 6.1)
            remaining_term = p.get("remaining_term", 27)
            funding_fee_exempt = p.get("funding_fee_exempt", True)
            parts.append(
                "[Loan parameters for the refinance calculation — "
                f"pass these exactly to the refi_savings_calculator:\n"
                f"  current_rate={current_rate}, new_rate={new_rate}, balance={balance}, "
                f"remaining_term={remaining_term}, funding_fee_exempt={funding_fee_exempt}]"
            )

    if any(kw in q for kw in ("schedule", "book", "appointment", "call for",
                               "monday", "tuesday", "wednesday", "thursday",
                               "friday", "saturday")):
        parts.append(
            "[Scheduling: call the appointment_scheduler tool. "
            "Extract preferred_day and preferred_time from what the Veteran said. "
            "If no specific time was given, use 'morning' or 'afternoon' as appropriate.]"
        )

    return "\n\n" + "\n".join(parts) if parts else ""
