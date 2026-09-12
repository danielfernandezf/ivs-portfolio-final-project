"""
Quality & Survival Engine — Phase 5 (Small/Mid Cap Filter)
============================================================
Computes institutional-grade solvency and quality metrics to filter out
distressed or low-quality companies before capital deployment.

Metrics implemented:
  ─ Altman Z-Score (1968 public-company variant)
      Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5
      Zones: Z > 2.99 → Safe · 1.81–2.99 → Grey · Z < 1.81 → Distress

  ─ Piotroski F-Score (2000)
      Nine binary signals across profitability, leverage, and efficiency.
      Score 0–3 → Weak · 4–6 → Average · 7–9 → Strong

  ─ Sector benchmark multiples (hardcoded sector averages)
      P/E and EV/EBITDA company vs. sector median

  ─ Liquidity alert
      If a 10%-of-portfolio position would exceed 5% of the stock's 10-day
      average volume, warn that the order would move the price.

Override rule:
  Z-Score in DISTRESS zone  → force verdict to SELL/AVOID
  F-Score < 5               → force verdict to SELL/AVOID
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger("quality-engine")

# ---------------------------------------------------------------------------
# Sector benchmark multiples (S&P 500 sector medians, 2024 approximation)
# ---------------------------------------------------------------------------

SECTOR_BENCHMARKS: dict[str, dict[str, float]] = {
    "Technology":              {"pe": 28.5, "ev_ebitda": 22.1},
    "Healthcare":              {"pe": 22.3, "ev_ebitda": 17.8},
    "Financial Services":      {"pe": 13.2, "ev_ebitda": 10.5},
    "Consumer Cyclical":       {"pe": 19.4, "ev_ebitda": 12.8},
    "Consumer Defensive":      {"pe": 21.8, "ev_ebitda": 14.6},
    "Energy":                  {"pe": 11.8, "ev_ebitda":  6.9},
    "Industrials":             {"pe": 22.1, "ev_ebitda": 14.3},
    "Basic Materials":         {"pe": 15.2, "ev_ebitda":  9.1},
    "Real Estate":             {"pe": 35.8, "ev_ebitda": 19.2},
    "Utilities":               {"pe": 18.6, "ev_ebitda": 11.4},
    "Communication Services":  {"pe": 16.8, "ev_ebitda": 10.9},
}
_DEFAULT_BENCHMARK: dict[str, float] = {"pe": 18.5, "ev_ebitda": 13.2}

ALTMAN_DISTRESS_THRESHOLD = 1.81
ALTMAN_SAFE_THRESHOLD     = 2.99
PIOTROSKI_WEAK_THRESHOLD  = 5     # < 5 → override to SELL/AVOID
LIQUIDITY_IMPACT_MAX_PCT  = 5.0   # alert if position > 5 % of daily volume
PORTFOLIO_SIZE_EUR        = 100_000.0
MAX_POSITION_WEIGHT       = 0.10  # 10 %


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AltmanZScore:
    z_score: float
    zone: str                    # "SAFE" | "GREY" | "DISTRESS"
    x1_wc_to_assets: float       # Working Capital / Total Assets
    x2_re_to_assets: float       # Retained Earnings / Total Assets
    x3_ebit_to_assets: float     # EBIT / Total Assets
    x4_mktcap_to_liab: float     # Market Cap / Total Liabilities
    x5_rev_to_assets: float      # Revenue / Total Assets
    triggers_override: bool
    note: str = ""               # e.g. "N/A for financials"


@dataclass
class PiotroskiScore:
    score: int                   # 0–9
    f1_roa_positive: bool
    f2_ocf_positive: bool
    f3_roa_improving: bool
    f4_accruals_quality: bool    # OCF/Assets > ROA
    f5_leverage_improving: bool
    f6_liquidity_improving: bool
    f7_no_dilution: bool
    f8_gross_margin_improving: bool
    f9_asset_turnover_improving: bool
    triggers_override: bool
    signals_computed: int        # how many of 9 we actually measured


@dataclass
class SectorBenchmark:
    pe_ratio: Optional[float]
    ev_ebitda: Optional[float]
    sector_pe: float
    sector_ev_ebitda: float
    pe_vs_sector_pct: Optional[float]     # (company/sector − 1) × 100
    ev_ebitda_vs_sector_pct: Optional[float]


@dataclass
class LiquidityAlert:
    avg_volume_10d: int
    max_shares_in_position: int  # shares at 10% of 100K portfolio
    volume_impact_pct: float     # max_shares / avg_volume × 100
    alert: Optional[str]         # non-None when volume_impact_pct > 5%


@dataclass
class QualityMetrics:
    ticker: str
    altman: AltmanZScore
    piotroski: PiotroskiScore
    benchmark: SectorBenchmark
    liquidity: LiquidityAlert
    verdict_override: bool
    override_reason: Optional[str]


# ---------------------------------------------------------------------------
# yfinance extraction helpers
# ---------------------------------------------------------------------------

def _sf(val: Any, default: float = 0.0) -> float:
    """Safe float conversion."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _row_value(df: Optional[pd.DataFrame], *keywords: str, col: int = 0) -> Optional[float]:
    """
    Find the first row in `df` whose index label contains ALL keywords
    (case-insensitive) and return the value at column `col`.
    Falls back to matching any single keyword if no multi-keyword match.
    """
    if df is None or df.empty:
        return None

    # Exact multi-keyword match first
    for idx in df.index:
        label = str(idx).lower()
        if all(kw.lower() in label for kw in keywords):
            try:
                vals = df.loc[idx].dropna()
                if len(vals) > col:
                    v = float(vals.iloc[col])
                    return v if math.isfinite(v) else None
            except Exception:
                continue

    # Fallback: first keyword only
    if len(keywords) > 1:
        for idx in df.index:
            if keywords[0].lower() in str(idx).lower():
                try:
                    vals = df.loc[idx].dropna()
                    if len(vals) > col:
                        v = float(vals.iloc[col])
                        return v if math.isfinite(v) else None
                except Exception:
                    continue
    return None


