"""
Monte Carlo DCF Engine — Phase 4 (Quant Engine)
=================================================
Runs N vectorised iterations of the DCF model with stochastic inputs,
sampling Growth Rate and WACC from empirically-calibrated normal distributions.

Mathematical basis:
  σ_growth = std dev of year-over-year FCF growth rates (historical company data)
  σ_wacc   = β × σ_mkt × ERP   (beta uncertainty propagated into WACC)

  Each iteration i:
    g_i    ~ N(μ_g,    σ_g)     → clipped to [-30%, +60%]
    wacc_i ~ N(μ_wacc, σ_wacc)  → clipped to [max(g_terminal+0.5%, 3%), 25%]
    Intrinsic_i = full DCF(g_i, wacc_i)

Outputs: percentiles (P10/P25/P50/P75/P90), histogram bins for the bell
         curve chart, and P(intrinsic > market price).

Vectorised with NumPy — 10 000 iterations completes in < 100 ms.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats as scipy_stats

from valuation_engine import DCFAssumptions, MarketInputs, ValuationEngine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_ITERATIONS = 10_000
N_BINS = 60

_engine = ValuationEngine()


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MonteCarloResult:
    ticker: str
    current_price: float
    iterations: int          # usable simulations after outlier removal

    # Percentile intrinsic prices
    p10: float
    p25: float
    p50: float               # median
    p75: float
    p90: float

    mean: float
    std: float

    # Probability intrinsic > current market price  (0–1 fraction)
    probability_above_market: float

    # Histogram bins for the frontend chart
    histogram: list[dict]    # [{price_mid, count, density, normal_density}]

    # Input parameters used (for display in the UI)
    growth_mean_pct: float   # μ_g in %
    growth_std_pct: float    # σ_g in %
    wacc_mean_pct: float     # μ_wacc in %
    wacc_std_pct: float      # σ_wacc in %

    # KS-test quality metric (goodness-of-fit to normal)
    ks_statistic: float
    ks_pvalue: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fcf_growth_std(fcf_history: list[float]) -> float:
    """
    Std dev of year-over-year FCF growth rates from company's own history.
    Floor at 5% (floor ensures meaningful uncertainty even for stable earners).
    Cap at 40% (prevents unrealistic noise for volatile start-ups).
    """
    clean = [v for v in fcf_history if v is not None and v != 0]
    if len(clean) < 2:
        return 0.12   # default: 12% if insufficient history

    rates = []
    for i in range(1, len(clean)):
        if clean[i - 1] != 0:
            rates.append((clean[i] - clean[i - 1]) / abs(clean[i - 1]))

    if not rates:
        return 0.12

    return float(np.clip(np.std(rates), 0.05, 0.40))


def _compute_base_wacc(inputs: MarketInputs) -> float:
    """Replicate ValuationEngine.compute_wacc without creating a full result."""
    r_e = inputs.risk_free_rate + inputs.beta * inputs.market_risk_premium
    total_cap = inputs.market_cap + inputs.total_debt
    if total_cap <= 0:
        return r_e
    e_w = inputs.market_cap / total_cap
    d_w = inputs.total_debt / total_cap
    cod_at = inputs.cost_of_debt_pretax * (1 - inputs.effective_tax_rate)
    return e_w * r_e + d_w * cod_at


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def run_montecarlo(
    inputs: MarketInputs,
    base_assumptions: DCFAssumptions,
    n_iterations: int = N_ITERATIONS,
) -> MonteCarloResult:
    """
    Simulate `n_iterations` DCF valuations with stochastic Growth and WACC.

    The full computation is vectorised — no Python loop over iterations.
    Outliers beyond 10× the median are removed before statistics are computed.
    """
    # ── Baseline parameters ──────────────────────────────────────────────────
    mu_g = base_assumptions.revenue_growth_rate
    sigma_g = _fcf_growth_std(inputs.fcf_history)

    mu_wacc = (
        base_assumptions.wacc_override
        if base_assumptions.wacc_override is not None
        else _compute_base_wacc(inputs)
    )
    # WACC uncertainty ~ beta × annual_mkt_vol × ERP
    # Typical result: β=1.0, σ_mkt=15%, ERP=5.5% → σ_wacc ≈ 82 bps
    sigma_wacc = float(
        np.clip(inputs.beta * 0.15 * inputs.market_risk_premium, 0.005, 0.030)
    )

    terminal_g = base_assumptions.terminal_growth_rate
    years = base_assumptions.projection_years

    # ── Sample from normal distributions (reproducible seed) ─────────────────
    rng = np.random.default_rng(seed=42)
    g_vec = rng.normal(mu_g, sigma_g, n_iterations)
    w_vec = rng.normal(mu_wacc, sigma_wacc, n_iterations)

    # Economically valid bounds
    g_vec = np.clip(g_vec, -0.30, 0.60)
    w_min = max(terminal_g + 0.005, 0.03)
    w_vec = np.clip(w_vec, w_min, 0.25)

    # ── Vectorised DCF ────────────────────────────────────────────────────────
    clean = [v for v in inputs.fcf_history if v is not None]
    base_fcf = float(clean[-1]) if clean else 0.0
    net_debt = inputs.total_debt - inputs.cash_and_equivalents
    shares = max(inputs.shares_outstanding, 1.0)

    t = np.arange(1, years + 1, dtype=float)   # shape (years,)

    # FCF projections:  shape (N, years)
    fcf_matrix = base_fcf * (1 + g_vec[:, None]) ** t[None, :]

    # Discount factor:  shape (N, years)
    discount = (1 + w_vec[:, None]) ** t[None, :]

    # Sum of PV(FCFs):  shape (N,)
    pv_sum = np.sum(fcf_matrix / discount, axis=1)

    # Terminal values:  shape (N,)
    spread = np.maximum(w_vec - terminal_g, 0.001)
    tv = fcf_matrix[:, -1] * (1 + terminal_g) / spread
    pv_tv = tv / (1 + w_vec) ** years

    # Enterprise → Equity → Per-share price:  shape (N,)
    prices = (pv_sum + pv_tv - net_debt) / shares

    # ── Outlier removal ───────────────────────────────────────────────────────
    prices = prices[np.isfinite(prices)]
    prices = prices[prices > 0]
    if len(prices) < 10:
        # Degenerate case — return point estimate with dummy distribution
        prices = np.full(10, inputs.current_price)
    median_raw = float(np.median(prices))
    prices = prices[prices < median_raw * 10]   # drop extreme upside outliers

    # ── Summary statistics ────────────────────────────────────────────────────
    p10 = float(np.percentile(prices, 10))
    p25 = float(np.percentile(prices, 25))
    p50 = float(np.percentile(prices, 50))
    p75 = float(np.percentile(prices, 75))
    p90 = float(np.percentile(prices, 90))
    mean = float(np.mean(prices))
    std = float(np.std(prices))
    prob_above = float(np.mean(prices > inputs.current_price))

    # ── KS goodness-of-fit (scipy.stats) ─────────────────────────────────────
    ks_stat, ks_pval = scipy_stats.kstest(prices, "norm", args=(mean, std))

    # ── Histogram + normal density overlay ───────────────────────────────────
    lo = max(0.0, p10 - std * 0.5)
    hi = p90 + std * 0.5
    counts, edges = np.histogram(prices, bins=N_BINS, range=(lo, hi))
    bin_width = float(edges[1] - edges[0]) if len(edges) > 1 else 1.0
    total = len(prices)

    histogram = []
    for i in range(len(counts)):
        price_mid = float((edges[i] + edges[i + 1]) / 2)
        density = float(counts[i] / total) if total > 0 else 0.0
        # Normal PDF scaled to same area as histogram
        normal_d = float(
            scipy_stats.norm.pdf(price_mid, mean, std) * bin_width
            if std > 0 else 0.0
        )
        histogram.append({
            "price_mid": round(price_mid, 2),
            "count": int(counts[i]),
            "density": round(density, 6),
            "normal_density": round(normal_d, 6),
        })

    return MonteCarloResult(
        ticker=inputs.ticker,
        current_price=round(inputs.current_price, 2),
        iterations=len(prices),
        p10=round(p10, 2),
        p25=round(p25, 2),
        p50=round(p50, 2),
        p75=round(p75, 2),
        p90=round(p90, 2),
        mean=round(mean, 2),
        std=round(std, 2),
        probability_above_market=round(prob_above, 4),
        histogram=histogram,
        growth_mean_pct=round(mu_g * 100, 2),
        growth_std_pct=round(sigma_g * 100, 2),
        wacc_mean_pct=round(mu_wacc * 100, 2),
        wacc_std_pct=round(sigma_wacc * 100, 2),
        ks_statistic=round(float(ks_stat), 4),
        ks_pvalue=round(float(ks_pval), 4),
    )
