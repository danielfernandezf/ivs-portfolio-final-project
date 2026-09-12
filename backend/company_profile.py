"""
Company Profile — Clasificación de instrumento y enrutado de modelo
====================================================================
Un DCF sobre Free Cash Flow NO es válido para todos los tipos de empresa.
Aplicarlo indiscriminadamente es la segunda causa de mala valoración del
sistema (después del descuadre de divisas):

  · Bancos y aseguradoras — la "deuda" es materia prima del negocio (depósitos,
    reservas técnicas), no financiación. Restar Net Debt del Enterprise Value
    carece de sentido económico y el FCF contable no mide capacidad distribuible.
    → Modelo de Exceso de Retorno sobre fondos propios (Damodaran).

  · REITs — el capex inmobiliario deprime el FCF de forma estructural, así que
    el DCF los infravalora sistemáticamente. La métrica sectorial es el AFFO.
    → DCF sobre AFFO descontado al coste de los fondos propios.

  · Preferentes, warrants, units y fondos cerrados — no son acciones ordinarias.
    Un DCF de equity sobre ellos es directamente una categoría errónea
    (detectados 54 en la caché: VNO-PL, KIM-PM, AMH-PG…).
    → Excluidos del universo.

  · Biotecnología pre-ingresos / empresas sin flujo de caja normalizable —
    no hay serie de FCF que proyectar; cualquier número es ruido.
    → Excluidas, con motivo explícito.

Este módulo NO calcula valor: sólo decide qué modelo corresponde y por qué,
de modo que la decisión sea auditable desde la interfaz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class InstrumentType(str, Enum):
    COMMON = "COMMON"          # acción ordinaria — valorable
    PREFERRED = "PREFERRED"    # preferente — renta fija disfrazada
    WARRANT = "WARRANT"
    UNIT = "UNIT"              # unit de SPAC
    FUND = "FUND"              # ETF, fondo cerrado, fideicomiso
    OTHER = "OTHER"


class ValuationModel(str, Enum):
    DCF = "DCF"                        # FCF a la firma, descontado a WACC
    EXCESS_RETURN = "EXCESS_RETURN"    # bancos / aseguradoras
    REIT_AFFO = "REIT_AFFO"            # inmobiliario cotizado
    EXCLUDED = "EXCLUDED"              # no valorable de forma fiable


@dataclass
class CompanyProfile:
    ticker: str
    instrument: InstrumentType
    model: ValuationModel
    sector: str
    industry: str
    is_financial: bool
    is_reit: bool
    excluded_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def valuable(self) -> bool:
        return self.model is not ValuationModel.EXCLUDED


# ---------------------------------------------------------------------------
# Detección de instrumento por símbolo
# ---------------------------------------------------------------------------
# Convenciones de Yahoo Finance para el mercado estadounidense:
#   BRK-B    → clase de acción ordinaria (VÁLIDA, no confundir)
#   VNO-PL   → preferente serie L        (excluir)
#   ABC-WT   → warrant                   (excluir)
#   XYZ-UN   → unit de SPAC              (excluir)
#   ABC.PR.A → preferente (formato alternativo)
#
# El patrón de preferente es `-P` seguido de la letra de serie. Se distingue de
# una clase ordinaria (`-A`, `-B`) porque estas nunca empiezan por P... salvo
# excepciones reales, de ahí que se confirme con el nombre largo cuando existe.
_RE_PREFERRED = re.compile(r"(-P[A-Z]?$)|(\.PR[\.\-]?[A-Z]?$)|(-P$)", re.I)
_RE_WARRANT = re.compile(r"(-WT?$)|(\.WS$)|(-RT$)", re.I)
_RE_UNIT = re.compile(r"(-UN?$)|(\.U$)", re.I)

_PREFERRED_NAME_HINTS = (
    "preferred", "pfd", "depositary share", "depositary shares",
    "cumulative", "perpetual pref",
)
_FUND_NAME_HINTS = (
    "etf", "index fund", "closed-end", "closed end", "trust series",
    "unit trust", " spdr", "ishares", "vanguard ", "proshares", "invesco q",
)


def _detect_instrument(ticker: str, info: dict) -> tuple[InstrumentType, str]:
    """Devuelve (tipo, motivo)."""
    t = (ticker or "").upper()
    name = str(info.get("longName") or info.get("shortName") or "").lower()
    quote_type = str(info.get("quoteType") or "").upper()

    if quote_type in {"ETF", "MUTUALFUND", "INDEX", "CURRENCY", "CRYPTOCURRENCY", "FUTURE"}:
        return InstrumentType.FUND, f"quoteType={quote_type} — no es una acción ordinaria"

    if any(h in name for h in _PREFERRED_NAME_HINTS):
        return InstrumentType.PREFERRED, "el nombre identifica una acción preferente"
    if _RE_PREFERRED.search(t):
        return InstrumentType.PREFERRED, f"el símbolo '{t}' sigue el patrón de preferente"
    if _RE_WARRANT.search(t):
        return InstrumentType.WARRANT, f"el símbolo '{t}' sigue el patrón de warrant"
    if _RE_UNIT.search(t):
        return InstrumentType.UNIT, f"el símbolo '{t}' sigue el patrón de unit de SPAC"
    if any(h in name for h in _FUND_NAME_HINTS):
        return InstrumentType.FUND, "el nombre identifica un fondo o vehículo indexado"

    return InstrumentType.COMMON, ""


# ---------------------------------------------------------------------------
# Detección sectorial
# ---------------------------------------------------------------------------
# Financieras con FCF económicamente interpretable: gestoras de activos, bolsas,
# asesoras, procesadoras de pagos y bróker. Su balance NO es su materia prima,
# así que el DCF clásico sigue siendo el modelo correcto para ellas.
_FINANCIAL_DCF_OK = (
    "asset management", "capital markets", "financial data", "financial exchanges",
    "shell companies", "financial conglomerates",
)
# Financieras donde el DCF es inválido: el pasivo ES el negocio.
_BANKING_INDUSTRIES = (
    "bank", "banks", "credit services", "insurance", "mortgage",
    "savings", "thrift", "reinsurance", "financial credit",
)
_REIT_HINTS = ("reit", "real estate investment trust")

# Umbral deuda/capitalización por encima del cual una financiera "de comisiones"
# se comporta en realidad como un banco. Calibrado sobre datos reales: asesoras
# puras ≤ 0,26x (EVR 0,09 · PJT 0,06 · HLI 0,05 · BX 0,10 · STEP 0,26) frente a
# bróker-dealers ≥ 0,70x (VIRT 0,70 · MS 1,71 · GS 2,50).
_BALANCE_SHEET_LEVERAGE = 0.5

# Nombres cuyo negocio incluye una licencia bancaria aunque Yahoo los clasifique
# como "Capital Markets". Sus depósitos no aparecen en `totalDebt`, así que la
# regla de apalancamiento no los detecta.
_BANK_LICENSE_HINTS = ("schwab", "raymond james", "stifel", "lpl financial", "ameriprise bank")


def _leverage_ratio(info: dict) -> float | None:
    """Deuda financiera sobre capitalización. None si falta algún dato."""
    try:
        mc = float(info.get("marketCap") or 0)
        td = float(info.get("totalDebt") or 0)
    except (TypeError, ValueError):
        return None
    if mc <= 0:
        return None
    return td / mc


def _detect_model(
    instrument: InstrumentType,
    sector: str,
    industry: str,
    info: dict,
) -> tuple[ValuationModel, str | None, list[str]]:
    notes: list[str] = []

    if instrument is not InstrumentType.COMMON:
        return ValuationModel.EXCLUDED, None, notes  # el motivo lo pone el llamador

    sec = (sector or "").lower()
    ind = (industry or "").lower()
    name = str(info.get("longName") or info.get("shortName") or "").lower()

    if sec == "financial services" and any(h in name for h in _BANK_LICENSE_HINTS):
        notes.append(
            "Entidad con licencia bancaria: los depósitos no figuran en la deuda "
            "financiera — se aplica Exceso de Retorno"
        )
        return ValuationModel.EXCESS_RETURN, None, notes

    is_reit = "reit" in ind or any(h in ind for h in _REIT_HINTS) or (
        sec == "real estate" and "reit" in str(info.get("longBusinessSummary", "")).lower()[:400]
    )
    if is_reit:
        notes.append("REIT: el capex inmobiliario invalida el FCF — se valora sobre AFFO")
        return ValuationModel.REIT_AFFO, None, notes

    if sec == "financial services":
        if any(k in ind for k in _FINANCIAL_DCF_OK):
            # Dentro de "Capital Markets" conviven dos negocios muy distintos:
            # asesoras puras (EVR, PJT, HLI, MC — deuda/capitalización < 0,10x) y
            # bróker-dealers que operan con balance propio (MS 1,71x, GS 2,50x).
            # Sólo las primeras admiten DCF; las segundas se financian con el
            # balance igual que un banco.
            lev = _leverage_ratio(info)
            if lev is not None and lev > _BALANCE_SHEET_LEVERAGE:
                notes.append(
                    f"Intermediario con balance propio (deuda/capitalización = {lev:.1f}x): "
                    "se financia como un banco — se aplica Exceso de Retorno"
                )
                return ValuationModel.EXCESS_RETURN, None, notes
            notes.append(
                "Financiera de comisiones (no toma balance): el FCF es interpretable, se mantiene DCF"
            )
            return ValuationModel.DCF, None, notes
        if any(k in ind for k in _BANKING_INDUSTRIES):
            notes.append(
                "Banco/aseguradora: los depósitos y reservas no son deuda financiera — "
                "se valora por Exceso de Retorno sobre fondos propios"
            )
            return ValuationModel.EXCESS_RETURN, None, notes
        # Financiera sin industria reconocida: el modelo de exceso de retorno es
        # el supuesto conservador, ya que el riesgo de tratar depósitos como
        # deuda es mucho mayor que el de aplicar un modelo de equity.
        notes.append(
            f"Financiera de industria no reconocida ('{industry}') — "
            "se aplica Exceso de Retorno por prudencia"
        )
        return ValuationModel.EXCESS_RETURN, None, notes

    return ValuationModel.DCF, None, notes


def classify(ticker: str, info: dict) -> CompanyProfile:
    """
    Determina instrumento y modelo de valoración a partir del `info` de yfinance.
    No realiza llamadas de red: opera sobre el diccionario ya descargado.
    """
    sector = str(info.get("sector") or "N/A")
    industry = str(info.get("industry") or "N/A")

    instrument, reason = _detect_instrument(ticker, info)
    model, _, notes = _detect_model(instrument, sector, industry, info)

    excluded_reason = None
    if instrument is not InstrumentType.COMMON:
        label = {
            InstrumentType.PREFERRED: "Acción preferente",
            InstrumentType.WARRANT: "Warrant",
            InstrumentType.UNIT: "Unit de SPAC",
            InstrumentType.FUND: "Fondo / vehículo cotizado",
            InstrumentType.OTHER: "Instrumento no ordinario",
        }[instrument]
        excluded_reason = (
            f"{label}: no es capital ordinario, un DCF de equity no le aplica"
            f"{' — ' + reason if reason else ''}"
        )
        model = ValuationModel.EXCLUDED

    ind_l = industry.lower()
    return CompanyProfile(
        ticker=ticker.upper(),
        instrument=instrument,
        model=model,
        sector=sector,
        industry=industry,
        is_financial=(sector or "").lower() == "financial services",
        is_reit="reit" in ind_l or any(h in ind_l for h in _REIT_HINTS),
        excluded_reason=excluded_reason,
        notes=notes,
    )