# ---------------------------------------------------------------------------
# Altman Z-Score
# ---------------------------------------------------------------------------

def _compute_altman(
    info: dict,
    balance_sheet: Optional[pd.DataFrame],
    financials: Optional[pd.DataFrame],
    market_cap: float,
    sector: str,
) -> AltmanZScore:
    """
    Altman Z-Score (1968) for publicly traded companies.
    Not meaningful for financial companies — returns N/A in that case.
    """
    # Financial companies have fundamentally different balance sheets
    _financial_sectors = {"financial services", "banks", "insurance", "financial"}
    if any(fs in sector.lower() for fs in _financial_sectors):
        return AltmanZScore(
            z_score=0.0, zone="N/A",
            x1_wc_to_assets=0, x2_re_to_assets=0,
            x3_ebit_to_assets=0, x4_mktcap_to_liab=0, x5_rev_to_assets=0,
            triggers_override=False,
            note="Z-Score not applicable to financial sector companies.",
        )

    # ── Gather inputs ──────────────────────────────────────────────────────
    # Total Assets
    total_assets = (
        _row_value(balance_sheet, "total assets")
        or _sf(info.get("totalAssets"))
        or 0.0
    )

    # Working Capital = Current Assets − Current Liabilities
    curr_assets = (
        _row_value(balance_sheet, "current assets")
        or _sf(info.get("totalCurrentAssets"))
        or 0.0
    )
    curr_liab = (
        _row_value(balance_sheet, "current liabilities")
        or _sf(info.get("totalCurrentLiabilities"))
        or 0.0
    )
    working_capital = curr_assets - curr_liab

    # Retained Earnings
    retained_earnings = (
        _row_value(balance_sheet, "retained earnings")
        or _sf(info.get("retainedEarnings"))
        or 0.0
    )

    # EBIT — try financials first, then info-derived EBITDA
    ebit = (
        _row_value(financials, "ebit")
        or _row_value(financials, "operating income")
        or _sf(info.get("ebit"))
        or (_sf(info.get("ebitda")) * 0.8)   # rough proxy: EBIT ≈ 80% EBITDA
        or 0.0
    )

    # Total Liabilities
    total_liab = (
        _row_value(balance_sheet, "total liabilities")
        or (_sf(info.get("totalDebt")) + curr_liab)   # approximation
        or 0.0
    )

    # Revenue
    revenue = (
        _row_value(financials, "total revenue")
        or _row_value(financials, "revenue")
        or _sf(info.get("totalRevenue"))
        or 0.0
    )

    if total_assets <= 0:
        return AltmanZScore(
            z_score=0.0, zone="N/A",
            x1_wc_to_assets=0, x2_re_to_assets=0,
            x3_ebit_to_assets=0, x4_mktcap_to_liab=0, x5_rev_to_assets=0,
            triggers_override=False,
            note="Insufficient balance sheet data to compute Z-Score.",
        )

    # ── Z-Score calculation ────────────────────────────────────────────────
    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = market_cap / total_liab if total_liab > 0 else 0.0
    x5 = revenue / total_assets

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

    if z > ALTMAN_SAFE_THRESHOLD:
        zone = "SAFE"
    elif z >= ALTMAN_DISTRESS_THRESHOLD:
        zone = "GREY"
    else:
        zone = "DISTRESS"

    return AltmanZScore(
        z_score=round(z, 3),
        zone=zone,
        x1_wc_to_assets=round(x1, 4),
        x2_re_to_assets=round(x2, 4),
        x3_ebit_to_assets=round(x3, 4),
        x4_mktcap_to_liab=round(x4, 4),
        x5_rev_to_assets=round(x5, 4),
        triggers_override=(zone == "DISTRESS"),
    )


