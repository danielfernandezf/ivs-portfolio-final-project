"""
Valuation Engine — DCF + WACC + CAPM
======================================
Mathematical core derived from Risk-Return Analysis (Schoenmaker & Schramade, 2023).

Key equations implemented:
  CAPM  (Eq. 12.15): r_i = r_f + β_i × (E[r_MKT] − r_f)
  Beta  (Eq. 12.13): β_i = (σ_i × ρ_{i,mp}) / σ_mp
  WACC            : (E/V) × r_e + (D/V) × r_d × (1 − T)
  DCF             : Enterprise Value = Σ FCF_t/(1+WACC)^t  +  TV/(1+WACC)^n
  Terminal Value  : TV = FCF_n × (1 + g_terminal) / (WACC − g_terminal)
  Equity Value    : EV − Net Debt  (Net Debt = Total Debt − Cash)

ISOLATION GUARANTEE: This module is PURE FUNDAMENTAL ANALYSIS.
No probabilistic / technical / speculative math enters here.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math
import numpy as np


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class MarketInputs:
    """Raw market data fetched from yfinance."""
    ticker: str
    company_name: str
    current_price: float
    beta: float
    shares_outstanding: float          # units
    total_debt: float                  # USD
    cash_and_equivalents: float        # USD
    risk_free_rate: float              # decimal  (e.g. 0.042)
    market_risk_premium: float         # decimal  (historical avg ~0.055)
    cost_of_debt_pretax: float         # decimal  (e.g. 0.05)
    effective_tax_rate: float          # decimal  (e.g. 0.21)
    fcf_history: list[float]           # last 3–5 years of Free Cash Flow (USD)
    market_cap: float                  # USD
    sector: str
    currency: str = "USD"              # moneda de COTIZACIÓN — la de todo el modelo

    # --- Trazabilidad de la normalización de divisa ---
    # Los ADR extranjeros publican sus cuentas en `financial_currency` mientras
    # cotizan en `currency`. Todos los importes de arriba llegan YA convertidos a
    # `currency`; estos campos conservan de dónde vienen para poder auditarlo.
    financial_currency: str = "USD"
    fx_rate: float = 1.0
    industry: str = "N/A"
    data_warnings: list[str] = field(default_factory=list)


@dataclass
class DCFAssumptions:
    """
    Scenario assumptions — frontend sliders write here.
    Defaults come from the engine's auto-calibration.
    """
    revenue_growth_rate: float         # year 1-5 growth applied to FCF
    fcf_margin: float                  # fraction of revenue used as FCF margin override
    terminal_growth_rate: float        # perpetuity growth (g) — must be < WACC
    wacc_override: Optional[float] = None  # if set, bypasses computed WACC
    projection_years: int = 5


@dataclass
class InvestmentVerdict:
    """
    Investment Committee decision output.
    Based on Margin of Safety (Graham) and CAPM expected return comparison.
    """
    verdict: str                    # "STRONG BUY" | "HOLD/MONITOR" | "SELL/AVOID"
    margin_of_safety: float         # (intrinsic - price) / intrinsic × 100
    expected_return: float          # (intrinsic - price) / price  — decimal
    hurdle_rate: float              # cost_of_equity (CAPM) — the benchmark to beat
    clears_hurdle: bool             # expected_return > cost_of_equity
    key_risk: str                   # one-line primary risk narrative
    rationale: str                  # two-sentence investment committee rationale


@dataclass
class ValuationResult:
    ticker: str
    company_name: str
    current_price: float

    # CAPM / WACC decomposition
    cost_of_equity: float
    cost_of_debt_aftertax: float
    equity_weight: float
    debt_weight: float
    wacc: float

    # DCF outputs
    base_fcf: float                    # FCF used as year-0 anchor
    projected_fcfs: list[float]        # 5 projected FCF values
    pv_fcfs: list[float]               # PV of each projected FCF
    terminal_value: float
    pv_terminal_value: float
    enterprise_value: float
    net_debt: float
    equity_value: float
    intrinsic_price_per_share: float

    # Sensitivity handles
    assumptions: DCFAssumptions
    market_inputs: MarketInputs

    # Margin of safety vs current price
    upside_downside_pct: float         # positive = undervalued

    # Investment Committee verdict
    verdict: InvestmentVerdict

    # Trazabilidad: avisos de normalización y peso del valor terminal.
    # Una valoración en la que el terminal supone el 90 % del valor no es una
    # valoración, es una apuesta sobre la perpetuidad — y el usuario debe verlo.
    warnings: list[str] = field(default_factory=list)
    terminal_value_share: float = 0.0


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class ValuationEngine:
    """
    Stateless calculator.  Call `compute(inputs, assumptions)` to get a
    ValuationResult.  All math is traceable to the PDF equations cited above.
    """

    MARKET_RISK_PREMIUM_DEFAULT = 0.055   # ~5.5% historical ERP (Table 12.1 average)

    # --- Guardarraíles del coste de los fondos propios ---
    # yfinance publica betas manifiestamente erróneas para valores poco líquidos
    # y ADR extranjeros (BBAR 0.03, KT 0.05, IRS 0.04 en el escaneo real). Una
    # beta de 0.03 implicaría exigirle a una acción casi el tipo libre de riesgo,
    # lo que dispara el valor intrínseco. Se acota a un rango defendible.
    BETA_FLOOR = 0.35
    BETA_CAP = 2.50
    # Ninguna acción es menos arriesgada que el bono soberano: se exige una prima
    # mínima sobre el tipo libre de riesgo y un suelo absoluto acorde con el
    # retorno histórico de la renta variable.
    MIN_EQUITY_SPREAD = 0.035
    COST_OF_EQUITY_FLOOR = 0.070
    COST_OF_EQUITY_CAP = 0.200

    # El WACC es siempre ≤ Ke (la deuda es más barata), pero un WACC por debajo
    # del 6,5 % hace estallar la perpetuidad de Gordon.
    WACC_FLOOR = 0.065
    WACC_CAP = 0.180
    # Diferencial mínimo WACC − g. Con un diferencial de 0,001 (el guardarraíl
    # anterior) el valor terminal alcanzaba 1.000 veces el FCF. Un 2 % mantiene
    # el múltiplo terminal por debajo de ~50x en el peor caso.
    MIN_TERMINAL_SPREAD = 0.020

    # ------------------------------------------------------------------
    # CAPM  —  Eq. 12.15
    # r_i = r_f + β_i × (E[r_MKT] − r_f)
    # ------------------------------------------------------------------
    @classmethod
    def cost_of_equity_capm(
        cls,
        risk_free_rate: float,
        beta: float,
        market_risk_premium: float,
    ) -> float:
        """
        CAPM cost of equity, con los guardarraíles descritos arriba.
        Source: Risk-Return Analysis, Eq. 12.15
        """
        b = float(np.clip(beta, cls.BETA_FLOOR, cls.BETA_CAP))
        raw = risk_free_rate + b * market_risk_premium
        floor = max(risk_free_rate + cls.MIN_EQUITY_SPREAD, cls.COST_OF_EQUITY_FLOOR)
        return float(np.clip(raw, floor, cls.COST_OF_EQUITY_CAP))

    # ------------------------------------------------------------------
    # WACC
    # WACC = (E/V) × r_e  +  (D/V) × r_d × (1 − T)
    # ------------------------------------------------------------------
    @staticmethod
    def compute_wacc(
        cost_of_equity: float,
        cost_of_debt_pretax: float,
        tax_rate: float,
        market_cap: float,
        total_debt: float,
    ) -> tuple[float, float, float]:
        """
        Returns (wacc, equity_weight, debt_weight).
        Source: Risk-Return Analysis, Chapter 13 reference (Eq. 12.21 pattern).
        """
        total_capital = market_cap + total_debt
        if total_capital <= 0:
            return cost_of_equity, 1.0, 0.0

        e_weight = market_cap / total_capital
        d_weight = total_debt / total_capital
        cost_of_debt_aftertax = cost_of_debt_pretax * (1 - tax_rate)

        wacc = e_weight * cost_of_equity + d_weight * cost_of_debt_aftertax
        return wacc, e_weight, d_weight

    # ------------------------------------------------------------------
    # FCF growth calibration
    # ------------------------------------------------------------------
    @staticmethod
    def _calibrate_base_growth(fcf_history: list[float]) -> float:
        """
        Tasa de crecimiento histórica del FCF, en decimal, acotada a [-0.30, +0.50].

        Se compara la media de la PRIMERA mitad del histórico con la de la
        SEGUNDA y se anualiza el cociente. Es el estimador adecuado para series
        cortas y ruidosas, y evita dos sesgos:

          · CAGR punto-a-punto (implementación original): queda determinada por
            sólo dos ejercicios. Si el primero fue un valle o el último un pico,
            el crecimiento proyectado se dispara.
          · Mediana de variaciones interanuales: sesgada en series oscilantes.
            Con el FCF de Apple [111,4 · 99,6 · 108,8 · 98,8] —plano en la
            práctica— dos de las tres variaciones son negativas y la mediana
            arroja −9,2 % anual, proyectando un declive inexistente.

        Promediando mitades, ese mismo histórico devuelve −0,8 %: plano, que es
        la lectura correcta.
        """
        clean = [v for v in fcf_history if v is not None and v != 0]
        if len(clean) < 2:
            return 0.05  # sin histórico suficiente: 5 % neutro

        if len(clean) == 2:
            prev, curr = clean
            if prev <= 0:
                return 0.05
            return float(np.clip(curr / prev - 1, -0.30, 0.50))

        mid = len(clean) // 2
        first, second = clean[:mid], clean[mid:]
        avg_first = sum(first) / len(first)
        avg_second = sum(second) / len(second)

        if avg_first <= 0:
            # Base negativa: no hay tasa de crecimiento definible sobre ella.
            # Una salida de pérdidas es una recuperación, no una tendencia
            # extrapolable a cinco años.
            return 0.0 if avg_second > 0 else -0.10

        # Separación temporal entre los centros de gravedad de ambas mitades
        span = (len(clean) - 1) / 2 or 1
        cagr = (avg_second / avg_first) ** (1 / span) - 1
        return float(np.clip(cagr, -0.30, 0.50))

    # ------------------------------------------------------------------
    # Normalización del FCF de partida
    # ------------------------------------------------------------------
    # Desviación relativa por encima de la cual el último ejercicio se considera
    # atípico y se sustituye por la media del período.
    _FCF_OUTLIER_TOLERANCE = 0.50

    @classmethod
    def normalize_base_fcf(cls, fcf_history: list[float]) -> tuple[float, str | None]:
        """
        Devuelve (fcf_base, aviso).

        El ancla del DCF era el FCF del último ejercicio. Un único año malo
        (una adquisición, una devolución de impuestos, un ciclo de capex)
        arrastraba toda la proyección a cinco años y el valor terminal. Se
        sustituye por el último ejercicio SÓLO cuando es representativo de la
        media reciente; en caso contrario se normaliza.
        """
        clean = [v for v in fcf_history if v is not None and math.isfinite(v)]
        if not clean:
            return 0.0, "Sin histórico de flujo de caja libre"

        recent = clean[-3:] if len(clean) >= 3 else clean
        mean_recent = sum(recent) / len(recent)
        latest = clean[-1]

        if any(v < 0 for v in clean):
            return mean_recent, (
                "El histórico contiene ejercicios con flujo de caja negativo: "
                f"se normaliza el FCF de partida a la media de {len(recent)} años"
            )

        if len(recent) >= 2 and mean_recent > 0:
            deviation = abs(latest - mean_recent) / mean_recent
            if deviation > cls._FCF_OUTLIER_TOLERANCE:
                return mean_recent, (
                    f"El último ejercicio se desvía un {deviation:.0%} de la media reciente: "
                    "se toma la media como base para no extrapolar un año atípico"
                )

        return latest, None

    # ------------------------------------------------------------------
    # DCF projection
    # ------------------------------------------------------------------
    @staticmethod
    def project_fcfs(
        base_fcf: float,
        growth_rate: float,
        years: int,
    ) -> list[float]:
        """Project FCF for `years` periods at constant `growth_rate`."""
        return [base_fcf * (1 + growth_rate) ** t for t in range(1, years + 1)]

    # ------------------------------------------------------------------
    # Present value helpers
    # ------------------------------------------------------------------
    @staticmethod
    def present_value(cash_flows: list[float], discount_rate: float) -> list[float]:
        """Discount each cash flow to PV at t=0."""
        return [cf / (1 + discount_rate) ** (t + 1) for t, cf in enumerate(cash_flows)]

    @classmethod
    def terminal_value(
        cls,
        last_fcf: float,
        terminal_growth: float,
        wacc: float,
    ) -> float:
        """
        Gordon Growth Model terminal value at end of projection horizon.
        TV = FCF_n × (1 + g) / (WACC − g)

        El diferencial WACC − g se acota por abajo a MIN_TERMINAL_SPREAD. El
        guardarraíl anterior (0,001) no protegía de nada: convertía una empresa
        con WACC ≈ g en un valor terminal de ~1.000 veces su FCF, que era la
        principal fuente de valoraciones desorbitadas.
        """
        spread = max(wacc - terminal_growth, cls.MIN_TERMINAL_SPREAD)
        return last_fcf * (1 + terminal_growth) / spread

    # ------------------------------------------------------------------
    # Investment Committee Verdict
    # ------------------------------------------------------------------
    @staticmethod
    def compute_verdict(
        intrinsic_price: float,
        current_price: float,
        cost_of_equity: float,
        beta: float,
        net_debt: float,
        market_cap: float,
        sector: str,
    ) -> InvestmentVerdict:
        """
        Generate an investment committee verdict using:
          - Margin of Safety = (intrinsic − price) / intrinsic × 100
            (Graham's MoS — guards against estimation error)
          - Expected Return = (intrinsic − price) / price
            (holding-period return to fair value)
          - Hurdle Rate = cost_of_equity via CAPM (Eq. 12.15)
            (minimum return investors require for the systematic risk taken)

        Decision rule:
          MoS > 20% AND expected_return > hurdle_rate → STRONG BUY
          0% ≤ MoS ≤ 20%                              → HOLD/MONITOR
          MoS < 0%                                     → SELL/AVOID
        """
        # Margin of Safety (Graham definition)
        if intrinsic_price > 0:
            mos = (intrinsic_price - current_price) / intrinsic_price * 100
        else:
            mos = -100.0

        # Expected return (price appreciation to fair value)
        if current_price > 0:
            exp_return = (intrinsic_price - current_price) / current_price
        else:
            exp_return = 0.0

        clears_hurdle = exp_return > cost_of_equity
        leverage_ratio = net_debt / market_cap if market_cap > 0 else 0.0

        # --- Key Risk narrative (sector-aware) ---
        if mos < 0:
            key_risk = (
                f"Significant overvaluation detected ({abs(mos):.1f}% premium to intrinsic). "
                "Entry at current price offers no margin of safety."
            )
        elif beta > 1.5:
            key_risk = (
                f"High systematic risk (β={beta:.2f}). "
                "Price is highly sensitive to broad market drawdowns."
            )
        elif leverage_ratio > 0.5:
            key_risk = (
                f"Elevated financial leverage (Net Debt / MCap = {leverage_ratio:.1f}x). "
                "Rising rates or earnings miss could compress equity value sharply."
            )
        elif "tech" in sector.lower() or "software" in sector.lower():
            key_risk = (
                "Terminal value dominates DCF (growth-dependent valuation). "
                "Competitive disruption or multiple compression are primary risks."
            )
        elif "energy" in sector.lower() or "material" in sector.lower():
            key_risk = (
                "FCF highly sensitive to commodity price cycles. "
                "Terminal growth assumption may overstate long-run earnings power."
            )
        else:
            key_risk = (
                "Model sensitivity to WACC: a +100bps increase reduces intrinsic value by ~10–15%. "
                "Validate assumptions against sector peers before deploying capital."
            )

        # --- Verdict ---
        if mos > 20.0 and clears_hurdle:
            verdict = "STRONG BUY"
            rationale = (
                f"The stock trades at a {mos:.1f}% discount to our DCF intrinsic value, "
                f"exceeding the 20% minimum margin of safety threshold. "
                f"The expected return of {exp_return:.1%} clears the CAPM hurdle rate of "
                f"{cost_of_equity:.1%}, compensating investors adequately for systematic risk. "
                f"Risk-reward is asymmetric in favour of the long position."
            )
        elif 0.0 <= mos <= 20.0:
            verdict = "HOLD/MONITOR"
            rationale = (
                f"The stock appears fairly valued with a margin of safety of {mos:.1f}%, "
                f"below the 20% threshold required for a strong conviction entry. "
                f"{'The expected return clears the CAPM hurdle — initiate on weakness.' if clears_hurdle else 'The expected return does not yet compensate for the cost of equity — wait for a better entry.'}"
            )
        else:
            verdict = "SELL/AVOID"
            rationale = (
                f"The stock is trading at a {abs(mos):.1f}% premium to intrinsic value. "
                f"There is negative margin of safety; the market is pricing in optimistic assumptions "
                f"not yet reflected in historical FCF generation. "
                f"The position offers unfavourable risk-reward at current levels."
            )

        return InvestmentVerdict(
            verdict=verdict,
            margin_of_safety=round(mos, 2),
            expected_return=round(exp_return, 6),
            hurdle_rate=round(cost_of_equity, 6),
            clears_hurdle=clears_hurdle,
            key_risk=key_risk,
            rationale=rationale,
        )

    # ------------------------------------------------------------------
    # Main computation entry point
    # ------------------------------------------------------------------
    def compute(
        self,
        inputs: MarketInputs,
        assumptions: DCFAssumptions,
    ) -> ValuationResult:
        """
        End-to-end DCF valuation.
        Returns a fully populated ValuationResult.
        """
        # --- 1. Cost of Equity (CAPM, Eq. 12.15) ---
        r_e = self.cost_of_equity_capm(
            inputs.risk_free_rate,
            inputs.beta,
            inputs.market_risk_premium,
        )

        # --- 2. WACC ---
        if assumptions.wacc_override is not None:
            wacc = assumptions.wacc_override
            # Reverse-engineer approximate weights for display
            e_weight = inputs.market_cap / max(inputs.market_cap + inputs.total_debt, 1)
            d_weight = 1 - e_weight
        else:
            wacc, e_weight, d_weight = self.compute_wacc(
                r_e,
                inputs.cost_of_debt_pretax,
                inputs.effective_tax_rate,
                inputs.market_cap,
                inputs.total_debt,
            )
            # --- Guardarraíles del WACC ---
            # Se sustituye la antigua lista blanca de "Big Tech" (que rebajaba a
            # mano el descuento de ocho tickers concretos) por un rango aplicable
            # a cualquier empresa. Un WACC demasiado bajo es peligrosísimo: con
            # g = 2,5 %, pasar de un WACC del 9 % al 7 % multiplica por 1,7 el
            # valor terminal, que es donde se concentra la mayor parte del valor.
            wacc = float(np.clip(wacc, self.WACC_FLOOR, self.WACC_CAP))

        cost_of_debt_aftertax = inputs.cost_of_debt_pretax * (1 - inputs.effective_tax_rate)

        # --- 3. FCF de partida normalizado ---
        warnings: list[str] = []
        base_fcf, fcf_warning = self.normalize_base_fcf(inputs.fcf_history)
        if fcf_warning:
            warnings.append(fcf_warning)

        # --- 4. Project FCFs ---
        growth = assumptions.revenue_growth_rate
        projected = self.project_fcfs(base_fcf, growth, assumptions.projection_years)

        # --- 5. PV of each FCF ---
        pv_list = self.present_value(projected, wacc)

        # --- 6. Terminal Value ---
        tv = self.terminal_value(projected[-1], assumptions.terminal_growth_rate, wacc)
        pv_tv = tv / (1 + wacc) ** assumptions.projection_years

        # --- 7. Enterprise Value ---
        enterprise_value = sum(pv_list) + pv_tv

        tv_share = pv_tv / enterprise_value if enterprise_value > 0 else 0.0
        if tv_share > 0.85:
            warnings.append(
                f"El valor terminal representa el {tv_share:.0%} del valor de empresa: "
                "la valoración depende casi por completo de hipótesis a perpetuidad"
            )

        # --- 8. Equity Value ---
        net_debt = inputs.total_debt - inputs.cash_and_equivalents
        equity_value = enterprise_value - net_debt

        # --- 9. Intrinsic Price per Share ---
        shares = inputs.shares_outstanding
        intrinsic_price = equity_value / shares if shares > 0 else 0.0

        # --- 10. Upside / Downside ---
        if inputs.current_price > 0:
            upside = (intrinsic_price - inputs.current_price) / inputs.current_price
        else:
            upside = 0.0

        # --- 11. Investment Committee Verdict ---
        verdict = self.compute_verdict(
            intrinsic_price=intrinsic_price,
            current_price=inputs.current_price,
            cost_of_equity=r_e,
            beta=inputs.beta,
            net_debt=net_debt,
            market_cap=inputs.market_cap,
            sector=inputs.sector,
        )

        return ValuationResult(
            ticker=inputs.ticker,
            company_name=inputs.company_name,
            current_price=inputs.current_price,
            cost_of_equity=r_e,
            cost_of_debt_aftertax=cost_of_debt_aftertax,
            equity_weight=e_weight,
            debt_weight=d_weight,
            wacc=wacc,
            base_fcf=base_fcf,
            projected_fcfs=projected,
            pv_fcfs=pv_list,
            terminal_value=tv,
            pv_terminal_value=pv_tv,
            enterprise_value=enterprise_value,
            net_debt=net_debt,
            equity_value=equity_value,
            intrinsic_price_per_share=intrinsic_price,
            assumptions=assumptions,
            market_inputs=inputs,
            upside_downside_pct=upside,
            verdict=verdict,
            warnings=warnings,
            terminal_value_share=round(tv_share, 4),
        )


# Singleton — import and use directly
engine = ValuationEngine()
