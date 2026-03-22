"""
VA Loan MCP Server — tool implementations and MCP schema definitions.

This module provides:
  - Plain Python tool functions (called directly by function_app.py)
  - MCP-format tool schemas for the tools/list response
"""

import hashlib
import json
import math
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# refi_savings_calculator
# ---------------------------------------------------------------------------

_IRRRL_FUNDING_FEE_RATE = 0.005
_IRRRL_BASE_CLOSING_COSTS = 4_050.0


def _monthly_payment(principal: float, annual_rate: float, term_years: int) -> float:
    if annual_rate == 0:
        return principal / (term_years * 12)
    r = annual_rate / 100 / 12
    n = term_years * 12
    return principal * (r * math.pow(1 + r, n)) / (math.pow(1 + r, n) - 1)


def refi_savings_calculator(
    current_rate: float,
    new_rate: float,
    balance: float,
    remaining_term: int,
    funding_fee_exempt: bool = False,
) -> dict:
    funding_fee = 0.0 if funding_fee_exempt else balance * _IRRRL_FUNDING_FEE_RATE
    closing_costs = _IRRRL_BASE_CLOSING_COSTS + funding_fee

    current_payment = _monthly_payment(balance, current_rate, remaining_term)
    new_payment = _monthly_payment(balance, new_rate, remaining_term)

    monthly_savings = current_payment - new_payment
    annual_savings = monthly_savings * 12
    lifetime_savings = (monthly_savings * remaining_term * 12) - closing_costs

    if monthly_savings <= 0:
        break_even_months, break_even_years = 9999, 9999.0
    else:
        break_even_months = math.ceil(closing_costs / monthly_savings)
        break_even_years = round(break_even_months / 12, 1)

    return {
        "current_monthly_payment": round(current_payment, 2),
        "new_monthly_payment": round(new_payment, 2),
        "monthly_savings": round(monthly_savings, 2),
        "annual_savings": round(annual_savings, 2),
        "break_even_months": break_even_months,
        "break_even_years": break_even_years,
        "lifetime_savings": round(lifetime_savings, 2),
        "closing_costs": closing_costs,
        "is_beneficial": monthly_savings > 0 and break_even_months <= 36,
    }


# ---------------------------------------------------------------------------
# appointment_scheduler
# ---------------------------------------------------------------------------

_LOAN_OFFICERS = {
    "sarah chen": "Sarah Chen",
    "marcus williams": "Marcus Williams",
    "priya patel": "Priya Patel",
}
_DEFAULT_OFFICER = "Sarah Chen"

_DAY_ALIASES: dict[str, str] = {
    "mon": "Monday", "monday": "Monday",
    "tue": "Tuesday", "tues": "Tuesday", "tuesday": "Tuesday",
    "wed": "Wednesday", "weds": "Wednesday", "wednesday": "Wednesday",
    "thu": "Thursday", "thur": "Thursday", "thurs": "Thursday", "thursday": "Thursday",
    "fri": "Friday", "friday": "Friday",
    "sat": "Saturday", "saturday": "Saturday",
}

_AVAILABLE_SLOTS: dict[str, list[str]] = {
    "Monday":    ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Tuesday":   ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Wednesday": ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Thursday":  ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Friday":    ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM"],
    "Saturday":  ["9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM"],
}


def _normalize_day(raw: str) -> str:
    key = raw.strip().lower()
    if key in _DAY_ALIASES:
        return _DAY_ALIASES[key]
    raise ValueError(f"Unrecognized day: '{raw}'")


def _normalize_time(raw: str, slots: list[str]) -> str:
    cleaned = raw.strip().lower().replace(" ", "")
    for slot in slots:
        if cleaned == slot.lower().replace(" ", ""):
            return slot
    if any(w in cleaned for w in ("morning", "am", "early")):
        am = [s for s in slots if "AM" in s]
        if am:
            return am[0]
    if any(w in cleaned for w in ("afternoon", "pm", "later")):
        pm = [s for s in slots if "PM" in s]
        if pm:
            return pm[0]
    for slot in slots:
        if slot.split(":")[0] in cleaned:
            return slot
    return slots[0]