# ---------------------------------------------------------------------------
# Piotroski F-Score
# ---------------------------------------------------------------------------

def _compute_piotroski(
    info: dict,
    balance_sheet: Optional[pd.DataFrame],
    financials: Optional[pd.DataFrame],
    cashflow: Optional[pd.DataFrame],
) -> PiotroskiScore:
    """
    Piotroski (2000) F-Score: 9 binary indicators.
    Uses current year (col 0) and prior year (col 1) from financial statements.
    Unavailable signals default to False (no credit) and are flagged in `signals_computed`.
    """
    signals_computed = 0

    def _bs(col: int, *kw) -> Optional[float]:
        return _row_value(balance_sheet, *kw, col=col)

    def _fin(col: int, *kw) -> Optional[float]:
        return _row_value(financials, *kw, col=col)

    def _cf(col: int, *kw) -> Optional[float]:
        return _row_value(cashflow, *kw, col=col)

    # ── Profitability signals ──────────────────────────────────────────────

    # F1: ROA > 0  (Net Income / Total Assets)
    f1 = False
    roa_cur = _sf(info.get("returnOnAssets"))
    net_income_cur = _fin(0, "net income") or _sf(info.get("netIncomeToCommon"))
    total_assets_cur = _bs(0, "total assets") or _sf(info.get("totalAssets"))
    if roa_cur != 0:
        f1 = roa_cur > 0
        signals_computed += 1
    elif net_income_cur is not None and total_assets_cur and total_assets_cur > 0:
        f1 = (net_income_cur / total_assets_cur) > 0
        signals_computed += 1
        roa_cur = net_income_cur / total_assets_cur

    # F2: Operating Cash Flow > 0
    f2 = False
    ocf_cur = _cf(0, "operating") or _sf(info.get("operatingCashflow"))
    if ocf_cur is not None:
        f2 = ocf_cur > 0
        signals_computed += 1

    # F3: ROA improving YoY
    f3 = False
    net_income_prior = _fin(1, "net income")
    total_assets_prior = _bs(1, "total assets")
    if (net_income_cur is not None and total_assets_cur and total_assets_cur > 0
            and net_income_prior is not None and total_assets_prior and total_assets_prior > 0):
        roa_prior = net_income_prior / total_assets_prior
        roa_curr_calc = net_income_cur / total_assets_cur
        f3 = roa_curr_calc > roa_prior
        signals_computed += 1

    # F4: Accruals — OCF/Assets > ROA
    f4 = False
    if (ocf_cur is not None and total_assets_cur and total_assets_cur > 0
            and net_income_cur is not None):
        ocf_ratio = ocf_cur / total_assets_cur
        roa_calc = net_income_cur / total_assets_cur if total_assets_cur > 0 else 0
        f4 = ocf_ratio > roa_calc
        signals_computed += 1

    # ── Leverage / Liquidity signals ───────────────────────────────────────

    # F5: Long-term leverage ratio decreasing
    f5 = False
    ltd_cur = _bs(0, "long term debt") or _sf(info.get("longTermDebt"))
    ltd_prior = _bs(1, "long term debt")
    if (ltd_cur is not None and total_assets_cur and total_assets_cur > 0
            and ltd_prior is not None and total_assets_prior and total_assets_prior > 0):
        lev_cur = ltd_cur / total_assets_cur
        lev_prior = ltd_prior / total_assets_prior
        f5 = lev_cur < lev_prior
        signals_computed += 1

    # F6: Current ratio improving
    f6 = False
    cr_cur = _sf(info.get("currentRatio"))
    curr_assets_prior = _bs(1, "current assets")
    curr_liab_prior = _bs(1, "current liabilities")
    cr_prior = None
    if curr_assets_prior and curr_liab_prior and curr_liab_prior > 0:
        cr_prior = curr_assets_prior / curr_liab_prior
    if cr_cur and cr_prior is not None:
        f6 = cr_cur > cr_prior
        signals_computed += 1
    elif cr_cur != 0:
        # Can only check current value — give credit if CR > 1.5 (healthy)
        f6 = cr_cur > 1.5
        signals_computed += 1

    # F7: No share dilution (shares outstanding not increased)
    f7 = False
    shares_cur = _sf(info.get("sharesOutstanding")) or _sf(info.get("impliedSharesOutstanding"))
    # Try to get prior year shares from balance_sheet
    shares_prior_bs = _bs(1, "ordinary shares", "number") or _bs(1, "common stock")
    shares_cur_bs = _bs(0, "ordinary shares", "number") or _bs(0, "common stock")
    if shares_cur_bs and shares_prior_bs and shares_prior_bs > 0:
        f7 = shares_cur_bs <= shares_prior_bs * 1.01   # 1% tolerance
        signals_computed += 1
    elif shares_cur != 0:
        # No prior year data — can't determine dilution; skip (False, not counted)
        pass

    # ── Operating efficiency signals ───────────────────────────────────────

    # F8: Gross margin improving
    f8 = False
    gm_cur = _sf(info.get("grossMargins"))
    gross_profit_cur = _fin(0, "gross profit")
    rev_cur = _fin(0, "total revenue") or _fin(0, "revenue")
    gross_profit_prior = _fin(1, "gross profit")
    rev_prior = _fin(1, "total revenue") or _fin(1, "revenue")
    if (gross_profit_cur and rev_cur and rev_cur > 0
            and gross_profit_prior and rev_prior and rev_prior > 0):
        gm_c = gross_profit_cur / rev_cur
        gm_p = gross_profit_prior / rev_prior
        f8 = gm_c > gm_p
        signals_computed += 1
    elif gm_cur != 0:
        # No YoY data — give credit if margin > 30% (decent quality)
        f8 = gm_cur > 0.30
        signals_computed += 1

    # F9: Asset turnover improving (Revenue / Total Assets)
    f9 = False
    if (rev_cur and total_assets_cur and total_assets_cur > 0
            and rev_prior and total_assets_prior and total_assets_prior > 0):
        at_c = rev_cur / total_assets_cur
        at_p = rev_prior / total_assets_prior
        f9 = at_c > at_p
        signals_computed += 1

    score = sum([f1, f2, f3, f4, f5, f6, f7, f8, f9])

    return PiotroskiScore(
        score=score,
        f1_roa_positive=f1,
        f2_ocf_positive=f2,
        f3_roa_improving=f3,
        f4_accruals_quality=f4,
        f5_leverage_improving=f5,
        f6_liquidity_improving=f6,
        f7_no_dilution=f7,
        f8_gross_margin_improving=f8,
        f9_asset_turnover_improving=f9,
        triggers_override=(score < PIOTROSKI_WEAK_THRESHOLD),
        signals_computed=signals_computed,
    )


