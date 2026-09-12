"""
Movers Engine — Top performers del universo rastreado
======================================================
Calcula el rendimiento reciente (semana / día / mes) de las ~2300 empresas del
universo del screener y publica el ranking de mejores y peores.

Por qué un job en background y no un cálculo al vuelo:
  - Son ~2300 tickers. Aun descargando por tandas de 150 (una petición HTTP por
    tanda en vez de una por ticker), la pasada completa tarda minutos. Bloquear
    una petición HTTP tanto tiempo no es viable, así que se replica el patrón del
    screener: se dispara un hilo, se persiste el resultado y la UI lee la caché.
  - El resultado se guarda en `movers_cache.json`, de modo que al abrir la
    pestaña el ranking aparece al instante aunque el backend se haya reiniciado.

Rendimiento semanal = variación del cierre ajustado entre la última sesión
disponible y la de 5 sesiones antes (una semana de bolsa), NO 7 días naturales:
así un festivo no falsea la ventana.

Los metadatos (nombre, sector, MoS, veredicto) se cruzan con `screener_cache.json`
cuando existen, para que el ranking no sea una lista de tickers desnudos y se
pueda ver si un valor que se ha disparado seguía barato en la última valoración.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import screener_engine
from price_cache import get_history_chunked

logger = logging.getLogger("movers-engine")

_BASE_DIR = Path(__file__).resolve().parent
_CACHE_FILE = _BASE_DIR / "movers_cache.json"

_CACHE_VERSION = 1

# Sesiones de bolsa que definen cada ventana.
_WINDOWS = {"day": 1, "week": 5, "month": 21}

# Cuántos días naturales de histórico pedir. 60 cubre con holgura las 21 sesiones
# de la ventana mensual incluso con puentes y festivos.
_LOOKBACK_DAYS = 60

# Cuántos nombres se guardan en cada extremo del ranking.
_TOP_N = 50


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def _read_cache() -> dict:
    empty = {
        "version": _CACHE_VERSION,
        "gainers": [], "losers": [],
        "last_run": None, "n_tickers": 0, "as_of": None, "window_dates": {},
    }
    try:
        if _CACHE_FILE.exists():
            with _CACHE_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("version") == _CACHE_VERSION:
                return data
    except Exception as exc:
        logger.warning(f"No se pudo leer movers_cache.json: {exc}")
    return empty


def _write_cache(payload: dict) -> None:
    try:
        with _CACHE_FILE.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except Exception as exc:
        logger.warning(f"No se pudo escribir movers_cache.json: {exc}")


# ---------------------------------------------------------------------------
# Metadatos del screener
# ---------------------------------------------------------------------------

def _screener_meta() -> dict[str, dict]:
    """{ticker: {company_name, sector, mos_pct, verdict}} de la última valoración.

    Se lee la caché del screener directamente en vez de llamar a get_status(),
    que además arrastra los 1400 resultados completos y el estado del escaneo.
    """
    meta: dict[str, dict] = {}
    try:
        cache = screener_engine._load_cache()
    except Exception as exc:
        logger.warning(f"No se pudo leer la caché del screener: {exc}")
        return meta

    for row in cache.get("results", []):
        tk = row.get("ticker")
        if not tk:
            continue
        meta[tk] = {
            "company_name": row.get("company_name") or tk,
            "sector": row.get("sector") or "N/A",
            "mos_pct": row.get("mos_pct"),
            "verdict": row.get("verdict"),
        }
    return meta


# ---------------------------------------------------------------------------
# Estado del job
# ---------------------------------------------------------------------------

class _RunState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.done = 0
        self.total = 0
        self.started_at: Optional[str] = None
        self.error: Optional[str] = None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "done": self.done,
                "total": self.total,
                "started_at": self.started_at,
                "error": self.error,
                "progress_pct": round(self.done / self.total * 100, 1) if self.total else 0.0,
            }


_state = _RunState()


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------

def _pct_change(closes: list[float], sessions: int) -> Optional[float]:
    """Variación % entre el último cierre y el de `sessions` sesiones antes.

    None si no hay histórico suficiente: es importante distinguir "no hay datos"
    de "no se movió", porque un 0.0 inventado contaminaría el ranking de perdedores.
    """
    if len(closes) < sessions + 1:
        return None
    prev = closes[-(sessions + 1)]
    last = closes[-1]
    if prev <= 0:
        return None
    return round((last / prev - 1) * 100, 2)


def _build_rows(history: dict[str, dict[str, float]], meta: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for ticker, series in history.items():
        if not series:
            continue
        dates = sorted(series.keys())
        closes = [series[d] for d in dates]

        week = _pct_change(closes, _WINDOWS["week"])
        if week is None:
            continue  # sin una semana de histórico no entra en el ranking semanal

        info = meta.get(ticker, {})
        rows.append({
            "ticker": ticker,
            "company_name": info.get("company_name") or ticker,
            "sector": info.get("sector") or "N/A",
            "mos_pct": info.get("mos_pct"),
            "verdict": info.get("verdict"),
            "last_close": round(closes[-1], 2),
            "last_date": dates[-1],
            "day_pct": _pct_change(closes, _WINDOWS["day"]),
            "week_pct": week,
            "month_pct": _pct_change(closes, _WINDOWS["month"]),
        })
    return rows


def _run(tickers: list[str]) -> None:
    start = (datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    def _progress(done: int, total: int) -> None:
        with _state.lock:
            _state.done = done
            _state.total = total

    try:
        history = get_history_chunked(tickers, start, progress=_progress)
        rows = _build_rows(history, _screener_meta())

        ranked = sorted(rows, key=lambda r: r["week_pct"], reverse=True)
        gainers = ranked[:_TOP_N]
        losers = list(reversed(ranked[-_TOP_N:])) if len(ranked) > _TOP_N else list(reversed(ranked))

        as_of = max((r["last_date"] for r in rows), default=None)
        _write_cache({
            "version": _CACHE_VERSION,
            "gainers": gainers,
            "losers": losers,
            "n_tickers": len(rows),
            "n_universe": len(tickers),
            "as_of": as_of,
            "last_run": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Movers: {len(rows)} tickers con datos de {len(tickers)} del universo")
        with _state.lock:
            _state.error = None
    except Exception as exc:
        logger.exception("El cálculo de movers falló")
        with _state.lock:
            _state.error = str(exc)[:300]
    finally:
        with _state.lock:
            _state.running = False


def start_refresh(tickers: Optional[list[str]] = None) -> dict:
    """Lanza el recálculo en background. No-op si ya hay uno en marcha."""
    with _state.lock:
        if _state.running:
            return {"started": False, "reason": "already_running", **_state.snapshot()}
        universe = tickers if tickers is not None else screener_engine.load_universe()
        _state.running = True
        _state.done = 0
        _state.total = len(universe)
        _state.error = None
        _state.started_at = datetime.now(timezone.utc).isoformat()

    threading.Thread(target=_run, args=(universe,), daemon=True, name="movers-refresh").start()
    return {"started": True, **_state.snapshot()}


def get_movers(limit: int = 20) -> dict[str, Any]:
    """Ranking cacheado de mejores y peores de la semana, más el estado del job."""
    cache = _read_cache()
    return {
        "gainers": cache.get("gainers", [])[:limit],
        "losers": cache.get("losers", [])[:limit],
        "n_tickers": cache.get("n_tickers", 0),
        "n_universe": cache.get("n_universe", 0),
        "as_of": cache.get("as_of"),
        "last_run": cache.get("last_run"),
        "status": _state.snapshot(),
    }
