"""
Simulated VA refinance savings calculator tool.

Returns monthly savings, annual savings, and break-even timeline
for a VA IRRRL or cash-out refinance scenario. No real API calls —
values are computed from standard mortgage math.
"""

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# IRRRL funding fee rate (0.50% of loan amount) — waived for exempt Veterans
IRRRL_FUNDING_FEE_RATE = 0.005

# Base IRRRL closing costs excluding the funding fee (origination + title + recording + prepaids)
IRRRL_BASE_CLOSING_COSTS = 4_050.0


@dataclass
class RefiCalculatorInput:
    current_rate: float           # Annual interest rate on existing loan (e.g. 6.8 for 6.8%)
    new_rate: float               # Annual interest rate on new loan (e.g. 6.1 for 6.1%)
    balance: float                # Current outstanding loan balance in dollars
    remaining_term: int           # Remaining term on existing loan in years
    funding_fee_exempt: bool = False  # True if Veteran is exempt (service-connected disability, Purple Heart, etc.)
    closing_costs: float = 0.0    # Override total closing costs; 0 = auto-calculate from balance and exemption status

    def effective_closing_costs(self) -> float:
        """
        Return the closing costs used for break-even calculation.

        If closing_costs is explicitly set (> 0), use it as-is.
        Otherwise, auto-calculate: base costs + funding fee (unless exempt).
        """
        if self.closing_costs > 0:
            return self.closing_costs
        funding_fee = 0.0 if self.funding_fee_exempt else self.balance * IRRRL_FUNDING_FEE_RATE
        return IRRRL_BASE_CLOSING_COSTS + funding_fee


@dataclass
class RefiCalculatorResult:
    current_monthly_payment: float   # P&I payment on existing loan
    new_monthly_payment: float       # P&I payment on new loan
    monthly_savings: float           # Reduction in monthly payment
    annual_savings: float            # monthly_savings × 12
    break_even_months: int           # Months to recoup closing costs
    break_even_years: float          # break_even_months / 12 (rounded to 1 decimal)
    lifetime_savings: float          # Total savings over remaining term
    closing_costs: float             # Closing costs used in break-even calculation
    is_beneficial: bool              # True if break-even ≤ 36 months (VA net tangible benefit)


def _monthly_payment(principal: float, annual_rate: float, term_years: int) -> float:
    """Standard amortizing mortgage payment formula."""
    if annual_rate == 0:
        return principal / (term_years * 12)
    r = annual_rate / 100 / 12          # monthly rate as decimal
    n = term_years * 12                 # total number of payments
    return principal * (r * math.pow(1 + r, n)) / (math.pow(1 + r, n) - 1)


def calculate_refi_savings(inputs: RefiCalculatorInput) -> RefiCalculatorResult:
    """
    Compute the financial impact of refinancing from one rate to another.

    Uses standard amortizing mortgage math. The new loan is assumed to have
    the same remaining term as the existing loan (standard for IRRRL).
    """
    closing_costs = inputs.effective_closing_costs()

    logger.info(
        "refi_calculator: balance=$%.0f, %s%% → %s%%, term=%dyr, costs=$%.0f (exempt=%s)",
        inputs.balance,
        inputs.current_rate,
        inputs.new_rate,
        inputs.remaining_term,
        closing_costs,
        inputs.funding_fee_exempt,
    )

    current_payment = _monthly_payment(inputs.balance, inputs.current_rate, inputs.remaining_term)
    new_payment = _monthly_payment(inputs.balance, inputs.new_rate, inputs.remaining_term)

    monthly_savings = current_payment - new_payment
    annual_savings = monthly_savings * 12
    total_months = inputs.remaining_term * 12
    lifetime_savings = (monthly_savings * total_months) - closing_costs

    if monthly_savings <= 0:
        break_even_months = 9999
        break_even_years = 9999.0
    else:
        break_even_months = math.ceil(closing_costs / monthly_savings)
        break_even_years = round(break_even_months / 12, 1)

    # VA net tangible benefit test: recoupment must be ≤ 36 months
    is_beneficial = monthly_savings > 0 and break_even_months <= 36

    result = RefiCalculatorResult(
        current_monthly_payment=round(current_payment, 2),
        new_monthly_payment=round(new_payment, 2),
        monthly_savings=round(monthly_savings, 2),
        annual_savings=round(annual_savings, 2),
        break_even_months=break_even_months,
        break_even_years=break_even_years,
        lifetime_savings=round(lifetime_savings, 2),
        closing_costs=closing_costs,
        is_beneficial=is_beneficial,
    )

    logger.info(
        "refi_calculator: monthly_savings=$%.2f, break_even=%d months, beneficial=%s",
        result.monthly_savings,
        result.break_even_months,
        result.is_beneficial,
    )

    return result