# ---------------------------------------------------------------------------
# Sector benchmarks
# ---------------------------------------------------------------------------

def _compute_benchmark(info: dict, sector: str) -> SectorBenchmark:
    bench = SECTOR_BENCHMARKS.get(sector, _DEFAULT_BENCHMARK)

    pe = _sf(info.get("trailingPE")) or _sf(info.get("forwardPE")) or None
    if pe == 0.0:
        pe = None

    ev_ebitda_raw = _sf(info.get("enterpriseToEbitda")) or None
    if ev_ebitda_raw == 0.0:
        ev_ebitda_raw = None

    pe_vs = ((pe / bench["pe"]) - 1) * 100 if pe else None
    ev_vs = ((ev_ebitda_raw / bench["ev_ebitda"]) - 1) * 100 if ev_ebitda_raw else None

    return SectorBenchmark(
        pe_ratio=round(pe, 1) if pe else None,
        ev_ebitda=round(ev_ebitda_raw, 1) if ev_ebitda_raw else None,
        sector_pe=bench["pe"],
        sector_ev_ebitda=bench["ev_ebitda"],
        pe_vs_sector_pct=round(pe_vs, 1) if pe_vs is not None else None,
        ev_ebitda_vs_sector_pct=round(ev_vs, 1) if ev_vs is not None else None,
    )


