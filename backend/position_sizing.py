"""
Position Sizing Engine — Institutional Allocation Algorithm
============================================================
Formula (MoS × β-adjusted × coefficient), hard-capped at 10%:

  raw_weight  = min(mos_pct / 100, 1.0) × (1 / max(beta, 0.3)) × BASE_COEF
  recommended = min(raw_weight, MAX_WEIGHT_PER_POSITION)

Rationale:
  - Higher Margin of Safety → larger signal (more undervalued → bigger bet)
  - Lower Beta → larger position (less systematic risk → can size up safely)
  - BASE_COEF = 0.15 calibrates so MoS=50%, β=1.0 → 7.5% weight
  - Hard cap at MAX_WEIGHT_PER_POSITION = 10% (institutional diversification rule)

The result gives:
  MoS=100%, β=0.5  → raw 30%  → capped 10%  (hit limit)
  MoS= 75%, β=0.8  → raw 14%  → capped 10%  (hit limit)
  MoS= 50%, β=1.0  → raw  7.5% → final 7.5%
  MoS= 30%, β=1.5  → raw  3.0% → final 3.0%
  MoS= 20%, β=2.0  → raw  1.5% → final 1.5%
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

BASE_COEF: float = 0.15
MAX_WEIGHT: float = 0.10          # 10% hard cap — institutional rule


@dataclass
class PositionSizingResult:
    ticker: str
    margin_of_safety: float        # % (e.g. 35.2)
    beta: float
    raw_weight_pct: float          # before cap, %
    recommended_weight_pct: float  # after cap, %
    capped_at_limit: bool          # True if raw > MAX_WEIGHT
    capital_to_deploy: float       # € to invest
    shares_to_buy: int             # rounded down (whole shares)
    estimated_cost: float          # shares_to_buy × current_price
    cash_available: float
    cash_sufficient: bool
    shortfall: float               # 0 if cash_sufficient, else gap in €

    # Portfolio capacity (Phase 6)
    portfolio_used_pct: float = 0.0        # % of initial capital already invested
    capacity_remaining_pct: float = 100.0  # % of initial capital still deployable
    max_affordable_shares: int = 0         # max shares buyable with remaining cash

    # Liquidity alert — populated only when cash_sufficient is False
    sell_candidate_ticker: Optional[str] = None
    sell_candidate_mos: Optional[float] = None
    sell_candidate_proceeds: Optional[float] = None
    liquidity_alert: Optional[str] = None


def compute_position_size(
    ticker: str,
    margin_of_safety_pct: float,
    beta: float,
    portfolio_total: float,        # total portfolio value (invested + cash) in €
    cash_available: float,
    current_price: float,
    initial_capital: float = 100_000.0,  # original starting capital (for usage %)
    sell_candidates: Optional[list[dict]] = None,  # [{ticker, live_mos, cost_basis}]
) -> PositionSizingResult:
    """
    Compute recommended position size.

    Parameters
    ----------
    sell_candidates
        Pre-computed list from /api/portfolio/live, sorted by live_mos ascending.
        If provided and cash is insufficient, the first entry becomes the sell recommendation.
    """
    # Guard against degenerate inputs
    mos_clamped = max(margin_of_safety_pct, 0.0)
    beta_safe = max(beta, 0.3)
    pt = max(portfolio_total, cash_available, 1.0)

    # --- Core formula ---
    raw_weight = min(mos_clamped / 100.0, 1.0) * (1.0 / beta_safe) * BASE_COEF
    capped = raw_weight > MAX_WEIGHT
    recommended_weight = min(raw_weight, MAX_WEIGHT)

    # --- Capital & shares ---
    capital_to_deploy = recommended_weight * pt
    shares = int(capital_to_deploy / current_price) if current_price > 0 else 0
    estimated_cost = shares * current_price

    # --- Cash check ---
    sufficient = estimated_cost <= cash_available + 0.01
    shortfall = max(estimated_cost - cash_available, 0.0)

    # --- Portfolio capacity (Phase 6) ---
    invested = max(portfolio_total - cash_available, 0.0)
    ic = max(initial_capital, 1.0)
    used_pct = round(invested / ic * 100, 1)
    remaining_pct = round(100.0 - used_pct, 1)
    max_affordable = int(cash_available / current_price) if current_price > 0 else 0

    # --- Liquidity alert ---
    sell_ticker: Optional[str] = None
    sell_mos: Optional[float] = None
    sell_proceeds: Optional[float] = None
    alert: Optional[str] = None

    if not sufficient and sell_candidates:
        worst = sell_candidates[0]
        sell_ticker = worst["ticker"]
        sell_mos = worst["live_mos"]
        sell_proceeds = worst["cost_basis"]
        alert = (
            f"ALERTA DE LIQUIDEZ: Para comprar {ticker}, se recomienda vender "
            f"{sell_ticker} porque su margen de seguridad se ha reducido al "
            f"{sell_mos:.1f}%. La venta liberaría {sell_proceeds:,.0f}€ en efectivo."
        )

    return PositionSizingResult(
        ticker=ticker,
        margin_of_safety=margin_of_safety_pct,
        beta=beta,
        raw_weight_pct=round(raw_weight * 100, 2),
        recommended_weight_pct=round(recommended_weight * 100, 2),
        capped_at_limit=capped,
        capital_to_deploy=round(capital_to_deploy, 2),
        shares_to_buy=shares,
        estimated_cost=round(estimated_cost, 2),
        cash_available=round(cash_available, 2),
        cash_sufficient=sufficient,
        shortfall=round(shortfall, 2),
        portfolio_used_pct=used_pct,
        capacity_remaining_pct=remaining_pct,
        max_affordable_shares=max_affordable,
        sell_candidate_ticker=sell_ticker,
        sell_candidate_mos=sell_mos,
        sell_candidate_proceeds=sell_proceeds,
        liquidity_alert=alert,
    )
