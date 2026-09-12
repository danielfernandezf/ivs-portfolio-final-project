"""
Sector Data — Extracción de magnitudes específicas por modelo
==============================================================
Aísla el acceso a yfinance que necesitan los modelos sectoriales, de forma que
`sector_models.py` permanezca puro (y por tanto testeable sin red).

Todas las funciones devuelven importes YA convertidos a la moneda de cotización
aplicando `fx_rate`, porque los estados financieros vienen en `financialCurrency`
y el precio/las acciones en `currency`.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd

logger = logging.getLogger("sector-data")


def _safe(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _find_row(df: pd.DataFrame | None, *patterns: str) -> pd.Series | None:
    """
    Primera fila cuyo índice contenga TODOS los términos de alguno de los
    patrones (cada patrón es una cadena con términos separados por '+').
    Devuelve la serie ordenada cronológicamente (más reciente al final).
    """
    if df is None or df.empty:
        return None
    for pattern in patterns:
        terms = [t.strip().lower() for t in pattern.split("+") if t.strip()]
        for idx in df.index:
            label = str(idx).lower()
            if all(t in label for t in terms):
                series = df.loc[idx].dropna()
                if series.empty:
                    continue
                try:
                    return series.sort_index()
                except Exception:
                    return series
    return None


def _latest(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    try:
        return float(series.iloc[-1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Entidades financieras
# ---------------------------------------------------------------------------

def fetch_financial_extras(tk, info: dict, fx_rate: float, shares: float) -> dict:
    """
    Fondos propios, ROE y payout para el modelo de Exceso de Retorno.

    `fx_rate` convierte de la moneda de los estados financieros a la de cotización.
    """
    out: dict = {"book_value_equity": None, "roe": None, "payout_ratio": 0.0,
                 "source": [], "warnings": []}

    # --- Fondos propios: balance auditado primero, `info` como respaldo ---
    bve: float | None = None
    try:
        bs = tk.balance_sheet
        row = _find_row(
            bs,
            "total+stockholder+equity",
            "stockholders+equity",
            "total+equity+gross+minority",
            "common+stock+equity",
        )
        bve = _latest(row)
        if bve is not None:
            out["source"].append("balance_sheet")
    except Exception as exc:
        logger.debug(f"balance_sheet no disponible: {exc}")

    if bve is None or bve <= 0:
        # `bookValue` de yfinance es POR ACCIÓN y ya viene en la moneda de
        # cotización, por lo que NO debe multiplicarse por el tipo de cambio.
        bvps = _safe(info.get("bookValue"), 0.0)
        if bvps > 0 and shares > 0:
            out["book_value_equity"] = bvps * shares
            out["source"].append("info.bookValue (por acción)")
            out["_already_quote_currency"] = True
        else:
            out["warnings"].append("Fondos propios no disponibles")
    else:
        out["book_value_equity"] = bve * fx_rate

    # --- ROE NORMALIZADO ---
    # La banca y los seguros son intensamente cíclicos: el ROE de un solo
    # ejercicio captura el pico (o el valle) del ciclo y, proyectado a diez años,
    # distorsiona el valor por completo. Se promedian los ejercicios disponibles.
    try:
        fin = tk.financials
        bs = tk.balance_sheet
        ni_s = _find_row(fin, "net+income+common", "net+income")
        eq_s = _find_row(bs, "total+stockholder+equity", "stockholders+equity",
                         "common+stock+equity")
        if ni_s is not None and eq_s is not None:
            ratios = [
                float(ni_s[idx]) / float(eq_s[idx])
                for idx in ni_s.index.intersection(eq_s.index)
                if float(eq_s[idx]) > 0
            ]
            ratios = [r for r in ratios if math.isfinite(r) and -1.0 < r < 1.0]
            if ratios:
                out["roe"] = sum(ratios) / len(ratios)
                out["roe_years"] = len(ratios)
                out["source"].append(f"ROE normalizado ({len(ratios)} ejercicios)")
                if len(ratios) < 3:
                    out["warnings"].append(
                        f"ROE promediado sobre sólo {len(ratios)} ejercicio(s): "
                        "puede reflejar un punto del ciclo"
                    )
    except Exception as exc:
        logger.debug(f"ROE normalizado falló: {exc}")

    if out["roe"] is None:
        r = _safe(info.get("returnOnEquity"), float("nan"))
        if math.isfinite(r):
            # yfinance mezcla formatos: unas veces 0.12, otras 12.0
            out["roe"] = r / 100.0 if abs(r) > 1.5 else r
            out["source"].append("info.returnOnEquity (ejercicio único)")
            out["warnings"].append(
                "ROE de un solo ejercicio: sin histórico para normalizar el ciclo"
            )

    if out["roe"] is None:
        out["warnings"].append("ROE no disponible")

    # --- Payout ---
    payout = _safe(info.get("payoutRatio"), float("nan"))
    if math.isfinite(payout) and 0 <= payout <= 1.5:
        out["payout_ratio"] = min(payout, 0.95)
    else:
        # Sin dato, se asume retención plena sólo si tampoco hay dividendo.
        dy = _safe(info.get("dividendYield"), 0.0)
        out["payout_ratio"] = 0.35 if dy > 0 else 0.0
        if dy > 0:
            out["warnings"].append("Payout no disponible: se asume 35 % (típico del sector)")

    return out


# ---------------------------------------------------------------------------
# REITs
# ---------------------------------------------------------------------------

def fetch_reit_extras(tk, info: dict, fx_rate: float) -> dict:
    """
    FFO y AFFO para el modelo inmobiliario.

      FFO  = Beneficio neto + Amortizaciones − plusvalías por venta de activos
      AFFO = FFO − capex recurrente (si es aislable; si no, lo estima el modelo)
    """
    out: dict = {"ffo": None, "affo": None, "ffo_history": [], "source": [], "warnings": []}

    try:
        cf = tk.cashflow
    except Exception as exc:
        logger.debug(f"cashflow no disponible: {exc}")
        cf = None

    ni_series = _find_row(cf, "net+income+from+continuing", "net+income")
    da_series = _find_row(cf, "depreciation+amortization+depletion",
                          "depreciation+and+amortization", "depreciation")
    gain_series = _find_row(cf, "gain+loss+on+sale+of+ppe", "gain+loss+on+investment",
                            "gain+on+sale")

    if ni_series is None or da_series is None:
        # Respaldo: beneficio neto de `info` + amortizaciones de la cuenta de PyG
        ni = _safe(info.get("netIncomeToCommon"), float("nan"))
        if math.isfinite(ni):
            try:
                da = _latest(_find_row(tk.financials, "reconciled+depreciation",
                                       "depreciation"))
            except Exception:
                da = None
            if da:
                out["ffo"] = (ni + da) * fx_rate
                out["source"].append("info.netIncomeToCommon + amortizaciones de PyG")
                out["warnings"].append(
                    "FFO aproximado: no se pudieron aislar las plusvalías por venta de activos"
                )
                return out
        out["warnings"].append("FFO no calculable: faltan beneficio neto o amortizaciones")
        return out

    # Serie histórica de FFO alineando por fecha
    common = ni_series.index.intersection(da_series.index)
    history: list[float] = []
    for idx in common:
        ffo_t = float(ni_series[idx]) + float(da_series[idx])
        if gain_series is not None and idx in gain_series.index:
            # La plusvalía por venta no es flujo recurrente: se descuenta del FFO.
            ffo_t -= float(gain_series[idx])
        history.append(ffo_t * fx_rate)

    if not history:
        out["warnings"].append("FFO no calculable: series de beneficio y amortización sin fechas comunes")
        return out

    out["ffo_history"] = history
    out["ffo"] = history[-1]
    out["source"].append("beneficio neto + amortizaciones − plusvalías (estado de flujos)")
    if gain_series is None:
        out["warnings"].append(
            "Plusvalías por venta de activos no identificadas: el FFO puede estar algo sobrestimado"
        )

    # AFFO con capex real cuando es aislable
    capex = _latest(_find_row(cf, "capital+expenditure", "purchase+of+ppe"))
    if capex is not None and out["ffo"]:
        maintenance = abs(capex) * fx_rate
        # Sólo se acepta el capex directo si no devora el FFO por completo: en un
        # REIT en expansión la mayor parte del capex es crecimiento, no mantenimiento.
        if 0 < maintenance < out["ffo"] * 0.6:
            out["affo"] = out["ffo"] - maintenance
            out["source"].append("AFFO = FFO − capex declarado")

    return out
