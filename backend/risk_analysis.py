"""
Risk Analysis Module — Probabilistic & Technical
==================================================
Inspired by: El Arte de Especular (José Luis Cava, 2006)

Conceptual basis:
  - Trend-following systems using momentum indicators (MACD, moving averages)
  - Fibonacci levels for support/resistance identification
  - Probability-weighted scenario analysis (bull / base / bear)
  - Volatility regimes: historical σ as proxy for future risk
  - Market sentiment: price-to-MA relationship as trend classifier

ISOLATION GUARANTEE: This module has ZERO coupling with valuation_engine.py.
It provides a supplementary risk dashboard, never modifying fundamental DCF values.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from typing import Optional


@dataclass
class TechnicalSignals:
    """Output of the technical / probabilistic risk module."""
    ticker: str

    # Trend
    trend_direction: str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    trend_strength: str           # "STRONG" | "MODERATE" | "WEAK"
    price_vs_ma50: float          # % above/below 50-day MA
    price_vs_ma200: float         # % above/below 200-day MA

    # Momentum (MACD inspired — Cava Chapter IV)
    macd_signal: str              # "BUY" | "SELL" | "NEUTRAL"
    macd_value: float
    macd_signal_line: float

    # Volatility regime
    annualised_volatility: float  # decimal (e.g. 0.25 = 25%)
    volatility_regime: str        # "LOW" | "NORMAL" | "HIGH" | "EXTREME"

    # Fibonacci retracement levels (last 52-week range)
    fib_236: float
    fib_382: float
    fib_500: float
    fib_618: float
    fib_786: float

    # Probabilistic scenarios (Cava's 3-scenario framework)
    bull_price_target: float
    base_price_target: float
    bear_price_target: float
    bull_probability: float       # decimal
    base_probability: float
    bear_probability: float
    probability_weighted_price: float

    # RSI
    rsi_14: float
    rsi_signal: str               # "OVERBOUGHT" | "OVERSOLD" | "NEUTRAL"

    # Risk score 0-100 (composite)
    risk_score: float
    risk_label: str               # "LOW" | "MODERATE" | "HIGH" | "VERY HIGH"


class TechnicalRiskAnalyser:
    """
    Pure technical / probabilistic analysis.
    Operates only on price time series — no fundamentals.
    """

    # ------------------------------------------------------------------
    # Moving averages
    # ------------------------------------------------------------------
    @staticmethod
    def _ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def _sma(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=window).mean()

    # ------------------------------------------------------------------
    # MACD (Cava Chapter IV — standard 12/26/9 parameterisation)
    # Signal: when fast EMA crosses slow EMA
    # ------------------------------------------------------------------
    @staticmethod
    def _macd(prices: pd.Series) -> tuple[float, float]:
        if len(prices) < 26:
            return 0.0, 0.0
        ema12 = TechnicalRiskAnalyser._ema(prices, 12)
        ema26 = TechnicalRiskAnalyser._ema(prices, 26)
        macd_line = ema12 - ema26
        signal_line = TechnicalRiskAnalyser._ema(macd_line, 9)
        return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])

    # ------------------------------------------------------------------
    # RSI (14-period)
    # ------------------------------------------------------------------
    @staticmethod
    def _rsi(prices: pd.Series, period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        delta = prices.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])

    # ------------------------------------------------------------------
    # Fibonacci retracements (52-week high / low)
    # ------------------------------------------------------------------
    @staticmethod
    def _fibonacci_levels(high: float, low: float) -> dict[str, float]:
        diff = high - low
        return {
            "236": high - 0.236 * diff,
            "382": high - 0.382 * diff,
            "500": high - 0.500 * diff,
            "618": high - 0.618 * diff,
            "786": high - 0.786 * diff,
        }

    # ------------------------------------------------------------------
    # Volatility regime classification
    # ------------------------------------------------------------------
    @staticmethod
    def _vol_regime(ann_vol: float) -> str:
        if ann_vol < 0.15:
            return "LOW"
        elif ann_vol < 0.30:
            return "NORMAL"
        elif ann_vol < 0.50:
            return "HIGH"
        else:
            return "EXTREME"

    # ------------------------------------------------------------------
    # Probabilistic scenario generator
    # Inspired by Cava's 3-scenario framework and the probability
    # distribution concept from Risk-Return Analysis (Fig. 12.5)
    # ------------------------------------------------------------------
    @staticmethod
    def _scenarios(
        current_price: float,
        ann_vol: float,
        trend: str,
    ) -> tuple[float, float, float, float, float, float, float]:
        """
        Generate bull / base / bear price targets and probabilities.
        Uses 1-standard-deviation bands over a 12-month horizon.
        Probabilities are tilted by trend direction (Cava's sentiment rule).
        """
        # Annual return assumptions by scenario
        bull_ret = ann_vol * 1.5
        base_ret = ann_vol * 0.3
        bear_ret = -ann_vol * 1.2

        bull_price = current_price * (1 + bull_ret)
        base_price = current_price * (1 + base_ret)
        bear_price = current_price * (1 + bear_ret)

        # Probabilities shift with trend (Cava: ride the trend)
        if trend == "BULLISH":
            p_bull, p_base, p_bear = 0.40, 0.40, 0.20
        elif trend == "BEARISH":
            p_bull, p_base, p_bear = 0.20, 0.35, 0.45
        else:
            p_bull, p_base, p_bear = 0.30, 0.40, 0.30

        pw_price = p_bull * bull_price + p_base * base_price + p_bear * bear_price
        return bull_price, base_price, bear_price, p_bull, p_base, p_bear, pw_price

    # ------------------------------------------------------------------
    # Composite risk score 0-100
    # ------------------------------------------------------------------
    @staticmethod
    def _risk_score(ann_vol: float, rsi: float, price_vs_ma200: float) -> float:
        vol_score = min(ann_vol / 0.60, 1.0) * 40          # 0-40 pts
        rsi_score = (abs(rsi - 50) / 50) * 30               # 0-30 pts (extremes = risky)
        trend_score = min(abs(price_vs_ma200) / 0.30, 1.0) * 30  # 0-30 pts
        return min(vol_score + rsi_score + trend_score, 100.0)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def analyse(
        self,
        ticker: str,
        prices: pd.Series,
        high_series: Optional[pd.Series] = None,
        low_series: Optional[pd.Series] = None,
    ) -> Optional[TechnicalSignals]:
        """
        Compute all technical signals from a daily price series.
        Pass high_series / low_series (OHLC High/Low columns) for accurate
        52-week Fibonacci levels; falls back to Close range if omitted.
        Returns None if insufficient data.
        """
        if prices is None or len(prices) < 50:
            return None

        prices = prices.dropna()
        current = float(prices.iloc[-1])

        # Moving averages
        ma50 = float(self._sma(prices, 50).iloc[-1])
        ma200_series = self._sma(prices, 200)
        ma200 = float(ma200_series.iloc[-1]) if len(prices) >= 200 else ma50

        pct_vs_50 = (current - ma50) / ma50 if ma50 else 0.0
        pct_vs_200 = (current - ma200) / ma200 if ma200 else 0.0

        # Trend classification (Cava: MA slope + price position)
        ma50_slope = float(self._sma(prices, 50).diff(5).iloc[-1])
        if current > ma50 and ma50_slope > 0:
            trend = "BULLISH"
            strength = "STRONG" if current > ma200 else "MODERATE"
        elif current < ma50 and ma50_slope < 0:
            trend = "BEARISH"
            strength = "STRONG" if current < ma200 else "MODERATE"
        else:
            trend = "NEUTRAL"
            strength = "WEAK"

        # MACD
        macd_val, macd_sig = self._macd(prices)
        if macd_val > macd_sig and macd_val > 0:
            macd_signal_str = "BUY"
        elif macd_val < macd_sig and macd_val < 0:
            macd_signal_str = "SELL"
        else:
            macd_signal_str = "NEUTRAL"

        # Volatility (annualised from daily returns)
        daily_returns = prices.pct_change().dropna()
        ann_vol = float(daily_returns.std() * np.sqrt(252))

        # Fibonacci (52-week range) — use real OHLC High/Low when available
        window = min(252, len(prices))
        if high_series is not None and low_series is not None:
            h = high_series.dropna()
            l = low_series.dropna()
            high_52 = float(h.iloc[-min(window, len(h)):].max())
            low_52  = float(l.iloc[-min(window, len(l)):].min())
        else:
            high_52 = float(prices.iloc[-window:].max())
            low_52  = float(prices.iloc[-window:].min())
        fibs = self._fibonacci_levels(high_52, low_52)

        # RSI
        rsi = self._rsi(prices)
        if rsi >= 70:
            rsi_sig = "OVERBOUGHT"
        elif rsi <= 30:
            rsi_sig = "OVERSOLD"
        else:
            rsi_sig = "NEUTRAL"

        # Scenarios
        bull_p, base_p, bear_p, p_bull, p_base, p_bear, pw = self._scenarios(
            current, ann_vol, trend
        )

        # Risk score
        score = self._risk_score(ann_vol, rsi, pct_vs_200)
        if score < 25:
            risk_label = "LOW"
        elif score < 50:
            risk_label = "MODERATE"
        elif score < 75:
            risk_label = "HIGH"
        else:
            risk_label = "VERY HIGH"

        return TechnicalSignals(
            ticker=ticker,
            trend_direction=trend,
            trend_strength=strength,
            price_vs_ma50=pct_vs_50,
            price_vs_ma200=pct_vs_200,
            macd_signal=macd_signal_str,
            macd_value=macd_val,
            macd_signal_line=macd_sig,
            annualised_volatility=ann_vol,
            volatility_regime=self._vol_regime(ann_vol),
            fib_236=fibs["236"],
            fib_382=fibs["382"],
            fib_500=fibs["500"],
            fib_618=fibs["618"],
            fib_786=fibs["786"],
            bull_price_target=bull_p,
            base_price_target=base_p,
            bear_price_target=bear_p,
            bull_probability=p_bull,
            base_probability=p_base,
            bear_probability=p_bear,
            probability_weighted_price=pw,
            rsi_14=rsi,
            rsi_signal=rsi_sig,
            risk_score=score,
            risk_label=risk_label,
        )


# Singleton
risk_analyser = TechnicalRiskAnalyser()
