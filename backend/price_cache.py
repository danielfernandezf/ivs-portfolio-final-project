"""
Price Cache & Batch Fetcher
===========================
Capa compartida de acceso a yfinance para acelerar drásticamente la descarga
de datos. Sustituye el patrón lento de "un `yf.Ticker(t)` por ticker en bucle"
(cada `.info` tarda 1-3s y dispara rate-limits 429) por:

  1. Descarga histórica EN LOTE — un único `yf.download([...])` para todos los
     tickers a la vez (1 petición HTTP en vez de N).
  2. Precios live vía `fast_info` (ligero) en paralelo, no `.info` (pesado).
  3. Caché en memoria con TTL corto para no repetir descargas dentro de la
     misma carga de pestaña (la reconstrucción del historial se pedía 3 veces).

Usado por performance_engine.py y main.py.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import yfinance as yf

logger = logging.getLogger("price-cache")

# TTLs (segundos)
_HIST_TTL = 300   # cierres históricos: cambian 1x/día, cache 5 min
_LIVE_TTL = 60    # precios live: cache 1 min para no saturar Yahoo

# La caché histórica va indexada por (ticker, start), NO por el conjunto de
# tickers pedido. Con la clave por conjunto, una tanda que Yahoo devolvía
# incompleta (pasa cuando la sesión del proceso lleva mucho tráfico: se perdían
# 6 de las 11 posiciones) quedaba fijada 5 minutos como si estuviera completa, y
# la matriz de correlación se dibujaba con los tickers que hubieran sobrevivido.
# Por ticker, lo que falta simplemente se vuelve a pedir en la llamada siguiente.
_hist_cache: dict[tuple[str, str], tuple[float, dict[str, float]]] = {}
_live_cache: dict[str, tuple[float, float]] = {}
_lock = threading.Lock()

# Espera antes de reintentar los tickers que una tanda no devolvió.
_RETRY_PAUSE = 1.5
# A partir de este tamaño se barren las entradas caducadas de la caché histórica
# (el universo del screener son ~2300 tickers y cada uno guarda ~500 cierres).
_HIST_CACHE_MAX = 6000


# ---------------------------------------------------------------------------
# Histórico en lote
# ---------------------------------------------------------------------------

def _download_history(tickers: list[str], start: str) -> dict[str, dict[str, float]]:
    """Descarga los cierres diarios de todos los tickers en UNA sola petición.

    Devuelve {ticker: {"YYYY-MM-DD": close}}. auto_adjust=True para replicar el
    comportamiento de yf.Ticker().history() del que depende el motor (cierres
    ajustados por splits/dividendos).
    """
    tickers = list(dict.fromkeys(t for t in tickers if t))  # dedupe, conserva orden
    result: dict[str, dict[str, float]] = {}
    if not tickers:
        return result

    try:
        df = yf.download(
            tickers, start=start, progress=False,
            group_by="ticker", threads=True, auto_adjust=True,
        )
    except Exception as e:
        logger.warning(f"batch download falló: {e}")
        return result

    if df is None or df.empty:
        return result

    import pandas as pd
    multi = isinstance(df.columns, pd.MultiIndex)

    for t in tickers:
        try:
            if multi:
                # group_by='ticker' => columnas ('TICKER', 'Close') incluso con 1 ticker
                closes = df[t]["Close"].dropna()
            else:
                # columnas planas (algunas versiones con un solo ticker)
                closes = df["Close"].dropna()
        except Exception:
            continue
        if len(closes):
            result[t] = {idx.strftime("%Y-%m-%d"): float(c) for idx, c in closes.items()}

    logger.info(f"batch history: {len(result)}/{len(tickers)} tickers desde {start}")
    return result


def get_history_batch(tickers: list[str], start: str) -> dict[str, dict[str, float]]:
    """Cierres históricos en lote, con caché por ticker de {_HIST_TTL}s.

    Solo se descarga lo que no esté cacheado. Si la tanda vuelve incompleta
    —Yahoo deja de servir parte de los tickers cuando la sesión acumula
    tráfico— se reintenta UNA vez lo que falte tras una pausa breve; lo que
    siga faltando no se cachea, así que la llamada siguiente lo vuelve a pedir
    en vez de heredar el hueco durante todo el TTL.
    """
    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return {}

    now = time.time()
    out: dict[str, dict[str, float]] = {}
    missing: list[str] = []

    with _lock:
        for t in tickers:
            hit = _hist_cache.get((t, start))
            if hit and now - hit[0] < _HIST_TTL:
                out[t] = hit[1]
            else:
                missing.append(t)

    if missing:
        fresh = _download_history(missing, start)

        absent = [t for t in missing if t not in fresh]
        if absent:
            # Un único reintento en lote: 1 petición HTTP más, no N.
            logger.info(f"reintentando {len(absent)} tickers que la tanda no devolvió")
            time.sleep(_RETRY_PAUSE)
            fresh.update(_download_history(absent, start))
            absent = [t for t in missing if t not in fresh]
        if absent:
            logger.warning(f"sin histórico tras reintento: {', '.join(absent)}")

        stamp = time.time()
        with _lock:
            for t, series in fresh.items():
                if series:
                    _hist_cache[(t, start)] = (stamp, series)
            if len(_hist_cache) > _HIST_CACHE_MAX:
                for k in [k for k, v in _hist_cache.items() if stamp - v[0] >= _HIST_TTL]:
                    del _hist_cache[k]
        out.update(fresh)

    # Se devuelve en el orden pedido (el llamador lo usa para etiquetar filas).
    return {t: out[t] for t in tickers if t in out}


# Un único yf.download con miles de tickers falla (URL enorme + timeout), así que
# el universo completo del screener se descarga por tandas.
_CHUNK_SIZE = 150


def get_history_chunked(
    tickers: list[str],
    start: str,
    chunk_size: int = _CHUNK_SIZE,
    progress: "Callable[[int, int], None] | None" = None,
    pause: float = 0.8,
) -> dict[str, dict[str, float]]:
    """Cierres históricos de un universo grande, descargando en tandas.

    Pensado para los ~2300 tickers del screener, donde `get_history_batch` en una
    sola llamada se queda colgado o lo tumba el rate-limit de Yahoo. Cada tanda sí
    pasa por la caché normal, así que repetir la operación dentro del TTL es
    gratis. `progress(hechos, total)` se llama tras cada tanda.

    Los fallos de una tanda no abortan el resto: se registran y se sigue, porque
    perder 150 de 2300 tickers es mucho mejor que perderlos todos.
    """
    tickers = list(dict.fromkeys(t for t in tickers if t))
    out: dict[str, dict[str, float]] = {}
    total = len(tickers)
    if not total:
        return out

    for i in range(0, total, chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            out.update(get_history_batch(chunk, start))
        except Exception as exc:
            logger.warning(f"tanda {i // chunk_size + 1} falló: {exc}")
        if progress:
            progress(min(i + chunk_size, total), total)
        # Respiro entre tandas para no disparar el rate-limit de Yahoo.
        if pause > 0 and i + chunk_size < total:
            time.sleep(pause)

    logger.info(f"histórico troceado: {len(out)}/{total} tickers desde {start}")
    return out


# ---------------------------------------------------------------------------
# Precios live
# ---------------------------------------------------------------------------

def _fetch_one_live(ticker: str) -> float:
    """Precio live de un ticker vía fast_info (ligero). 0.0 si no disponible."""
    try:
        fi = yf.Ticker(ticker).fast_info
        for key in ("lastPrice", "last_price"):
            try:
                price = fi[key] if not hasattr(fi, "get") else fi.get(key)
            except Exception:
                price = None
            if price and float(price) > 0:
                return float(price)
        # Último recurso: último cierre reciente
        hist = yf.Ticker(ticker).history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def get_live_prices(tickers: list[str]) -> dict[str, float]:
    """Precios live de varios tickers en paralelo, con caché de {_LIVE_TTL}s.

    Devuelve {ticker: price}; los que fallan se omiten (el llamador aplica su
    propio fallback, p.ej. purchase_price).
    """
    tickers = list(dict.fromkeys(t for t in tickers if t))
    now = time.time()
    out: dict[str, float] = {}
    missing: list[str] = []

    with _lock:
        for t in tickers:
            hit = _live_cache.get(t)
            if hit and now - hit[0] < _LIVE_TTL:
                out[t] = hit[1]
            else:
                missing.append(t)

    if missing:
        with ThreadPoolExecutor(max_workers=min(8, len(missing))) as ex:
            fetched = dict(zip(missing, ex.map(_fetch_one_live, missing)))
        stamp = time.time()
        with _lock:
            for t, price in fetched.items():
                if price > 0:
                    _live_cache[t] = (stamp, price)
                    out[t] = price

    return out


def get_live_price(ticker: str) -> float:
    """Precio live de un único ticker (con caché). 0.0 si no disponible."""
    return get_live_prices([ticker]).get(ticker, 0.0)
