"""
Sector Models — Valoración para negocios donde el DCF sobre FCF no aplica
=========================================================================
Dos modelos alternativos, ambos sobre FLUJO AL ACCIONISTA (por tanto descontados
al coste de los fondos propios Ke, y SIN restar deuda neta — ese es justamente
el error conceptual que se busca evitar).

1. Exceso de Retorno — bancos, aseguradoras y bróker-dealers
   ---------------------------------------------------------
   Valor del equity = BV₀ + Σ VA(Exceso de Retorno_t) + VA(Terminal)

     Exceso de Retorno_t = (ROE_t − Ke) × BV_{t−1}
     BV_t = BV_{t−1} × (1 + ROE_t × tasa de retención)

   Intuición: un banco sólo crea valor por encima de sus fondos propios
   contables si obtiene un ROE superior al coste del capital. Si ROE = Ke, la
   acción vale exactamente su valor en libros. Referencia: Damodaran,
   "Valuing Financial Service Firms" (2013).

   El ROE revierte linealmente hacia un ROE sostenible (Ke + prima estrecha):
   ninguna entidad mantiene un ROE del 25 % a perpetuidad bajo competencia.

2. AFFO — REITs
   -------------
   Valor del equity = Σ VA(AFFO_t @ Ke) + VA(Terminal @ Ke)

     FFO  = Beneficio neto + Amortizaciones − plusvalías por venta de activos
     AFFO = FFO − capex recurrente de mantenimiento

   El FCF contable de un REIT está estructuralmente deprimido por el capex
   inmobiliario, lo que hace que el DCF los infravalore siempre. El AFFO es la
   métrica que usa el propio sector, y es un flujo YA neto de intereses: por eso
   se descuenta a Ke y no se le resta la deuda.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger("sector-models")


@dataclass
class SectorValuationResult:
    model: str                      # "EXCESS_RETURN" | "REIT_AFFO"
    intrinsic_price_per_share: float
    equity_value: float
    cost_of_equity: float
    drivers: dict                   # magnitudes clave para auditar en la UI
    warnings: list[str] = field(default_factory=list)
    ok: bool = True
    failure_reason: str | None = None

    @staticmethod
    def failed(model: str, reason: str) -> "SectorValuationResult":
        return SectorValuationResult(
            model=model, intrinsic_price_per_share=0.0, equity_value=0.0,
            cost_of_equity=0.0, drivers={}, ok=False, failure_reason=reason,
        )


# ---------------------------------------------------------------------------
# 1 — Modelo de Exceso de Retorno (bancos / aseguradoras)
# ---------------------------------------------------------------------------

# Un ROE fuera de esta banda es casi siempre un artefacto contable (cargo
# extraordinario, fondos propios casi nulos) y no una capacidad de generación real.
_ROE_MIN, _ROE_MAX = -0.25, 0.35
# Prima sostenible sobre Ke en el estado estacionario para una entidad SIN
# ventaja competitiva: la competencia erosiona el exceso de retorno.
_TERMINAL_ROE_SPREAD = 0.015
# Fracción del exceso de retorno actual que se considera estructural y sobrevive
# al horizonte de proyección. Converger a Ke + 1,5 % a TODAS las entidades por
# igual trataba a JPMorgan como a un banco regional cualquiera y las valoraba a
# todas por debajo de su valor en libros. Una franquicia con depósitos baratos y
# marca conserva parte de su ventaja de forma persistente.
_FRANCHISE_PERSISTENCE = 0.35


def excess_return_valuation(
    *,
    book_value_equity: float,
    roe: float,
    payout_ratio: float,
    cost_of_equity: float,
    shares_outstanding: float,
    terminal_growth: float,
    years: int = 10,
) -> SectorValuationResult:
    """
    Valora una entidad financiera por exceso de retorno sobre fondos propios.
    Todos los importes deben venir YA convertidos a la moneda de cotización.
    """
    warnings: list[str] = []
    m = "EXCESS_RETURN"

    if not math.isfinite(book_value_equity) or book_value_equity <= 0:
        return SectorValuationResult.failed(
            m, "Fondos propios contables nulos o negativos: el modelo de exceso "
               "de retorno no es aplicable"
        )
    if shares_outstanding <= 0:
        return SectorValuationResult.failed(m, "Número de acciones no disponible")
    if not math.isfinite(roe):
        return SectorValuationResult.failed(m, "ROE no disponible")

    ke = float(np.clip(cost_of_equity, 0.05, 0.20))
    if ke != cost_of_equity:
        warnings.append(f"Coste de los fondos propios acotado a {ke:.1%} (rango razonable 5–20 %)")

    roe0 = float(np.clip(roe, _ROE_MIN, _ROE_MAX))
    if abs(roe0 - roe) > 1e-9:
        warnings.append(
            f"ROE de partida {roe:.1%} acotado a {roe0:.1%}: fuera de rango es un artefacto contable"
        )

    # Crecimiento terminal siempre por debajo de Ke, o la perpetuidad diverge.
    g = float(min(terminal_growth, ke - 0.02))
    if g < 0:
        g = 0.0

    payout = float(np.clip(payout_ratio, 0.0, 0.95))
    retention = 1.0 - payout

    # ROE sostenible en el estado estacionario. El ROE observado converge hacia
    # él de forma lineal a lo largo del horizonte de proyección, conservando la
    # parte del exceso atribuible a una franquicia duradera.
    # La reversión se aplica en AMBOS sentidos. Aplicarla sólo a la baja
    # (penalizar al banco rentable pero no reconocer recuperación al que hoy no
    # cubre su coste de capital) generaba un sesgo sistemático: TODAS las
    # entidades salían sobrevaloradas. Un banco por debajo de su coste de
    # capital no permanece ahí a perpetuidad — reestructura, encoge, cambia de
    # ciclo de tipos o es absorbido.
    competitive_floor = ke + _TERMINAL_ROE_SPREAD
    terminal_roe = competitive_floor + _FRANCHISE_PERSISTENCE * (roe0 - competitive_floor)

    bv = float(book_value_equity)
    pv_excess = 0.0
    path: list[dict] = []

    for t in range(1, years + 1):
        # Reversión lineal del ROE hacia el sostenible
        w = t / years
        roe_t = roe0 * (1 - w) + terminal_roe * w
        excess = (roe_t - ke) * bv
        pv = excess / (1 + ke) ** t
        pv_excess += pv
        path.append({
            "year": t, "roe": round(roe_t, 4), "book_value": round(bv, 0),
            "excess_return": round(excess, 0), "pv": round(pv, 0),
        })
        # El crecimiento de los fondos propios se autofinancia con lo retenido
        bv *= 1 + max(roe_t, 0.0) * retention

    # Terminal: exceso de retorno del año n+1 en perpetuidad con crecimiento g.
    terminal_excess = (terminal_roe - ke) * bv
    if ke - g > 0.001:
        tv = terminal_excess * (1 + g) / (ke - g)
    else:
        tv = 0.0
        warnings.append("Diferencial Ke−g insuficiente: valor terminal anulado por prudencia")
    pv_tv = tv / (1 + ke) ** years

    equity_value = book_value_equity + pv_excess + pv_tv

    if equity_value <= 0:
        return SectorValuationResult.failed(
            m, "El modelo arroja un valor del equity nulo o negativo "
               "(la entidad destruye valor sobre sus fondos propios)"
        )

    intrinsic = equity_value / shares_outstanding

    return SectorValuationResult(
        model=m,
        intrinsic_price_per_share=intrinsic,
        equity_value=equity_value,
        cost_of_equity=ke,
        drivers={
            "book_value_equity": round(book_value_equity, 0),
            "book_value_per_share": round(book_value_equity / shares_outstanding, 4),
            "roe_initial": round(roe0, 4),
            "roe_terminal": round(terminal_roe, 4),
            "payout_ratio": round(payout, 4),
            "retention_ratio": round(retention, 4),
            "terminal_growth": round(g, 4),
            "pv_excess_returns": round(pv_excess, 0),
            "pv_terminal": round(pv_tv, 0),
            "projection_years": years,
            "path": path,
        },
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 2 — Modelo AFFO (REITs)
# ---------------------------------------------------------------------------

# Fracción del FFO que sobrevive al capex recurrente de mantenimiento cuando no
# se puede aislar del capex de expansión en los estados publicados. 85 % es el
# convenio habitual del sector (NAREIT) y es deliberadamente conservador.
_AFFO_HAIRCUT = 0.85
# Los alquileres crecen con la inflación y poco más: un REIT que crezca al 8 %
# a perpetuidad es una hipótesis insostenible.
_REIT_GROWTH_CAP = 0.04


def reit_affo_valuation(
    *,
    ffo: float,
    cost_of_equity: float,
    shares_outstanding: float,
    growth_rate: float,
    terminal_growth: float,
    affo: float | None = None,
    years: int = 10,
) -> SectorValuationResult:
    """
    Valora un REIT descontando su AFFO al coste de los fondos propios.
    NO se resta deuda neta: el AFFO ya es un flujo posterior a intereses.
    """
    warnings: list[str] = []
    m = "REIT_AFFO"

    if shares_outstanding <= 0:
        return SectorValuationResult.failed(m, "Número de acciones no disponible")

    if affo is None or not math.isfinite(affo) or affo <= 0:
        if not math.isfinite(ffo) or ffo <= 0:
            return SectorValuationResult.failed(
                m, "FFO no disponible o negativo: el REIT no genera fondos de operaciones "
                   "normalizables"
            )
        affo = ffo * _AFFO_HAIRCUT
        warnings.append(
            f"Capex de mantenimiento no aislable: AFFO estimado como {_AFFO_HAIRCUT:.0%} del FFO"
        )

    ke = float(np.clip(cost_of_equity, 0.06, 0.16))
    if abs(ke - cost_of_equity) > 1e-9:
        warnings.append(f"Coste de los fondos propios acotado a {ke:.1%} para un REIT")

    g = float(np.clip(growth_rate, -0.05, _REIT_GROWTH_CAP))
    if g < growth_rate:
        warnings.append(
            f"Crecimiento del AFFO acotado al {_REIT_GROWTH_CAP:.0%}: los alquileres "
            "no crecen indefinidamente por encima de la inflación"
        )
    gt = float(min(terminal_growth, ke - 0.02, 0.025))
    if gt < 0:
        gt = 0.0

    pv_sum = 0.0
    projected: list[float] = []
    for t in range(1, years + 1):
        cf = affo * (1 + g) ** t
        projected.append(cf)
        pv_sum += cf / (1 + ke) ** t

    if ke - gt > 0.001:
        tv = projected[-1] * (1 + gt) / (ke - gt)
    else:
        tv = 0.0
        warnings.append("Diferencial Ke−g insuficiente: valor terminal anulado por prudencia")
    pv_tv = tv / (1 + ke) ** years

    equity_value = pv_sum + pv_tv
    if equity_value <= 0:
        return SectorValuationResult.failed(m, "Valor del equity nulo o negativo")

    intrinsic = equity_value / shares_outstanding

    return SectorValuationResult(
        model=m,
        intrinsic_price_per_share=intrinsic,
        equity_value=equity_value,
        cost_of_equity=ke,
        drivers={
            "ffo": round(ffo, 0) if math.isfinite(ffo) else None,
            "affo": round(affo, 0),
            "affo_per_share": round(affo / shares_outstanding, 4),
            "growth_rate": round(g, 4),
            "terminal_growth": round(gt, 4),
            "pv_affo": round(pv_sum, 0),
            "pv_terminal": round(pv_tv, 0),
            "terminal_share_of_value": round(pv_tv / equity_value, 4) if equity_value else None,
            "projection_years": years,
        },
        warnings=warnings,
    )