def _next_weekday_date(target_day: str) -> datetime:
    day_numbers = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
        "Friday": 4, "Saturday": 5, "Sunday": 6,
    }
    today = datetime.now()
    days_ahead = (day_numbers[target_day] - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def _confirmation_number(day: str, time: str, officer: str) -> str:
    seed = f"{day}-{time}-{officer}"
    digest = hashlib.md5(seed.encode()).hexdigest()  # noqa: S324
    return f"LOAN-{int(digest[:8], 16) % 90_000 + 10_000}"


def appointment_scheduler(
    preferred_day: str,
    preferred_time: str,
    loan_officer: str = "",
    appointment_type: str = "VA Loan Consultation",
    **_extra,
) -> dict:
    confirmed_day = _normalize_day(preferred_day)
    available = _AVAILABLE_SLOTS[confirmed_day]
    confirmed_time = _normalize_time(preferred_time, available)

    key = loan_officer.strip().lower()
    if key in _LOAN_OFFICERS:
        officer = _LOAN_OFFICERS[key]
    elif key:
        officer = next((v for k, v in _LOAN_OFFICERS.items() if key in k), _DEFAULT_OFFICER)
    else:
        officer = _DEFAULT_OFFICER

    confirmation_number = _confirmation_number(confirmed_day, confirmed_time, officer)
    calendar_date = _next_weekday_date(confirmed_day).strftime("%a %b %d, %Y")

    return {
        "confirmed_day": confirmed_day,
        "confirmed_time": confirmed_time,
        "loan_officer": officer,
        "appointment_type": appointment_type,
        "confirmation_number": confirmation_number,
        "calendar_date": calendar_date,
        "confirmation_message": (
            f"Your {appointment_type} is confirmed with {officer} "
            f"on {confirmed_day}, {calendar_date} at {confirmed_time}. "
            f"Reference number: {confirmation_number}. "
            f"You will receive a calendar invite and reminder at the contact info on file."
        ),
    }


# ---------------------------------------------------------------------------
# MCP tool schemas — returned by tools/list
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "refi_savings_calculator",
        "description": (
            "Calculate VA IRRRL refinance savings. Returns monthly savings, annual savings, "
            "lifetime savings, break-even timeline, closing costs, and whether the VA net "
            "tangible benefit test passes (break-even must be 36 months or fewer)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "current_rate": {
                    "type": "number",
                    "description": "Annual interest rate on the existing loan (e.g. 6.8 for 6.8%).",
                },
                "new_rate": {
                    "type": "number",
                    "description": "Annual interest rate on the new loan (e.g. 6.1 for 6.1%).",
                },
                "balance": {
                    "type": "number",
                    "description": "Current outstanding loan balance in dollars.",
                },
                "remaining_term": {
                    "type": "integer",
                    "description": "Remaining term on the existing loan in years.",
                },
                "funding_fee_exempt": {
                    "type": "boolean",
                    "description": "True if the Veteran is exempt from the IRRRL funding fee.",
                },
            },
            "required": ["current_rate", "new_rate", "balance", "remaining_term"],
        },
    },
    {
        "name": "appointment_scheduler",
        "description": (
            "Schedule a VA loan consultation appointment. Returns a confirmed appointment "
            "slot with a reference number, assigned loan officer, and calendar date."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "preferred_day": {
                    "type": "string",
                    "description": "Preferred day of the week (e.g. 'Thursday', 'Friday').",
                },
                "preferred_time": {
                    "type": "string",
                    "description": "Preferred time (e.g. '2:00 PM', 'morning', 'afternoon').",
                },
                "loan_officer": {
                    "type": "string",
                    "description": "Preferred loan officer name (optional).",
                },
                "appointment_type": {
                    "type": "string",
                    "description": "Type of consultation (defaults to 'VA Loan Consultation').",
                },
            },
            "required": ["preferred_day", "preferred_time"],
        },
    },
]
