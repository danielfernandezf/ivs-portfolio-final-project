"""
Institutional Business Valuation System — FastAPI Backend
==========================================================
Endpoints:
  GET  /api/valuation/{ticker}         — Full DCF valuation + technical risk
  POST /api/valuation/{ticker}/recalc  — Recalculate with custom scenario params
  POST /api/export-thesis              — Save Factsheet + Investment Thesis to /reports/
  GET  /api/portfolio                  — Current positions + cash summary
  GET  /api/portfolio/live             — Live prices + live MoS for all positions
  GET  /api/portfolio/sizing/{ticker}  — Position sizing recommendation + liquidity check
  POST /api/portfolio/buy              — Execute a buy and record position
  POST /api/portfolio/sell/{ticker}    — Fully liquidate a position
  GET  /api/health                     — Health check
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from valuation_engine import DCFAssumptions, MarketInputs, ValuationResult, engine
from risk_analysis import risk_analyser
from report_generator import generate_both, generate_trade_memo_pdf
from portfolio_db import portfolio_db, PortfolioPosition
from position_sizing import compute_position_size
from montecarlo_engine import run_montecarlo
from quality_engine import compute_quality_metrics, QualityMetrics
from performance_engine import (
    record_snapshot, record_capital_injection, get_performance,
    get_benchmark, bootstrap_history, get_portfolio_as_of, get_daily_returns,
)
from price_cache import get_live_prices, get_live_price, get_history_batch
import screener_engine
import movers_engine
import fx_engine
import sector_data
import sector_models
import valuation_guard
from company_profile import classify, ValuationModel, CompanyProfile

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("valuation-api")

# El python de la Microsoft Store trae yfinance 0.2.x, que falla todas las
# descargas contra la API actual de Yahoo (precios congelados al coste).
# Arrancar SIEMPRE con Anaconda (ver Desktop/ivs-portfolio.bat).
if int(yf.__version__.split(".")[0]) < 1:
    import sys
    logger.critical(
        "yfinance %s es demasiado antiguo — los precios live fallaran. "
        "Interprete: %s. Arranca el backend con el python de Anaconda.",
        yf.__version__, sys.executable,
    )

app = FastAPI(
    title="Institutional Valuation System",
    description="DCF + CAPM + WACC engine powered by Risk-Return Analysis (Schoenmaker & Schramade 2023)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RecalcRequest(BaseModel):
    wacc_override: Optional[float] = Field(None, description="Override WACC (decimal, e.g. 0.08)")
    revenue_growth_rate: float = Field(0.07, description="FCF growth rate for years 1-5")
    fcf_margin: float = Field(0.15, description="FCF margin % (informational)")
    terminal_growth_rate: float = Field(0.025, description="Terminal perpetuity growth rate")


class ExportThesisRequest(BaseModel):
    """
    Payload sent by the frontend when the user confirms a trade.
    Contains the full current valuation snapshot (with live slider values applied).
    """
    ticker: str
    snapshot: dict = Field(..., description="Full valuation snapshot as returned by /api/valuation")
    allocated_weight_pct: Optional[float] = Field(
        None, description="Portfolio weight % assigned to this position"
    )
    is_manual_override: bool = False   # Phase 6: true when user edited the system recommendation


class BuyRequest(BaseModel):
    ticker: str
    company_name: str
    shares: float = Field(gt=0)
    price_per_share: float = Field(gt=0)
    sector: str = "N/A"
    currency: str = "USD"
    intrinsic_price: float = Field(gt=0)
    mos_pct: float
    allocated_weight_pct: float
    is_manual_override: bool = False   # Phase 6: true when user edited the system recommendation


# ---------------------------------------------------------------------------
# yfinance data fetcher
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert arbitrary yfinance value to float safely."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


# Ticker aliases: non-standard symbols → yfinance-compatible equivalents
# .MC (Mercado Continuo Español) tickers are handled natively by yfinance (e.g. TEF.MC)
_TICKER_ALIASES: dict[str, str] = {
    "AHLA": "BABA.F",   # Alibaba — Frankfurt Xetra (EUR)
    "BABA.DE": "BABA.F",
}


def _normalize_ticker(raw: str) -> str:
    """Map non-standard ticker aliases to their yfinance equivalents."""
    upper = raw.upper().strip()
    return _TICKER_ALIASES.get(upper, upper)


# Caché corta de (Ticker, info). `.info` es la llamada más cara de yfinance
# (1-3 s) y durante una valoración completa se necesita en varios puntos
# (datos de mercado, clasificación, modelo sectorial). Sin esta caché, cada
# ticker del screener dispararía 3-4 descargas idénticas.
_INFO_TTL = 180
_info_cache: dict[str, tuple[float, Any, dict]] = {}
_info_lock = threading.Lock()


def _get_ticker_info(symbol: str) -> tuple[Any, dict]:
    """Devuelve (yf.Ticker, info) con caché de {_INFO_TTL}s."""
    now = time.time()
    with _info_lock:
        hit = _info_cache.get(symbol)
        if hit and now - hit[0] < _INFO_TTL:
            return hit[1], hit[2]

    try:
        tk = yf.Ticker(symbol)
        info = tk.info
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"yfinance error: {exc}") from exc

    with _info_lock:
        _info_cache[symbol] = (now, tk, info)
        # Poda simple para que un escaneo de 1.600 tickers no crezca sin control
        if len(_info_cache) > 400:
            cutoff = now - _INFO_TTL
            for k in [k for k, v in _info_cache.items() if v[0] < cutoff]:
                _info_cache.pop(k, None)
    return tk, info


def _fetch_market_inputs(ticker_symbol: str, require_fcf: bool = True) -> MarketInputs:
    """
    Download all required market data from yfinance.
    Raises HTTPException(404) if ticker not found.
    Raises HTTPException(502) on data fetch errors.

    `require_fcf=False` para bancos, aseguradoras y REITs: se valoran por
    exceso de retorno o por AFFO, de modo que la ausencia de una serie de flujo
    de caja libre no debe abortar la valoración.
    """
    ticker_symbol = _normalize_ticker(ticker_symbol)
    logger.info(f"Fetching data for {ticker_symbol}")

    tk, info = _get_ticker_info(ticker_symbol)

    # Validate ticker exists
    company_name = info.get("longName") or info.get("shortName") or ""
    if not company_name:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker '{ticker_symbol}' not found or has no data. "
                   "Check the symbol (e.g. AAPL, MSFT, NVDA).",
        )

    current_price = _safe_float(
        info.get("currentPrice") or info.get("regularMarketPrice") or info.get("ask"), 0.0
    )
    if current_price == 0.0:
        # Try last close
        hist = tk.history(period="5d")
        if not hist.empty:
            current_price = float(hist["Close"].iloc[-1])

    # --- Normalización de divisa (corrección crítica) ---
    # `currency` es la moneda de cotización; `financialCurrency` la de las
    # cuentas anuales. En los ADR extranjeros NO coinciden (AVAL cotiza en USD y
    # reporta en COP), y mezclarlas producía valores intrínsecos ~87.000x el
    # precio. A partir de aquí, TODO importe procedente de los estados
    # financieros se convierte a la moneda de cotización.
    data_warnings: list[str] = []
    quote_currency = info.get("currency") or "USD"
    financial_currency = info.get("financialCurrency") or quote_currency
    fx_rate = fx_engine.get_rate(financial_currency, quote_currency)

    if financial_currency != quote_currency:
        logger.info(
            f"{ticker_symbol}: cuentas en {financial_currency}, cotiza en "
            f"{quote_currency} — factor de conversión {fx_rate:.6g}"
        )
        if not fx_engine.is_supported(financial_currency):
            data_warnings.append(
                f"Divisa de los estados financieros ({financial_currency}) sin tipo de "
                "cambio fiable: la valoración puede estar distorsionada"
            )

    # --- Beta ---
    # Los guardarraíles de rango viven en el motor (BETA_FLOOR / BETA_CAP); aquí
    # sólo se descarta un valor imposible o ausente.
    beta = _safe_float(info.get("beta"), 0.0)
    if beta <= 0 or beta > 5:
        beta = 1.0
        data_warnings.append("Beta no disponible o fuera de rango: se asume 1,00")

    # --- Shares outstanding ---
    # El respaldo anterior era 1e6 acciones. Si yfinance no devolvía el dato, el
    # valor intrínseco se dividía entre un millón ficticio y salía disparado.
    # Sin número de acciones no hay valor por acción posible: es un fallo duro.
    shares = _safe_float(
        info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"), 0.0
    )
    if shares <= 0:
        raise HTTPException(
            status_code=422,
            detail=f"'{ticker_symbol}': número de acciones en circulación no disponible; "
                   "no es posible calcular un valor por acción.",
        )

    # --- Balance sheet items (en moneda de las cuentas → se convierten) ---
    total_debt = _safe_float(info.get("totalDebt"), 0.0) * fx_rate
    cash = _safe_float(
        info.get("totalCash") or info.get("cashAndCashEquivalentsAtCarryingValue"), 0.0
    ) * fx_rate

    # --- Market cap (ya en moneda de cotización) ---
    market_cap = _safe_float(info.get("marketCap"), current_price * shares)

    # --- Risk-Free Rate (10-year Treasury ^TNX) ---
    try:
        tnx = yf.Ticker("^TNX")
        tnx_hist = tnx.history(period="5d")
        if not tnx_hist.empty:
            rfr = float(tnx_hist["Close"].iloc[-1]) / 100.0
        else:
            rfr = 0.042
    except Exception:
        rfr = 0.042

    # --- Cost of Debt (use interest expense / total debt) ---
    try:
        fin = tk.financials
        interest_expense = 0.0
        if fin is not None and not fin.empty:
            ie_row = None
            for idx in fin.index:
                if "interest" in str(idx).lower():
                    ie_row = idx
                    break
            if ie_row is not None:
                ie_vals = fin.loc[ie_row].dropna()
                interest_expense = abs(float(ie_vals.iloc[0])) if not ie_vals.empty else 0.0
        cod = (interest_expense / total_debt) if total_debt > 0 else 0.05
        cod = max(min(cod, 0.15), 0.03)  # clamp 3%-15%
    except Exception:
        cod = 0.05

    # --- Effective Tax Rate ---
    try:
        tax_rate = _safe_float(info.get("effectiveTaxRate"), 0.21)
        if tax_rate > 1:
            tax_rate /= 100
        tax_rate = max(min(tax_rate, 0.40), 0.05)
    except Exception:
        tax_rate = 0.21

    # --- Free Cash Flow History (last 3-4 years) ---
    try:
        cf = tk.cashflow
        fcf_history: list[float] = []
        if cf is not None and not cf.empty:
            # Try standard FCF rows
            ocf_row = next(
                (r for r in cf.index if "operating" in str(r).lower() and "cash" in str(r).lower()),
                None,
            )
            capex_row = next(
                (r for r in cf.index if "capital" in str(r).lower() or "capex" in str(r).lower()),
                None,
            )
            fcf_row = next(
                (r for r in cf.index if "free cash" in str(r).lower()),
                None,
            )

            if fcf_row is not None:
                fcf_series = cf.loc[fcf_row].dropna().sort_index()
                fcf_history = [float(v) for v in fcf_series.values[-4:]]
            elif ocf_row and capex_row:
                ocf = cf.loc[ocf_row]
                capex = cf.loc[capex_row]
                combined = ocf + capex  # capex is usually negative
                combined = combined.dropna().sort_index()
                fcf_history = [float(v) for v in combined.values[-4:]]

        if not fcf_history:
            # Respaldo: sólo flujo de caja de explotación.
            # `.sort_index()` es imprescindible — yfinance devuelve las columnas
            # del estado de flujos en orden DESCENDENTE (el ejercicio más
            # reciente primero). Sin ordenar, `values[-4:]` tomaba el año MÁS
            # ANTIGUO como base del DCF y calculaba el crecimiento al revés.
            try:
                ocf_row2 = next(
                    (r for r in cf.index if "operating" in str(r).lower()),
                    None,
                )
                if ocf_row2:
                    series = cf.loc[ocf_row2].dropna().sort_index()
                    fcf_history = [float(v) for v in series.values[-4:]]
                    data_warnings.append(
                        "Sin capex identificable: se usa el flujo de explotación como "
                        "aproximación del FCF (sobrestima el flujo libre)"
                    )
            except Exception:
                pass

        if not fcf_history:
            reported = _safe_float(info.get("freeCashflow"), 0.0)
            if reported != 0:
                fcf_history = [reported]
                data_warnings.append("FCF de un solo ejercicio: sin histórico para calibrar el crecimiento")

    except Exception:
        reported = _safe_float(info.get("freeCashflow"), 0.0)
        fcf_history = [reported] if reported != 0 else []

    # El respaldo anterior era `market_cap * 0.05`: inventaba un FCF a partir de
    # la propia capitalización, de modo que el DCF acababa "validando" el precio
    # de mercado que debía cuestionar. Sin flujo real no hay valoración posible.
    if not fcf_history:
        if require_fcf:
            raise HTTPException(
                status_code=422,
                detail=f"'{ticker_symbol}': sin histórico de flujo de caja utilizable; "
                       "no es posible aplicar un descuento de flujos.",
            )
        data_warnings.append("Sin histórico de flujo de caja libre (no requerido por este modelo)")

    # Los flujos vienen de las cuentas anuales → conversión a moneda de cotización
    fcf_history = [v * fx_rate for v in fcf_history]

    return MarketInputs(
        ticker=ticker_symbol,
        company_name=company_name,
        current_price=current_price,
        beta=beta,
        shares_outstanding=shares,
        total_debt=total_debt,
        cash_and_equivalents=cash,
        risk_free_rate=rfr,
        market_risk_premium=0.055,   # Historical ERP ~5.5% (Table 12.1 avg)
        cost_of_debt_pretax=cod,
        effective_tax_rate=tax_rate,
        fcf_history=fcf_history,
        market_cap=market_cap,
        sector=info.get("sector", "N/A"),
        currency=quote_currency,
        financial_currency=financial_currency,
        fx_rate=fx_rate,
        industry=info.get("industry", "N/A"),
        data_warnings=data_warnings,
    )


def _auto_assumptions(inputs: MarketInputs) -> DCFAssumptions:
    """Derive baseline assumptions from historical data."""
    from valuation_engine import ValuationEngine
    eng = ValuationEngine()
    hist_growth = eng._calibrate_base_growth(inputs.fcf_history)

    # Reversión a la media: se aplica un factor de 0,70 al crecimiento histórico
    # porque ninguna ventaja competitiva se sostiene indefinidamente.
    #
    # El suelo anterior era del +3 % para cualquier empresa con FCF positivo, lo
    # que significaba que un negocio en declive estructural (FCF cayendo un 15 %
    # anual) se proyectaba igualmente CRECIENDO un 3 % durante cinco años, y
    # luego a perpetuidad. Eso convertía trampas de valor en "oportunidades".
    # Ahora se permite proyectar decrecimiento, acotado para no extrapolar un
    # desplome hasta cero.
    base_growth = float(np.clip(hist_growth * 0.70, -0.10, 0.20))

    return DCFAssumptions(
        revenue_growth_rate=base_growth,
        fcf_margin=0.15,
        terminal_growth_rate=min(0.025, inputs.risk_free_rate - 0.01),
    )


def _result_to_dict(result: ValuationResult, inputs: MarketInputs, assumptions: DCFAssumptions) -> dict:
    """Serialise ValuationResult to a JSON-safe dict."""

    def fmt(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 6) if abs(v) < 1e10 else round(v, 2)
        if isinstance(v, list):
            return [fmt(i) for i in v]
        return v

    return {
        "ticker": result.ticker,
        "company_name": result.company_name,
        "sector": inputs.sector,
        "currency": inputs.currency,
        "current_price": fmt(result.current_price),

        # WACC decomposition
        "wacc": fmt(result.wacc),
        "cost_of_equity": fmt(result.cost_of_equity),
        "cost_of_debt_aftertax": fmt(result.cost_of_debt_aftertax),
        "equity_weight": fmt(result.equity_weight),
        "debt_weight": fmt(result.debt_weight),

        # Inputs used
        "beta": fmt(inputs.beta),
        "risk_free_rate": fmt(inputs.risk_free_rate),
        "market_risk_premium": fmt(inputs.market_risk_premium),
        "effective_tax_rate": fmt(inputs.effective_tax_rate),

        # Balance sheet
        "market_cap": fmt(inputs.market_cap),
        "total_debt": fmt(inputs.total_debt),
        "cash": fmt(inputs.cash_and_equivalents),
        "net_debt": fmt(result.net_debt),
        "shares_outstanding": fmt(inputs.shares_outstanding),

        # FCF history
        "fcf_history": fmt(inputs.fcf_history),

        # DCF outputs
        "base_fcf": fmt(result.base_fcf),
        "projected_fcfs": fmt(result.projected_fcfs),
        "pv_fcfs": fmt(result.pv_fcfs),
        "terminal_value": fmt(result.terminal_value),
        "pv_terminal_value": fmt(result.pv_terminal_value),
        "enterprise_value": fmt(result.enterprise_value),
        "equity_value": fmt(result.equity_value),
        "intrinsic_price_per_share": fmt(result.intrinsic_price_per_share),
        "upside_downside_pct": fmt(result.upside_downside_pct),

        # Trazabilidad de calidad de datos y modelo
        "terminal_value_share": fmt(result.terminal_value_share),
        "warnings": list(result.warnings) + list(inputs.data_warnings),
        "financial_currency": inputs.financial_currency,
        "fx_rate": fmt(inputs.fx_rate),
        "fx_converted": inputs.financial_currency != inputs.currency,

        # Assumptions used
        "assumptions": {
            "revenue_growth_rate": fmt(assumptions.revenue_growth_rate),
            "fcf_margin": fmt(assumptions.fcf_margin),
            "terminal_growth_rate": fmt(assumptions.terminal_growth_rate),
            "wacc_override": assumptions.wacc_override,
            "projection_years": assumptions.projection_years,
        },

        # Investment Committee Verdict
        "verdict": {
            "verdict": result.verdict.verdict,
            "margin_of_safety": fmt(result.verdict.margin_of_safety),
            "expected_return": fmt(result.verdict.expected_return),
            "hurdle_rate": fmt(result.verdict.hurdle_rate),
            "clears_hurdle": result.verdict.clears_hurdle,
            "key_risk": result.verdict.key_risk,
            "rationale": result.verdict.rationale,
        },
    }


def _technical_to_dict(sig) -> Optional[dict]:
    if sig is None:
        return None
    d = asdict(sig)
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items()}


def _quality_to_dict(q: QualityMetrics) -> dict:
    """Serialise QualityMetrics to a JSON-safe dict."""
    return {
        "ticker": q.ticker,
        "altman": {
            "z_score": q.altman.z_score,
            "zone": q.altman.zone,
            "x1_wc_to_assets": q.altman.x1_wc_to_assets,
            "x2_re_to_assets": q.altman.x2_re_to_assets,
            "x3_ebit_to_assets": q.altman.x3_ebit_to_assets,
            "x4_mktcap_to_liab": q.altman.x4_mktcap_to_liab,
            "x5_rev_to_assets": q.altman.x5_rev_to_assets,
            "triggers_override": q.altman.triggers_override,
            "note": q.altman.note,
        },
        "piotroski": {
            "score": q.piotroski.score,
            "f1_roa_positive": q.piotroski.f1_roa_positive,
            "f2_ocf_positive": q.piotroski.f2_ocf_positive,
            "f3_roa_improving": q.piotroski.f3_roa_improving,
            "f4_accruals_quality": q.piotroski.f4_accruals_quality,
            "f5_leverage_improving": q.piotroski.f5_leverage_improving,
            "f6_liquidity_improving": q.piotroski.f6_liquidity_improving,
            "f7_no_dilution": q.piotroski.f7_no_dilution,
            "f8_gross_margin_improving": q.piotroski.f8_gross_margin_improving,
            "f9_asset_turnover_improving": q.piotroski.f9_asset_turnover_improving,
            "triggers_override": q.piotroski.triggers_override,
            "signals_computed": q.piotroski.signals_computed,
        },
        "benchmark": {
            "pe_ratio": q.benchmark.pe_ratio,
            "ev_ebitda": q.benchmark.ev_ebitda,
            "sector_pe": q.benchmark.sector_pe,
            "sector_ev_ebitda": q.benchmark.sector_ev_ebitda,
            "pe_vs_sector_pct": q.benchmark.pe_vs_sector_pct,
            "ev_ebitda_vs_sector_pct": q.benchmark.ev_ebitda_vs_sector_pct,
        },
        "liquidity": {
            "avg_volume_10d": q.liquidity.avg_volume_10d,
            "max_shares_in_position": q.liquidity.max_shares_in_position,
            "volume_impact_pct": q.liquidity.volume_impact_pct,
            "alert": q.liquidity.alert,
        },
        "verdict_override": q.verdict_override,
        "override_reason": q.override_reason,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    import sys
    return {
        "status": "online",
        "engine": "Institutional Valuation System v1.0",
        "python": sys.executable,
        "yfinance": yf.__version__,
    }


@app.get("/api/valuation/{ticker}")
def get_valuation(ticker: str):
    """
    Auto-fetch market data and compute full DCF valuation.
    Returns fundamental valuation + technical risk analysis.
    """
    inputs = _fetch_market_inputs(ticker)
    assumptions = _auto_assumptions(inputs)
    result = engine.compute(inputs, assumptions)

    # ¿Es esta empresa un caso donde el DCF sobre FCF no es el modelo correcto?
    # El analizador conserva el DCF (con las cifras ya normalizadas por divisa,
    # así que no es catastrófico), pero avisa de que el screener aplica un
    # modelo específico del sector y ese es el número de referencia.
    model_note: Optional[str] = None
    try:
        _, _info = _get_ticker_info(_normalize_ticker(ticker))
        _profile = classify(_normalize_ticker(ticker), _info)
        if _profile.model is ValuationModel.EXCESS_RETURN:
            model_note = (
                "Entidad financiera de balance: el DCF sobre flujo de caja libre no capta "
                "su economía. La valoración automática aplica un modelo de Exceso de "
                "Retorno sobre fondos propios — úsalo como referencia."
            )
        elif _profile.model is ValuationModel.REIT_AFFO:
            model_note = (
                "REIT: el capex inmobiliario deprime el FCF y el DCF lo infravalora. "
                "La valoración automática aplica un modelo AFFO — úsalo como referencia."
            )
        elif _profile.model is ValuationModel.EXCLUDED:
            model_note = _profile.excluded_reason
    except Exception as e:
        logger.warning(f"Model classification failed for {ticker}: {e}")

    # Technical risk (separate module — El Arte de Especular methodology)
    technical = None
    try:
        tk = yf.Ticker(ticker.upper())
        hist = tk.history(period="1y")
        if not hist.empty:
            technical = risk_analyser.analyse(
                ticker.upper(),
                hist["Close"],
                high_series=hist["High"] if "High" in hist.columns else None,
                low_series=hist["Low"]  if "Low"  in hist.columns else None,
            )
    except Exception as e:
        logger.warning(f"Technical analysis failed for {ticker}: {e}")

    # Phase 5 — Quality & Survival metrics
    quality = None
    quality_dict = None
    try:
        quality = compute_quality_metrics(
            ticker_symbol=ticker,
            current_price=inputs.current_price,
            market_cap=inputs.market_cap,
        )
        quality_dict = _quality_to_dict(quality)
    except Exception as e:
        logger.warning(f"Quality metrics failed for {ticker}: {e}")

    fundamental_dict = _result_to_dict(result, inputs, assumptions)

    # Override verdict if quality triggers it
    if quality and quality.verdict_override:
        fundamental_dict["verdict"]["verdict"] = "SELL/AVOID"
        fundamental_dict["verdict"]["key_risk"] = (
            quality.override_reason or fundamental_dict["verdict"]["key_risk"]
        )
        fundamental_dict["verdict"]["rationale"] = (
            f"[QUALITY OVERRIDE] {quality.override_reason}  "
            + fundamental_dict["verdict"]["rationale"]
        )
        logger.info(f"Quality override applied for {ticker}: {quality.override_reason}")

    if model_note:
        fundamental_dict["model_note"] = model_note

    return {
        "fundamental": fundamental_dict,
        "technical": _technical_to_dict(technical),
        "quality": quality_dict,
    }


@app.post("/api/valuation/{ticker}/recalc")
def recalc_valuation(ticker: str, body: RecalcRequest):
    """
    Recalculate DCF with user-overridden scenario parameters.
    Used by the frontend sensitivity panel sliders.
    """
    inputs = _fetch_market_inputs(ticker)
    assumptions = DCFAssumptions(
        revenue_growth_rate=body.revenue_growth_rate,
        fcf_margin=body.fcf_margin,
        terminal_growth_rate=body.terminal_growth_rate,
        wacc_override=body.wacc_override,
    )
    result = engine.compute(inputs, assumptions)
    return {"fundamental": _result_to_dict(result, inputs, assumptions)}


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

def _position_to_dict(p: PortfolioPosition) -> dict:
    return {
        "id": p.id,
        "ticker": p.ticker,
        "company_name": p.company_name,
        "shares": p.shares,
        "purchase_price": round(p.purchase_price, 4),
        "purchase_date": p.purchase_date,
        "sector": p.sector,
        "currency": p.currency,
        "intrinsic_price_at_purchase": round(p.intrinsic_price_at_purchase, 4),
        "mos_at_purchase": round(p.mos_at_purchase, 2),
        "allocated_weight_pct": round(p.allocated_weight_pct, 2),
        "cost_basis_total": round(p.cost_basis_total, 2),
        "is_manual_override": p.is_manual_override,
    }


def _fetch_live_price(ticker: str) -> float:
    """Fast yfinance price fetch (cacheado, vía fast_info en price_cache)."""
    return get_live_price(ticker)


# ---------------------------------------------------------------------------
# Portfolio endpoints
# ---------------------------------------------------------------------------

@app.get("/api/portfolio")
def get_portfolio():
    """Return current positions and cash summary."""
    summary = portfolio_db.get_summary()
    return {
        "positions": [_position_to_dict(p) for p in summary.positions],
        "cash_balance": round(summary.cash_balance, 2),
        "initial_capital": round(summary.initial_capital, 2),
        "invested_capital": round(summary.invested_capital, 2),
        "total_portfolio_value": round(summary.total_portfolio_value, 2),
        "n_positions": len(summary.positions),
    }


@app.get("/api/portfolio/live")
def get_portfolio_live():
    """
    Refresh all positions with live yfinance prices.
    Recomputes: current_value, return_pct, live_mos for each position.
    """
    positions = portfolio_db.get_positions()
    if not positions:
        summary = portfolio_db.get_summary()
        return {
            "live_positions": [],
            "cash_balance": round(summary.cash_balance, 2),
            "total_live_value": round(summary.cash_balance, 2),
            "total_return_pct": 0.0,
        }

    live_rows = []
    total_live_market_value = 0.0

    # Precarga TODOS los precios live en una sola tanda (paralelo + caché)
    live_prices = get_live_prices([p.ticker for p in positions])

    stale_count = 0
    for pos in positions:
        live_price = live_prices.get(pos.ticker) or 0.0
        price_is_live = live_price > 0
        if not price_is_live:
            live_price = pos.purchase_price   # fallback to cost
            stale_count += 1

        current_market_value = pos.shares * live_price
        total_live_market_value += current_market_value

        return_pct = (live_price - pos.purchase_price) / pos.purchase_price * 100

        # Live MoS uses the intrinsic price locked at purchase vs current market price
        live_mos = (
            (pos.intrinsic_price_at_purchase - live_price)
            / pos.intrinsic_price_at_purchase * 100
            if pos.intrinsic_price_at_purchase > 0 else 0.0
        )

        live_rows.append({
            **_position_to_dict(pos),
            "live_price": round(live_price, 4),
            "price_is_live": price_is_live,
            "current_market_value": round(current_market_value, 2),
            "return_pct": round(return_pct, 2),
            "live_mos": round(live_mos, 2),
        })

    # Sort by live_mos ascending (worst first — useful for substitution committee)
    live_rows.sort(key=lambda r: r["live_mos"])

    cash = portfolio_db.get_cash()
    total = total_live_market_value + cash
    initial = portfolio_db.get_initial_capital()
    portfolio_return = (total - initial) / initial * 100

    return {
        "live_positions": live_rows,
        "cash_balance": round(cash, 2),
        "total_live_value": round(total, 2),
        "portfolio_return_pct": round(portfolio_return, 2),
        # Nº de posiciones cuyo precio live NO se pudo obtener (mostrando coste).
        # Si > 0 el frontend enseña un aviso: el retorno mostrado no es real.
        "stale_prices": stale_count,
    }


@app.get("/api/portfolio/sizing/{ticker}")
def get_position_sizing(
    ticker: str,
    mos_pct: float = 0.0,
    beta: float = 1.0,
    current_price: float = 0.0,
):
    """
    Return position sizing recommendation for a given ticker.
    Also performs the liquidity check and Substitution Committee analysis.
    """
    ticker = ticker.upper()

    # Fetch live price if not provided
    if current_price <= 0:
        current_price = _fetch_live_price(ticker)
    if current_price <= 0:
        raise HTTPException(status_code=502, detail=f"Could not fetch live price for {ticker}.")

    summary = portfolio_db.get_summary()
    cash = summary.cash_balance
    portfolio_total = summary.total_portfolio_value

    # Get live sell candidates (sorted worst MoS first) if cash is tight
    sell_candidates = []
    if cash < current_price:   # rough check — no cash for even 1 share
        try:
            live = get_portfolio_live()
            for row in live["live_positions"]:
                sell_candidates.append({
                    "ticker": row["ticker"],
                    "live_mos": row["live_mos"],
                    "cost_basis": row["cost_basis_total"],
                    "live_price": row["live_price"],
                    "shares": row["shares"],
                })
        except Exception as e:
            logger.warning(f"Could not compute sell candidates: {e}")

    initial_capital = summary.initial_capital

    result = compute_position_size(
        ticker=ticker,
        margin_of_safety_pct=mos_pct,
        beta=beta,
        portfolio_total=portfolio_total,
        cash_available=cash,
        current_price=current_price,
        initial_capital=initial_capital,
        sell_candidates=sell_candidates if not (cash >= 0) else sell_candidates,
    )

    return {
        "ticker": result.ticker,
        "margin_of_safety": result.margin_of_safety,
        "beta": result.beta,
        "raw_weight_pct": result.raw_weight_pct,
        "recommended_weight_pct": result.recommended_weight_pct,
        "capped_at_limit": result.capped_at_limit,
        "capital_to_deploy": result.capital_to_deploy,
        "shares_to_buy": result.shares_to_buy,
        "estimated_cost": result.estimated_cost,
        "cash_available": result.cash_available,
        "cash_sufficient": result.cash_sufficient,
        "shortfall": result.shortfall,
        "portfolio_used_pct": result.portfolio_used_pct,
        "capacity_remaining_pct": result.capacity_remaining_pct,
        "max_affordable_shares": result.max_affordable_shares,
        "sell_candidate_ticker": result.sell_candidate_ticker,
        "sell_candidate_mos": result.sell_candidate_mos,
        "sell_candidate_proceeds": result.sell_candidate_proceeds,
        "liquidity_alert": result.liquidity_alert,
        "portfolio_total": round(portfolio_total, 2),
        "initial_capital": round(initial_capital, 2),
    }


@app.post("/api/portfolio/buy")
def buy_position(body: BuyRequest):
    """Execute a buy and record the position in the portfolio DB."""
    ticker = body.ticker.upper()
    try:
        pos = portfolio_db.buy(
            ticker=ticker,
            company_name=body.company_name,
            shares=body.shares,
            price_per_share=body.price_per_share,
            sector=body.sector,
            currency=body.currency,
            intrinsic_price=body.intrinsic_price,
            mos_pct=body.mos_pct,
            allocated_weight_pct=body.allocated_weight_pct,
            is_manual_override=body.is_manual_override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        f"BUY {body.shares:.4f} × {ticker} @ {body.price_per_share:.2f} "
        f"| MoS={body.mos_pct:.1f}% | Weight={body.allocated_weight_pct:.1f}%"
    )

    # Record performance snapshot after buy
    try:
        cash_now = portfolio_db.get_cash()
        invested = sum(p.cost_basis_total for p in portfolio_db.get_positions())
        record_snapshot(
            total_value=cash_now + invested,
            cash_balance=cash_now,
            invested_value=invested,
            event="buy",
        )
    except Exception as e:
        logger.warning(f"Failed to record snapshot after buy: {e}")

    # Auto-generate professional Trade Memo PDF
    memo_path: Optional[str] = None
    try:
        snapshot = get_valuation(ticker)
        memo = generate_trade_memo_pdf(
            snapshot=snapshot,
            action="BUY",
            trade={
                "shares": body.shares,
                "price": body.price_per_share,
                "notional": body.shares * body.price_per_share,
                "origin": "Manual override" if body.is_manual_override else "System recommendation",
            },
            allocated_weight_pct=body.allocated_weight_pct,
            is_manual_override=body.is_manual_override,
        )
        memo_path = str(memo.resolve())
        logger.info(f"Trade memo PDF written: {memo_path}")
    except Exception as e:
        logger.warning(f"Failed to generate BUY memo PDF for {ticker}: {e}")

    return {
        "success": True,
        "position": _position_to_dict(pos),
        "cash_remaining": round(portfolio_db.get_cash(), 2),
        "trade_memo_pdf": memo_path,
    }


@app.post("/api/portfolio/sell/{ticker}")
def sell_position(ticker: str, at_live_price: bool = False):
    """
    Fully liquidate a position.
    at_live_price=True fetches the current price from yfinance for proceeds.
    at_live_price=False returns the cost basis (conservative / virtual mode).
    """
    ticker = ticker.upper()

    # Capture pre-sell position details (needed for the memo's P&L section)
    pre_pos = portfolio_db.get_position(ticker)
    pre_shares = pre_pos.shares if pre_pos else 0.0
    pre_cost_basis = pre_pos.cost_basis_total if pre_pos else 0.0
    pre_weight = getattr(pre_pos, "allocated_weight_pct", None) if pre_pos else None

    try:
        if at_live_price:
            live_price = _fetch_live_price(ticker)
            if live_price <= 0:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not fetch live price for {ticker}. Use at_live_price=false.",
                )
            proceeds = portfolio_db.sell_at_price(ticker, live_price)
        else:
            proceeds = portfolio_db.sell(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(f"SELL {ticker} | Proceeds={proceeds:.2f} credited to cash")

    # Record performance snapshot after sell
    try:
        cash_now = portfolio_db.get_cash()
        invested = sum(p.cost_basis_total for p in portfolio_db.get_positions())
        record_snapshot(
            total_value=cash_now + invested,
            cash_balance=cash_now,
            invested_value=invested,
            event="sell",
        )
    except Exception as e:
        logger.warning(f"Failed to record snapshot after sell: {e}")

    # Auto-generate professional SELL Trade Memo PDF
    memo_path: Optional[str] = None
    try:
        snapshot = get_valuation(ticker)
        exec_price = proceeds / pre_shares if pre_shares > 0 else 0.0
        realised_pnl = proceeds - pre_cost_basis
        realised_pnl_pct = (
            (realised_pnl / pre_cost_basis) * 100 if pre_cost_basis > 0 else None
        )
        memo = generate_trade_memo_pdf(
            snapshot=snapshot,
            action="SELL",
            trade={
                "shares": pre_shares,
                "price": exec_price,
                "proceeds": proceeds,
                "realised_pnl": realised_pnl,
                "realised_pnl_pct": realised_pnl_pct,
                "origin": "Live-price liquidation" if at_live_price else "Cost-basis liquidation",
            },
            allocated_weight_pct=pre_weight,
        )
        memo_path = str(memo.resolve())
        logger.info(f"Trade memo PDF written: {memo_path}")
    except Exception as e:
        logger.warning(f"Failed to generate SELL memo PDF for {ticker}: {e}")

    return {
        "success": True,
        "ticker": ticker,
        "proceeds": round(proceeds, 2),
        "cash_balance": round(portfolio_db.get_cash(), 2),
        "trade_memo_pdf": memo_path,
    }


@app.post("/api/export-thesis")
def export_thesis(body: ExportThesisRequest):
    """
    Save Factsheet and Investment Thesis to disk.

    Receives the full valuation snapshot (with live slider overrides) from the frontend,
    generates two Markdown files in /reports/, and returns their paths.

    The snapshot is expected to match the shape of /api/valuation/{ticker} response.
    """
    ticker = body.ticker.upper().strip()
    snapshot = body.snapshot

    # Defensive: ensure fundamental key exists in the snapshot
    if "fundamental" not in snapshot:
        raise HTTPException(
            status_code=422,
            detail="Snapshot must contain a 'fundamental' key.",
        )

    try:
        paths = generate_both(snapshot, allocated_weight_pct=body.allocated_weight_pct, is_manual_override=body.is_manual_override)
    except Exception as exc:
        logger.exception(f"Report generation failed for {ticker}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate reports: {exc}",
        ) from exc

    logger.info(f"Reports saved for {ticker}: {paths}")

    return {
        "success": True,
        "ticker": ticker,
        "verdict": snapshot["fundamental"].get("verdict", {}).get("verdict", "N/A"),
        "files": {
            "factsheet": paths["factsheet"],
            "thesis": paths["thesis"],
        },
        "reports_dir": paths["reports_dir"],
        "message": f"Investment thesis for {ticker} saved to {paths['reports_dir']}",
    }


# ---------------------------------------------------------------------------
# Phase 4 — Quant Engine endpoints
# ---------------------------------------------------------------------------

@app.get("/api/montecarlo/{ticker}")
def get_montecarlo(ticker: str, iterations: int = Query(default=10_000, ge=1000, le=50_000)):
    """
    Run a Monte Carlo DCF simulation for a ticker.

    Introduces Gaussian noise on the FCF growth rate (σ calibrated to
    historical FCF volatility) and WACC (σ derived from beta uncertainty).

    Returns histogram bins for the bell-curve chart, key percentiles, and
    P(intrinsic > market_price).
    """
    inputs = _fetch_market_inputs(ticker)
    assumptions = _auto_assumptions(inputs)

    try:
        result = run_montecarlo(inputs, assumptions, n_iterations=iterations)
    except Exception as exc:
        logger.exception(f"Monte Carlo failed for {ticker}: {exc}")
        raise HTTPException(status_code=500, detail=f"Monte Carlo error: {exc}") from exc

    return {
        "ticker": result.ticker,
        "current_price": result.current_price,
        "iterations": result.iterations,
        "p10": result.p10,
        "p25": result.p25,
        "p50": result.p50,
        "p75": result.p75,
        "p90": result.p90,
        "mean": result.mean,
        "std": result.std,
        "probability_above_market": result.probability_above_market,
        "histogram": result.histogram,
        "growth_mean_pct": result.growth_mean_pct,
        "growth_std_pct": result.growth_std_pct,
        "wacc_mean_pct": result.wacc_mean_pct,
        "wacc_std_pct": result.wacc_std_pct,
        "ks_statistic": result.ks_statistic,
        "ks_pvalue": result.ks_pvalue,
    }


@app.get("/api/portfolio/risk-metrics")
def get_portfolio_risk_metrics():
    """
    Compute portfolio-level risk analytics:
      - Annualised return & volatility (from daily returns, 252-day scaling)
      - Sharpe ratio (excess return / volatility)
      - Quality alerts: Z-Score / F-Score warnings for each position
    """
    positions = portfolio_db.get_positions()
    if not positions:
        return {
            "sharpe_ratio": None,
            "annualised_return_pct": 0.0,
            "annualised_volatility_pct": 0.0,
            "portfolio_beta": 0.0,
            "alerts": [],
            "n_positions": 0,
        }

    tickers = [p.ticker for p in positions]
    weights_map: dict[str, float] = {}
    total_cost = sum(p.cost_basis_total for p in positions)
    for p in positions:
        weights_map[p.ticker] = p.cost_basis_total / total_cost if total_cost > 0 else 1.0 / len(positions)

    # Download 1-year price history per position
    price_data: dict[str, pd.Series] = {}
    beta_map: dict[str, float] = {}
    for tk_sym in tickers:
        try:
            tk = yf.Ticker(tk_sym)
            hist = tk.history(period="1y")
            if len(hist) > 50:
                price_data[tk_sym] = hist["Close"]
            beta_map[tk_sym] = _safe_float(tk.info.get("beta"), 1.0)
        except Exception as exc:
            logger.warning(f"Risk metrics: could not download {tk_sym}: {exc}")

    # Portfolio-weighted beta
    portfolio_beta = sum(
        weights_map.get(t, 0) * beta_map.get(t, 1.0) for t in tickers
    )

    # Portfolio return & volatility from weighted daily returns
    sharpe = None
    ann_return = 0.0
    ann_vol = 0.0

    available = [t for t in tickers if t in price_data]
    if len(available) >= 1:
        price_df = pd.DataFrame({t: price_data[t] for t in available}).dropna()
        if len(price_df) > 20:
            returns_df = price_df.pct_change().dropna()
            # Weighted portfolio daily return
            w = np.array([weights_map.get(t, 0) for t in available])
            w = w / w.sum()  # renormalise to available tickers
            portfolio_returns = returns_df.values @ w

            ann_return = float(np.mean(portfolio_returns) * 252 * 100)
            ann_vol = float(np.std(portfolio_returns, ddof=1) * np.sqrt(252) * 100)

            # Sharpe: (portfolio return - risk-free) / vol
            # Use current 10Y treasury as risk-free proxy
            try:
                tnx = yf.Ticker("^TNX")
                tnx_hist = tnx.history(period="5d")
                rfr = float(tnx_hist["Close"].iloc[-1]) if not tnx_hist.empty else 4.2
            except Exception:
                rfr = 4.2

            if ann_vol > 0:
                sharpe = round((ann_return - rfr) / ann_vol, 3)

    # Quality alerts: check each position for Z-Score / F-Score risks
    alerts: list[dict] = []
    for pos in positions:
        try:
            qm = compute_quality_metrics(
                ticker_symbol=pos.ticker,
                current_price=_fetch_live_price(pos.ticker) or pos.purchase_price,
                market_cap=0,  # will be fetched internally
            )
            if qm.altman.zone == "DISTRESS":
                alerts.append({
                    "ticker": pos.ticker,
                    "type": "Z_SCORE_DISTRESS",
                    "severity": "critical",
                    "title": f"{pos.ticker} — RIESGO DE SOLVENCIA",
                    "detail": f"Altman Z-Score = {qm.altman.z_score:.2f} (zona DISTRESS < 1.81). Revisar posici\u00f3n urgentemente.",
                    "z_score": qm.altman.z_score,
                })
            elif qm.altman.zone == "GREY":
                alerts.append({
                    "ticker": pos.ticker,
                    "type": "Z_SCORE_GREY",
                    "severity": "warning",
                    "title": f"{pos.ticker} — ZONA GRIS DE SOLVENCIA",
                    "detail": f"Altman Z-Score = {qm.altman.z_score:.2f} (zona gris 1.81-2.99). Monitorizar.",
                    "z_score": qm.altman.z_score,
                })
            if qm.piotroski.score < 5 and qm.piotroski.signals_computed >= 5:
                alerts.append({
                    "ticker": pos.ticker,
                    "type": "F_SCORE_WEAK",
                    "severity": "critical" if qm.piotroski.score < 3 else "warning",
                    "title": f"{pos.ticker} — CALIDAD FUNDAMENTAL D\u00c9BIL",
                    "detail": f"Piotroski F-Score = {qm.piotroski.score}/9. Se\u00f1ales de deterioro operativo.",
                    "f_score": qm.piotroski.score,
                })
        except Exception as exc:
            logger.warning(f"Quality alert check failed for {pos.ticker}: {exc}")

    return {
        "sharpe_ratio": sharpe,
        "annualised_return_pct": round(ann_return, 2),
        "annualised_volatility_pct": round(ann_vol, 2),
        "portfolio_beta": round(portfolio_beta, 3),
        "alerts": alerts,
        "n_positions": len(positions),
    }


@app.get("/api/portfolio/correlation")
def get_correlation(include: Optional[str] = Query(default=None)):
    """
    Compute the Pearson correlation matrix of daily returns for all portfolio
    positions over the past 2 years.

    If `include=TICKER` is provided, that ticker is added to the computation
    even if it is not yet in the portfolio (used by TradeConfirmModal to
    warn about high correlation before buying).

    Returns a correlation matrix, a list of pairs above the 0.75 threshold,
    and the number of trading-day observations used.
    """
    positions = portfolio_db.get_positions()
    tickers: list[str] = [p.ticker for p in positions]

    if include:
        extra = include.upper().strip()
        if extra not in tickers:
            tickers.append(extra)

    if len(tickers) < 2:
        return {
            "tickers": tickers,
            "matrix": {t: {t: 1.0} for t in tickers},
            "warnings": [],
            "data_period": "2y",
            "n_observations": 0,
            "message": "Need at least 2 tickers to compute correlation.",
        }

    # Histórico en UNA sola petición vía price_cache. Antes se hacía un
    # yf.Ticker().history() por ticker, que con 11 posiciones son 11 llamadas
    # secuenciales (lentas y carne de rate-limit 429). El heatmap de
    # rendimientos diarios reutiliza la misma descarga cacheada.
    start_2y = (datetime.now(timezone.utc) - timedelta(days=730)).strftime("%Y-%m-%d")
    raw = get_history_batch(tickers, start_2y)
    price_data: dict[str, Any] = {
        tk_sym: series for tk_sym, series in raw.items() if len(series) > 50
    }
    # Las posiciones sin histórico suficiente se quedan fuera de la matriz. Se
    # devuelven en `missing_tickers` para que la UI lo diga: una matriz de 5x5
    # sobre una cartera de 11 parece completa si no se avisa.
    missing = [tk_sym for tk_sym in tickers if tk_sym not in price_data]
    for tk_sym in missing:
        logger.warning(f"Insufficient history for {tk_sym}")

    available = list(price_data.keys())
    if len(available) < 2:
        return {
            "tickers": available,
            "matrix": {t: {t: 1.0} for t in available},
            "warnings": [],
            "missing_tickers": missing,
            "data_period": "2y",
            "n_observations": 0,
            "message": "Insufficient price data to compute correlation.",
        }

    # Align series and compute returns
    import pandas as pd
    price_df = pd.DataFrame(price_data).dropna()
    returns = price_df.pct_change().dropna()
    corr_df = returns.corr(method="pearson")

    n_obs = len(returns)

    # Build nested dict matrix
    matrix: dict[str, dict[str, float]] = {}
    for r in available:
        matrix[r] = {}
        for c in available:
            val = float(corr_df.loc[r, c]) if (r in corr_df.index and c in corr_df.columns) else 0.0
            matrix[r][c] = round(val, 4)

    # Identify high-correlation pairs (threshold 0.75, upper triangle only)
    THRESHOLD = 0.75
    warnings_list = []
    for i, r in enumerate(available):
        for c in available[i + 1:]:
            corr_val = matrix[r].get(c, 0.0)
            if corr_val > THRESHOLD:
                warnings_list.append({
                    "ticker1": r,
                    "ticker2": c,
                    "correlation": corr_val,
                })

    return {
        "tickers": available,
        "matrix": matrix,
        "warnings": warnings_list,
        "missing_tickers": missing,
        "data_period": "2y",
        "n_observations": n_obs,
    }


@app.get("/api/portfolio/daily-returns")
def get_portfolio_daily_returns(days: int = Query(default=30, ge=5, le=365)):
    """
    Rendimiento diario % de cada posición durante los últimos `days` días.

    Complementa a /api/portfolio/correlation: la correlación resume si dos
    valores se mueven juntos; esto muestra el detalle día a día de cada uno,
    que es lo que se pinta en el heatmap contiguo.
    """
    return get_daily_returns(days)


@app.get("/api/portfolio/as-of")
def get_portfolio_at_date(
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD"),
    compare_sessions: int = Query(default=5, ge=1, le=60),
):
    """
    La cartera tal y como estaba al cierre de `date`, posición a posición.

    `compare_sessions` fija la ventana de comparación en sesiones de bolsa
    (5 = una semana), usada para la columna de variación del período.

    Si la fecha cae fuera del rango con datos se acota al extremo más cercano en
    lugar de fallar, y si no fue día de bolsa se usa la sesión anterior; en ambos
    casos la respuesta indica la fecha efectiva en `date`.
    """
    return get_portfolio_as_of(date, compare_sessions)


# ---------------------------------------------------------------------------
# Movers — top performers del universo rastreado
# ---------------------------------------------------------------------------

@app.get("/api/screener/movers")
def get_screener_movers(limit: int = Query(default=20, ge=5, le=50)):
    """Ranking cacheado de mejores y peores de la semana en el universo."""
    return movers_engine.get_movers(limit)


@app.post("/api/screener/movers/refresh")
def refresh_screener_movers():
    """
    Recalcula los movers en background sobre el universo completo.

    Tarda minutos (~2300 tickers en tandas de 150), así que responde al momento
    con el estado y la UI va consultando /api/screener/movers.
    """
    return movers_engine.start_refresh()


# ---------------------------------------------------------------------------
# Phase 8 — Performance & Benchmarking endpoints
# ---------------------------------------------------------------------------

class CapitalInjectionRequest(BaseModel):
    amount: float = Field(gt=0, description="Amount of capital injection in EUR")


@app.get("/api/portfolio/performance")
def get_portfolio_performance(period: str = Query(default="all", pattern="^(week|month|year|all)$")):
    """
    Return portfolio value history and TWR (time-weighted return).
    period: week | month | year | all
    """
    perf = get_performance(period)
    return {
        "history": perf.history,
        "twr_pct": perf.twr_pct,
        "total_contributions": perf.total_contributions,
        "initial_capital": perf.initial_capital,
    }


@app.get("/api/portfolio/benchmark")
def get_portfolio_benchmark():
    """
    Compare portfolio performance against S&P 500 (SPY).
    Both series normalised to 100 from the first portfolio snapshot date.
    """
    bench = get_benchmark()
    return {
        "dates": bench.dates,
        "portfolio_indexed": bench.portfolio_indexed,
        "spy_indexed": bench.spy_indexed,
        "portfolio_return_pct": bench.portfolio_return_pct,
        "spy_return_pct": bench.spy_return_pct,
        "alpha_pct": bench.alpha_pct,
    }


@app.post("/api/portfolio/snapshot")
def take_snapshot():
    """
    Record a manual portfolio value snapshot (e.g. daily cron or manual trigger).
    Uses live prices to compute current total value.
    """
    positions = portfolio_db.get_positions()
    cash = portfolio_db.get_cash()

    live_prices = get_live_prices([p.ticker for p in positions])
    total_invested_live = 0.0
    for pos in positions:
        live_price = live_prices.get(pos.ticker) or 0.0
        if live_price <= 0:
            live_price = pos.purchase_price
        total_invested_live += pos.shares * live_price

    total_value = cash + total_invested_live

    record_snapshot(
        total_value=total_value,
        cash_balance=cash,
        invested_value=total_invested_live,
        event="manual_snapshot",
    )

    return {
        "success": True,
        "total_value": round(total_value, 2),
        "cash_balance": round(cash, 2),
        "invested_value": round(total_invested_live, 2),
    }


@app.post("/api/portfolio/inject-capital")
def inject_capital(body: CapitalInjectionRequest):
    """
    Record a capital injection (e.g. monthly 1,000 EUR contribution).
    Adds to cash balance and records it as a contribution (not return).
    """
    amount = body.amount

    portfolio_db.inject_capital(amount)

    new_cash = portfolio_db.get_cash()
    new_initial = portfolio_db.get_initial_capital()
    invested = sum(p.cost_basis_total for p in portfolio_db.get_positions())

    record_capital_injection(
        amount=amount,
        new_cash_balance=new_cash,
        new_total_value=new_cash + invested,
    )

    logger.info(f"Capital injection: +{amount:.2f} EUR | New cash: {new_cash:.2f} | New initial: {new_initial:.2f}")

    return {
        "success": True,
        "amount_injected": round(amount, 2),
        "new_cash_balance": round(new_cash, 2),
        "new_initial_capital": round(new_initial, 2),
    }


# ---------------------------------------------------------------------------
# Phase 9 — Live Screener (Margin-of-Safety discovery across a universe)
# ---------------------------------------------------------------------------

def _value_by_model(ticker: str) -> dict:
    """
    Valoración enrutada por tipo de empresa.

    Devuelve un diccionario homogéneo independientemente del modelo aplicado
    (DCF, Exceso de Retorno o AFFO), de modo que la interfaz pueda comparar
    manzanas con manzanas mientras la matemática subyacente respeta la
    naturaleza de cada negocio.

    Lanza HTTPException en fallos duros de descarga; devuelve un registro con
    `excluded=True` cuando la empresa no es valorable de forma fiable.
    """
    symbol = _normalize_ticker(ticker)
    tk, info = _get_ticker_info(symbol)
    profile = classify(symbol, info)

    base = {
        "ticker": symbol,
        "company_name": info.get("longName") or info.get("shortName") or symbol,
        "sector": profile.sector,
        "industry": profile.industry,
        "currency": info.get("currency", "USD"),
        "model": profile.model.value,
        "excluded": False,
        "excluded_reason": None,
    }

    # --- Instrumentos no valorables: preferentes, warrants, units, fondos ---
    if profile.model is ValuationModel.EXCLUDED:
        return {**base, "excluded": True, "excluded_reason": profile.excluded_reason}

    needs_fcf = profile.model is ValuationModel.DCF
    inputs = _fetch_market_inputs(symbol, require_fcf=needs_fcf)

    beta_defaulted = any("Beta no disponible" in w for w in inputs.data_warnings)
    warnings: list[str] = list(inputs.data_warnings) + list(profile.notes)

    ke = engine.cost_of_equity_capm(
        inputs.risk_free_rate, inputs.beta, inputs.market_risk_premium
    )
    terminal_g = min(0.025, max(inputs.risk_free_rate - 0.01, 0.0))

    wacc_pct: float | None = None
    tv_share: float | None = None
    drivers: dict = {}
    history_years = len([v for v in inputs.fcf_history if v is not None])

    # ---------------- DCF clásico ----------------
    if profile.model is ValuationModel.DCF:
        assumptions = _auto_assumptions(inputs)
        result = engine.compute(inputs, assumptions)
        intrinsic = result.intrinsic_price_per_share
        warnings += result.warnings
        wacc_pct = round(result.wacc * 100, 2)
        tv_share = result.terminal_value_share
        ke = result.cost_of_equity
        drivers = {
            "base_fcf": round(result.base_fcf, 0),
            "growth_rate": round(assumptions.revenue_growth_rate, 4),
            "terminal_growth": round(assumptions.terminal_growth_rate, 4),
            "net_debt": round(result.net_debt, 0),
            "terminal_value_share": tv_share,
        }

    # ---------------- Exceso de retorno (bancos / aseguradoras) ----------------
    elif profile.model is ValuationModel.EXCESS_RETURN:
        extras = sector_data.fetch_financial_extras(
            tk, info, inputs.fx_rate, inputs.shares_outstanding
        )
        warnings += extras["warnings"]
        if extras["book_value_equity"] is None or extras["roe"] is None:
            return {
                **base, "excluded": True,
                "excluded_reason": "Sin fondos propios o ROE publicados: el modelo de "
                                   "exceso de retorno no es aplicable",
            }
        sr = sector_models.excess_return_valuation(
            book_value_equity=extras["book_value_equity"],
            roe=extras["roe"],
            payout_ratio=extras["payout_ratio"],
            cost_of_equity=ke,
            shares_outstanding=inputs.shares_outstanding,
            terminal_growth=terminal_g,
        )
        if not sr.ok:
            return {**base, "excluded": True, "excluded_reason": sr.failure_reason}
        intrinsic = sr.intrinsic_price_per_share
        warnings += sr.warnings
        ke = sr.cost_of_equity
        drivers = sr.drivers
        history_years = extras.get("roe_years", 1)

    # ---------------- AFFO (REITs) ----------------
    else:
        extras = sector_data.fetch_reit_extras(tk, info, inputs.fx_rate)
        warnings += extras["warnings"]
        if not extras["ffo"]:
            return {
                **base, "excluded": True,
                "excluded_reason": "FFO no calculable: sin beneficio neto o amortizaciones "
                                   "publicados para el REIT",
            }
        ffo_hist = extras.get("ffo_history") or []
        growth = engine._calibrate_base_growth(ffo_hist) * 0.70 if len(ffo_hist) >= 2 else 0.02
        sr = sector_models.reit_affo_valuation(
            ffo=extras["ffo"], affo=extras.get("affo"),
            cost_of_equity=ke, shares_outstanding=inputs.shares_outstanding,
            growth_rate=growth, terminal_growth=terminal_g,
        )
        if not sr.ok:
            return {**base, "excluded": True, "excluded_reason": sr.failure_reason}
        intrinsic = sr.intrinsic_price_per_share
        warnings += sr.warnings
        ke = sr.cost_of_equity
        drivers = sr.drivers
        tv_share = sr.drivers.get("terminal_share_of_value")
        history_years = max(len(ffo_hist), 1)

    # ---------------- Control de plausibilidad ----------------
    guard = valuation_guard.evaluate(
        intrinsic_price=intrinsic,
        current_price=inputs.current_price,
        model=profile.model.value,
        fcf_years=history_years,
        terminal_value_share=tv_share,
        fx_converted=inputs.financial_currency != inputs.currency,
        fx_supported=fx_engine.is_supported(inputs.financial_currency),
        warnings=warnings,
        beta_defaulted=beta_defaulted,
    )
    if not guard.accepted:
        return {**base, "excluded": True, "excluded_reason": guard.rejection_reason}

    # ---------------- Veredicto ----------------
    net_debt = inputs.total_debt - inputs.cash_and_equivalents
    verdict = engine.compute_verdict(
        intrinsic_price=intrinsic,
        current_price=inputs.current_price,
        cost_of_equity=ke,
        beta=inputs.beta,
        net_debt=net_debt,
        market_cap=inputs.market_cap,
        sector=inputs.sector,
    )
    verdict_label = verdict.verdict
    key_risk = verdict.key_risk

    # Calidad y supervivencia (Altman Z / Piotroski F) — puede vetar la compra
    try:
        quality = compute_quality_metrics(
            ticker_symbol=symbol,
            current_price=inputs.current_price,
            market_cap=inputs.market_cap,
        )
        if quality and quality.verdict_override:
            verdict_label = "SELL/AVOID"
            key_risk = quality.override_reason or key_risk
    except Exception as e:
        logger.warning(f"Quality check failed for {symbol}: {e}")

    # Una confianza baja o un descuento sospechoso nunca deben emitir una orden
    # de compra: se degrada a seguimiento y se explica el motivo.
    if verdict_label == "STRONG BUY" and guard.confidence_label == "BAJA":
        verdict_label = "HOLD/MONITOR"
        key_risk = (
            "Descuento aparente elevado pero calidad de datos baja — "
            "verificar las cuentas antes de invertir. " + key_risk
        )

    return {
        **base,
        "current_price": round(inputs.current_price, 2),
        "intrinsic_price": round(intrinsic, 2),
        "mos_pct": round(verdict.margin_of_safety, 2),
        "upside_pct": round((intrinsic - inputs.current_price) / inputs.current_price * 100, 2),
        "expected_return_pct": round(verdict.expected_return * 100, 2),
        "hurdle_rate_pct": round(verdict.hurdle_rate * 100, 2),
        "clears_hurdle": verdict.clears_hurdle,
        "beta": round(inputs.beta, 2),
        "wacc_pct": wacc_pct,
        "cost_of_equity_pct": round(ke * 100, 2),
        "market_cap": round(inputs.market_cap, 0),
        "verdict": verdict_label,
        "key_risk": key_risk,
        "confidence": guard.confidence,
        "confidence_label": guard.confidence_label,
        "flags": guard.flags,
        "warnings": warnings,
        "financial_currency": inputs.financial_currency,
        "fx_rate": round(inputs.fx_rate, 8),
        "drivers": drivers,
    }


def _screener_valuator(ticker: str) -> Optional[dict]:
    """
    Fila compacta para el screener. Devuelve None cuando la empresa queda
    excluida (instrumento no valorable, datos insuficientes o resultado
    implausible), de modo que nunca contamine el ranking.
    """
    row = _value_by_model(ticker)
    if row.get("excluded"):
        logger.info(f"Screener: {ticker} excluido — {row.get('excluded_reason')}")
        return None
    return row


class UniverseTickerRequest(BaseModel):
    ticker: str


class UniverseReplaceRequest(BaseModel):
    tickers: list[str]


@app.get("/api/screener")
def get_screener():
    """Return the last cached ranked screener results + live scan status."""
    return screener_engine.get_status()


@app.get("/api/screener/status")
def get_screener_status():
    """Lightweight status poll used by the UI while a scan runs."""
    return screener_engine.get_status()


@app.post("/api/screener/scan")
def start_screener_scan(fresh: bool = False):
    """
    Kick off a live background scan of the whole universe, ranking by MoS.
    Returns immediately; poll /api/screener/status for progress + partial results.

    By default the scan RESUMES from the last cached results (skipping tickers
    already valued) so an interrupted multi-hour scan of the full small/mid-cap
    universe can continue. Pass ?fresh=true to start over from scratch.
    """
    return screener_engine.start_scan(_screener_valuator, resume=not fresh)


@app.post("/api/screener/universe/refresh")
def refresh_screener_universe():
    """
    Rebuild the universe by pulling the full US small/mid-cap list ($300M–$10B)
    from Yahoo Finance's screener. Runs in the background; poll
    /api/screener/status and read `universe_refresh` for progress.
    """
    return screener_engine.refresh_universe_async()


@app.get("/api/screener/universe")
def get_screener_universe():
    return {"tickers": screener_engine.load_universe()}


@app.post("/api/screener/universe")
def replace_screener_universe(body: UniverseReplaceRequest):
    return {"tickers": screener_engine.save_universe(body.tickers)}


@app.post("/api/screener/universe/add")
def add_screener_ticker(body: UniverseTickerRequest):
    return {"tickers": screener_engine.add_ticker(body.ticker)}


@app.post("/api/screener/universe/remove")
def remove_screener_ticker(body: UniverseTickerRequest):
    return {"tickers": screener_engine.remove_ticker(body.ticker)}
