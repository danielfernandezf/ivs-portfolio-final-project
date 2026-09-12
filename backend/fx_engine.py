"""
FX Engine — Normalización de divisas para estados financieros
=============================================================
Resuelve el fallo más grave del motor de valoración: los ADR extranjeros
reportan sus estados financieros en la moneda local (`financialCurrency`)
mientras que el precio, el market cap y las acciones cotizan en otra
(`currency`, típicamente USD).

Ejemplo real detectado en la caché del screener:

    AVAL (Grupo Aval, Colombia)
      currency          = USD   → precio 4.91 USD
      financialCurrency = COP   → FCF, deuda y caja en pesos colombianos

    El DCF descontaba FCF en COP y dividía por acciones cotizadas en USD,
    produciendo un valor intrínseco de 431.475 USD frente a un precio de
    4.91 USD — un error de ~87.000x que colocaba a estos ADR en lo más alto
    del ranking de Margin of Safety.

Este módulo convierte TODA magnitud procedente de los estados financieros
(FCF, deuda, caja, patrimonio, beneficio) a la moneda de cotización antes de
que entre en el motor. Regla de oro: el DCF debe operar en una sola moneda.

Fuente de tipos: par `XXXYYY=X` de Yahoo Finance, con caché en memoria (TTL
largo — un tipo de cambio no necesita refrescarse en mitad de un escaneo) y
un mapa de respaldo con órdenes de magnitud correctos para los casos en que
Yahoo falle, de modo que un fallo de red nunca reintroduzca el error de 87.000x.
"""

from __future__ import annotations

import logging
import threading
import time

import yfinance as yf

logger = logging.getLogger("fx-engine")

# Un tipo de cambio no se mueve lo suficiente en una sesión de escaneo como
# para justificar refrescarlo: 6 h mantiene el escaneo consistente y barato.
_FX_TTL = 6 * 3600

_fx_cache: dict[str, tuple[float, float]] = {}
_lock = threading.Lock()

# Respaldo de emergencia: unidades de moneda local por 1 USD.
# NO pretende ser preciso — su único trabajo es preservar el ORDEN DE MAGNITUD
# cuando Yahoo no responde, evitando que una divisa de 4 cifras (COP, KRW, CLP)
# se trate como paridad 1:1 y vuelva a envenenar el ranking.
_FALLBACK_PER_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "GBp": 79.0,       # peniques — Yahoo usa GBp para valores de Londres
    "CHF": 0.88,
    "CAD": 1.36,
    "AUD": 1.52,
    "JPY": 152.0,
    "CNY": 7.2,
    "HKD": 7.8,
    "TWD": 32.0,
    "KRW": 1350.0,
    "INR": 84.0,
    "SGD": 1.34,
    "BRL": 5.4,
    "MXN": 18.0,
    "ARS": 1000.0,
    "CLP": 950.0,
    "COP": 4100.0,
    "PEN": 3.7,
    "ZAR": 18.5,
    "TRY": 34.0,
    "SEK": 10.5,
    "NOK": 10.8,
    "DKK": 6.9,
    "PLN": 4.0,
    "ILS": 3.7,
    "THB": 35.0,
    "IDR": 15800.0,
    "PHP": 58.0,
    "MYR": 4.5,
    "VND": 25000.0,
    "AED": 3.67,
    "SAR": 3.75,
    "NGN": 1600.0,
    "EGP": 48.0,
}

# Divisas cotizadas en subunidades: Yahoo devuelve precios en peniques/centavos
# pero los estados financieros en la unidad mayor. Factor = subunidades por unidad.
_MINOR_UNIT = {"GBp": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def _normalise_code(code: str | None) -> str:
    """Limpia el código de divisa preservando la distinción GBP / GBp."""
    if not code:
        return ""
    c = str(code).strip()
    if c in _MINOR_UNIT:
        return c
    return c.upper()


def _fetch_pair(base: str, quote: str) -> float | None:
    """Tipo `base→quote` desde Yahoo (`BASEQUOTE=X`). None si no disponible."""
    symbol = f"{base}{quote}=X"
    try:
        tk = yf.Ticker(symbol)
        # fast_info es mucho más ligero que .info y suficiente para un spot
        try:
            fi = tk.fast_info
            price = fi.get("lastPrice") if hasattr(fi, "get") else fi["lastPrice"]
            if price and float(price) > 0:
                return float(price)
        except Exception:
            pass
        hist = tk.history(period="5d")
        if not hist.empty:
            last = float(hist["Close"].iloc[-1])
            if last > 0:
                return last
    except Exception as exc:
        logger.debug(f"FX {symbol} no disponible: {exc}")
    return None


def _fallback_rate(base: str, quote: str) -> float | None:
    """Tipo aproximado vía USD usando el mapa de respaldo."""
    b = _FALLBACK_PER_USD.get(base)
    q = _FALLBACK_PER_USD.get(quote)
    if b and q and b > 0:
        # base→USD = 1/b ; USD→quote = q
        return q / b
    return None


def get_rate(base: str | None, quote: str | None) -> float:
    """
    Devuelve el factor multiplicativo para convertir un importe de `base` a `quote`.

    `importe_en_quote = importe_en_base * get_rate(base, quote)`

    Devuelve 1.0 cuando ambas monedas coinciden o cuando no hay información
    suficiente (en cuyo caso el llamador debe marcar el dato como no fiable).
    """
    b = _normalise_code(base)
    q = _normalise_code(quote)

    if not b or not q:
        return 1.0

    # Subunidades: convierte a la unidad mayor y sigue desde ahí.
    factor = 1.0
    if b in _MINOR_UNIT:
        major, div = _MINOR_UNIT[b]
        factor /= div
        b = major
    if q in _MINOR_UNIT:
        major, mul = _MINOR_UNIT[q]
        factor *= mul
        q = major

    if b == q:
        return factor

    key = f"{b}->{q}"
    now = time.time()
    with _lock:
        hit = _fx_cache.get(key)
        if hit and now - hit[0] < _FX_TTL:
            return factor * hit[1]

    rate = _fetch_pair(b, q)
    if rate is None:
        # Segundo intento: par inverso (Yahoo cubre mejor unos pares que otros)
        inv = _fetch_pair(q, b)
        if inv and inv > 0:
            rate = 1.0 / inv
    if rate is None:
        rate = _fallback_rate(b, q)
        if rate is not None:
            logger.warning(f"FX {key}: usando tipo de respaldo aproximado {rate:.6g}")

    if rate is None or rate <= 0:
        logger.error(f"FX {key}: sin tipo de cambio — se asume 1.0 (dato NO fiable)")
        return factor

    with _lock:
        _fx_cache[key] = (now, rate)
    return factor * rate


def is_supported(code: str | None) -> bool:
    """True si conocemos un respaldo para la divisa (permite avisar al usuario)."""
    return _normalise_code(code) in _FALLBACK_PER_USD or _normalise_code(code) in _MINOR_UNIT


def convert(amount: float, base: str | None, quote: str | None) -> float:
    """Convierte un importe de `base` a `quote`."""
    if amount is None:
        return 0.0
    return float(amount) * get_rate(base, quote)