# ---------------------------------------------------------------------------
# Liquidity check
# ---------------------------------------------------------------------------

def _compute_liquidity(info: dict, current_price: float) -> LiquidityAlert:
    avg_vol = int(_sf(info.get("averageVolume10days") or info.get("averageVolume"), 0))
    if avg_vol <= 0:
        avg_vol = int(_sf(info.get("regularMarketVolume"), 100_000))

    max_capital = PORTFOLIO_SIZE_EUR * MAX_POSITION_WEIGHT
    max_shares = int(max_capital / current_price) if current_price > 0 else 0

    impact_pct = (max_shares / avg_vol * 100) if avg_vol > 0 else 0.0

    alert: Optional[str] = None
    if impact_pct > LIQUIDITY_IMPACT_MAX_PCT:
        alert = (
            f"ALERTA DE LIQUIDEZ: La posición máxima recomendada "
            f"({max_shares:,} acciones) representa el {impact_pct:.1f}% del "
            f"volumen diario medio ({avg_vol:,} acc/día). "
            f"Operación difícil de ejecutar sin mover el precio."
        )

    return LiquidityAlert(
        avg_volume_10d=avg_vol,
        max_shares_in_position=max_shares,
        volume_impact_pct=round(impact_pct, 2),
        alert=alert,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_quality_metrics(ticker_symbol: str, current_price: float, market_cap: float) -> QualityMetrics:
    """
    Download fresh financial data for `ticker_symbol` and compute all
    Phase 5 quality metrics.  Returns a QualityMetrics instance.

    Designed to be called inside a try/except in main.py so that a yfinance
    failure degrades gracefully without crashing the main valuation response.
    """
    ticker_symbol = ticker_symbol.upper().strip()
    tk = yf.Ticker(ticker_symbol)

    try:
        info = tk.info
    except Exception:
        info = {}

    try:
        balance_sheet = tk.balance_sheet
        if balance_sheet is not None and balance_sheet.empty:
            balance_sheet = None
    except Exception:
        balance_sheet = None

    try:
        financials = tk.financials
        if financials is not None and financials.empty:
            financials = None
    except Exception:
        financials = None

    try:
        cashflow = tk.cashflow
        if cashflow is not None and cashflow.empty:
            cashflow = None
    except Exception:
        cashflow = None

    sector = info.get("sector", "N/A")

    altman = _compute_altman(info, balance_sheet, financials, market_cap, sector)
    piotroski = _compute_piotroski(info, balance_sheet, financials, cashflow)
    benchmark = _compute_benchmark(info, sector)
    liquidity = _compute_liquidity(info, current_price)

    # ── Determine override ─────────────────────────────────────────────────
    reasons: list[str] = []
    if altman.triggers_override:
        reasons.append(
            f"Altman Z-Score = {altman.z_score:.2f} — ZONA DE PELIGRO "
            f"(umbral: {ALTMAN_DISTRESS_THRESHOLD}). Riesgo elevado de insolvencia."
        )
    if piotroski.triggers_override:
        reasons.append(
            f"Piotroski F-Score = {piotroski.score}/9 — CALIDAD DÉBIL "
            f"(umbral: {PIOTROSKI_WEAK_THRESHOLD}). Señales de deterioro financiero."
        )

    override = bool(reasons)
    override_reason = " | ".join(reasons) if reasons else None

    return QualityMetrics(
        ticker=ticker_symbol,
        altman=altman,
        piotroski=piotroski,
        benchmark=benchmark,
        liquidity=liquidity,
        verdict_override=override,
        override_reason=override_reason,
    )
