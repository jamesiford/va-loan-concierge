"""
Simulated VA loan appointment scheduler tool.

Accepts a preferred day, time, and optional loan officer name, then returns
a confirmed appointment slot with a reference number. No real calendar API
is called — the confirmation is deterministically generated for demo purposes.
"""

import hashlib
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Loan officers available for scheduling (matches lender_products.md)
LOAN_OFFICERS = {
    "sarah chen": "Sarah Chen",
    "marcus williams": "Marcus Williams",
    "priya patel": "Priya Patel",
    "default": "Sarah Chen",  # fallback when no preference given
}

# Canonical day mapping for flexible input ("thurs" → "Thursday", etc.)
DAY_ALIASES: dict[str, str] = {
    "mon": "Monday", "monday": "Monday",
    "tue": "Tuesday", "tues": "Tuesday", "tuesday": "Tuesday",
    "wed": "Wednesday", "weds": "Wednesday", "wednesday": "Wednesday",
    "thu": "Thursday", "thur": "Thursday", "thurs": "Thursday", "thursday": "Thursday",
    "fri": "Friday", "friday": "Friday",
    "sat": "Saturday", "saturday": "Saturday",
}

# Available appointment slots per day (Saturday is limited)
AVAILABLE_SLOTS: dict[str, list[str]] = {
    "Monday":    ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Tuesday":   ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Wednesday": ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Thursday":  ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM"],
    "Friday":    ["9:00 AM", "10:00 AM", "11:00 AM", "1:00 PM", "2:00 PM", "3:00 PM"],
    "Saturday":  ["9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM"],
}


@dataclass
class AppointmentInput:
    preferred_day: str                   # e.g. "Thursday", "thurs", "Friday"
    preferred_time: str                  # e.g. "2:00 PM", "2pm", "afternoon"
    loan_officer: str = ""               # Optional; defaults to next available
    appointment_type: str = "IRRRL review and rate lock"  # Type of consultation


@dataclass
class AppointmentResult:
    confirmed_day: str                   # e.g. "Thursday"
    confirmed_time: str                  # e.g. "2:00 PM"
    loan_officer: str                    # Assigned officer name
    appointment_type: str                # Type of consultation
    confirmation_number: str             # e.g. "LOAN-84921"
    confirmation_message: str           # Human-readable summary
    calendar_date: str                   # Absolute date, e.g. "Thu Mar 26, 2026"


def _normalize_day(raw: str) -> str:
    """Convert flexible day input to a canonical day name, or raise ValueError."""
    normalized = raw.strip().lower()
    if normalized in DAY_ALIASES:
        return DAY_ALIASES[normalized]
    raise ValueError(
        f"Unrecognized day: '{raw}'. "
        f"Use a day name like Monday, Tuesday, Wednesday, Thursday, Friday, or Saturday."
    )


def _normalize_time(raw: str, available_slots: list[str]) -> str:
    """
    Match a loose time string to the nearest available slot.
    Falls back to the first available slot if no match found.
    """
    raw_lower = raw.strip().lower().replace(" ", "")

    # Direct match first (case-insensitive)
    for slot in available_slots:
        if raw_lower == slot.lower().replace(" ", ""):
            return slot

    # Keyword mapping for vague preferences
    if any(word in raw_lower for word in ("morning", "am", "early")):
        morning = [s for s in available_slots if "AM" in s]
        if morning:
            return morning[0]

    if any(word in raw_lower for word in ("afternoon", "pm", "later")):
        afternoon = [s for s in available_slots if "PM" in s]
        if afternoon:
            return afternoon[0]

    # Hour-only match (e.g. "2pm" → "2:00 PM")
    for slot in available_slots:
        slot_hour = slot.split(":")[0]
        if slot_hour in raw_lower:
            return slot

    # Default: first available slot
    logger.warning("appointment_scheduler: could not match time '%s', using first slot", raw)
    return available_slots[0]


def _next_weekday_date(target_day: str) -> datetime:
    """Return the next calendar occurrence of target_day from today."""
    day_numbers = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
        "Friday": 4, "Saturday": 5, "Sunday": 6,
    }
    today = datetime.now()
    target_num = day_numbers[target_day]
    days_ahead = (target_num - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # schedule next week if today matches
    return today + timedelta(days=days_ahead)


def _confirmation_number(day: str, time: str, officer: str) -> str:
    """Generate a deterministic-looking confirmation number from the booking details."""
    seed = f"{day}-{time}-{officer}"
    digest = hashlib.md5(seed.encode()).hexdigest()  # noqa: S324 — not used for security
    numeric = int(digest[:8], 16) % 90_000 + 10_000  # 5-digit numeric suffix
    return f"LOAN-{numeric}"


def schedule_appointment(inputs: AppointmentInput) -> AppointmentResult:
    """
    Book a simulated VA loan consultation appointment.

    Normalizes the requested day and time, resolves the loan officer,
    and returns a confirmed appointment with a reference number.
    """
    logger.info(
        "appointment_scheduler: requested %s %s with '%s' for %s",
        inputs.preferred_day,
        inputs.preferred_time,
        inputs.loan_officer or "any officer",
        inputs.appointment_type,
    )

    # Resolve day
    confirmed_day = _normalize_day(inputs.preferred_day)

    # Sunday is not available
    if confirmed_day == "Sunday":
        confirmed_day = "Monday"
        logger.info("appointment_scheduler: Sunday unavailable, moved to Monday")

    available = AVAILABLE_SLOTS[confirmed_day]

    # Resolve time
    confirmed_time = _normalize_time(inputs.preferred_time, available)

    # Resolve loan officer
    officer_key = inputs.loan_officer.strip().lower()
    if officer_key and officer_key in LOAN_OFFICERS:
        loan_officer = LOAN_OFFICERS[officer_key]
    elif officer_key:
        # Partial name match
        match = next((v for k, v in LOAN_OFFICERS.items() if officer_key in k), None)
        loan_officer = match or LOAN_OFFICERS["default"]
    else:
        loan_officer = LOAN_OFFICERS["default"]

    # Build confirmation details
    confirmation_number = _confirmation_number(confirmed_day, confirmed_time, loan_officer)
    appt_date = _next_weekday_date(confirmed_day)
    calendar_date = appt_date.strftime("%a %b %d, %Y")

    confirmation_message = (
        f"Your {inputs.appointment_type} is confirmed with {loan_officer} "
        f"on {confirmed_day}, {calendar_date} at {confirmed_time}. "
        f"Reference number: {confirmation_number}. "
        f"You will receive a calendar invite and reminder at the contact info on file."
    )

    result = AppointmentResult(
        confirmed_day=confirmed_day,
        confirmed_time=confirmed_time,
        loan_officer=loan_officer,
        appointment_type=inputs.appointment_type,
        confirmation_number=confirmation_number,
        confirmation_message=confirmation_message,
        calendar_date=calendar_date,
    )

    logger.info(
        "appointment_scheduler: confirmed %s %s with %s — ref %s",
        confirmed_day,
        confirmed_time,
        loan_officer,
        confirmation_number,
    )

    return result
