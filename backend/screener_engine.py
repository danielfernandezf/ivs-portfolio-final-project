"""
Screener Engine — Live Margin-of-Safety discovery
===================================================
Scans a curated universe of US small/mid-cap quality names, computes each
ticker's DCF-based Margin of Safety (MoS) via the same valuation engine used by
the Analyzer, caches the ranked result to disk, and exposes progress so the UI
can show a live scan.

Design notes:
  - The heavy per-ticker valuation lives in main.py (needs yfinance + engine).
    This module is engine-agnostic: `start_scan(valuator)` receives a callable
    `valuator(ticker) -> dict | None` and orchestrates threading, progress,
    caching and ranking around it.
  - Universe is persisted to `screener_universe.json` so the user can edit it
    (add / remove tickers) and the change survives restarts.
  - Results are persisted to `screener_cache.json` so the ranked list is
    available instantly on load, without re-scanning.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import universe_fetcher

logger = logging.getLogger("screener-engine")

_BASE_DIR = Path(__file__).resolve().parent
_UNIVERSE_FILE = _BASE_DIR / "screener_universe.json"
_CACHE_FILE = _BASE_DIR / "screener_cache.json"

# Versión del formato de resultados. Al subirla, una caché escrita por un motor
# anterior se descarta automáticamente en lugar de mezclarse con resultados
# nuevos. Imprescindible aquí: la caché v1 contenía valoraciones calculadas
# antes de corregir el descuadre de divisas (valores intrínsecos hasta 87.000x
# el precio) y `resume=True` las habría dado por buenas para siempre.
_CACHE_VERSION = 2

# Persist partial results at least this often so a multi-hour scan survives a
# crash / restart without losing progress.
_SAVE_EVERY = 20

# Errors whose text hints at Yahoo rate-limiting / transient network failure;
# these get retried with exponential backoff instead of being recorded.
_RATELIMIT_HINTS = (
    "429", "too many requests", "rate limit", "connection aborted",
    "remote end closed", "expecting value", "timed out", "read timeout",
    "max retries", "connection reset", "temporarily unavailable",
)


def _looks_rate_limited(msg: str) -> bool:
    m = (msg or "").lower()
    return any(h in m for h in _RATELIMIT_HINTS)


def _rank_key(row: dict) -> float:
    """
    Puntuación de ordenación del ranking.

    Ordenar por Margin of Safety a secas es justo lo que empujaba la basura a lo
    más alto: el descuento aparente más grande casi siempre era el error de
    datos más grande. La puntuación combina descuento y CONVICCIÓN:

      · el Margin of Safety aporta el atractivo,
      · la confianza (0-100) lo pondera, de modo que un 40 % de MoS con
        confianza alta manda sobre un 95 % con confianza baja,
      · sólo cuenta el MoS positivo: entre dos sobrevaloradas, ordenar por
        "menos mala" no aporta nada al inversor.
    """
    mos = row.get("mos_pct", 0.0) or 0.0
    conf = row.get("confidence", 50.0)
    if conf is None:
        conf = 50.0
    upside = max(mos, 0.0)
    # Un pequeño empujón a las que superan el umbral de compra fuerte.
    conviction = conf / 100.0
    bonus = 15.0 if row.get("verdict") == "STRONG BUY" else 0.0
    return upside * conviction + bonus


# ---------------------------------------------------------------------------
# Default universe — US small/mid-cap quality compounders
# (software, healthcare, industrials, financials, consumer). Mirrors the
# style of the existing portfolio. Fully editable from the UI.
# ---------------------------------------------------------------------------

DEFAULT_UNIVERSE: list[str] = [
    # Software / SaaS
    "MANH", "TYL", "MANT", "QLYS", "TENB", "RPD", "VRNS", "PCTY", "PAYC",
    "APPF", "BL", "ENV", "FROG", "AI", "BRZE", "SUMO", "DOCN", "BOX",
    "NCNO", "ALKT", "INTA", "SEMR", "GTLB", "PATH",
    # IT services / hardware
    "DLB", "FFIV", "NTCT", "SWKS", "CTSH", "EPAM", "GCT", "EXLS", "SPSC",
    "PSN", "DXC", "TDC",
    # Healthcare / med-tech / pharma
    "RMD", "VEEV", "COLL", "MEDP", "HALO", "LNTH", "PRVA", "ADUS", "AMED",
    "CORT", "SUPN", "HRMY", "ICUI", "OMCL", "TNDM",
    # Financials / fintech / capital markets
    "FDS", "AMP", "BR", "HLI", "PJT", "EVR", "MC", "STEP", "PIPR",
    "VIRT", "FLYW", "PAYO",
    # Industrials / niche manufacturing
    "TTC", "ROP", "CHD", "AAON", "SITE", "CSWI", "EXPO", "MTZ", "ATKR",
    "UFPT", "POWL", "GVA", "PRIM",
    # Consumer / other
    "CROX", "BOOT", "DECK", "FIVE", "TXRH", "WING", "CAKE", "SHAK",
]


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[Any]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:
        logger.warning(f"Could not read {path.name}: {exc}")
    return None


def _write_json(path: Path, data: Any) -> None:
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception as exc:
        logger.warning(f"Could not write {path.name}: {exc}")


def load_universe() -> list[str]:
    """Return the persisted editable universe, seeding defaults on first run."""
    data = _read_json(_UNIVERSE_FILE)
    if isinstance(data, list) and data:
        return [str(t).upper().strip() for t in data if str(t).strip()]
    _write_json(_UNIVERSE_FILE, DEFAULT_UNIVERSE)
    return list(DEFAULT_UNIVERSE)


def save_universe(tickers: list[str]) -> list[str]:
    """Persist a de-duplicated, upper-cased universe and return it."""
    seen: set[str] = set()
    clean: list[str] = []
    for t in tickers:
        u = str(t).upper().strip()
        if u and u not in seen:
            seen.add(u)
            clean.append(u)
    _write_json(_UNIVERSE_FILE, clean)
    return clean


def add_ticker(ticker: str) -> list[str]:
    universe = load_universe()
    u = ticker.upper().strip()
    if u and u not in universe:
        universe.append(u)
        save_universe(universe)
    return universe


def remove_ticker(ticker: str) -> list[str]:
    universe = load_universe()
    u = ticker.upper().strip()
    universe = [t for t in universe if t != u]
    save_universe(universe)
    return universe


# ---------------------------------------------------------------------------
# Universe refresh (pull the full US small/mid-cap universe from Yahoo)
# ---------------------------------------------------------------------------

_refresh_lock = threading.Lock()
_refresh_state: dict = {"running": False, "found": 0, "error": None, "finished_at": None}


def refresh_universe_async(min_cap: float = universe_fetcher.DEFAULT_MIN_CAP,
                           max_cap: float = universe_fetcher.DEFAULT_MAX_CAP) -> dict:
    """
    Kick off a background fetch of the full small/mid-cap universe from Yahoo and
    persist it to the editable universe file. Returns immediately.
    """
    with _refresh_lock:
        if _refresh_state["running"]:
            return dict(_refresh_state)
        _refresh_state.update(running=True, found=0, error=None, finished_at=None)

    def _worker() -> None:
        try:
            def _progress(n: int) -> None:
                with _refresh_lock:
                    _refresh_state["found"] = n
            tickers = universe_fetcher.fetch_smallmid_universe(min_cap, max_cap, _progress)
            save_universe(tickers)
            with _refresh_lock:
                _refresh_state.update(running=False, found=len(tickers),
                                      finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logger.exception("Universe refresh failed")
            with _refresh_lock:
                _refresh_state.update(running=False, error=str(exc)[:300],
                                      finished_at=datetime.now(timezone.utc).isoformat())

    threading.Thread(target=_worker, daemon=True, name="universe-refresh").start()
    with _refresh_lock:
        return dict(_refresh_state)


def refresh_status() -> dict:
    with _refresh_lock:
        return dict(_refresh_state)


def _load_cache() -> dict:
    data = _read_json(_CACHE_FILE)
    if isinstance(data, dict):
        # Descartar cachés de una versión de motor anterior (p. ej. las que
        # contenían valoraciones con el descuadre de divisas sin corregir).
        if data.get("version") != _CACHE_VERSION:
            logger.warning(
                "Caché del screener de una versión anterior: se ignora y se "
                "reconstruirá en el próximo escaneo"
            )
            return {"results": [], "last_scan": None, "errors": [], "version": _CACHE_VERSION}
        return data
    return {"results": [], "last_scan": None, "errors": [], "version": _CACHE_VERSION}


def _save_cache(results: list[dict], errors: list[dict]) -> None:
    _write_json(_CACHE_FILE, {
        "version": _CACHE_VERSION,
        "results": results,
        "errors": errors,
        "last_scan": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Scan state (thread-safe singleton)
# ---------------------------------------------------------------------------

class _ScanState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.total = 0
        self.done = 0
        self.current: Optional[str] = None
        self.started_at: Optional[str] = None
        self.rate_limited = False   # True while backing off from Yahoo throttling
        # Live-accumulating results of the *in-flight* scan
        self._live_results: list[dict] = []
        self._live_errors: list[dict] = []

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "total": self.total,
                "done": self.done,
                "current": self.current,
                "started_at": self.started_at,
                "rate_limited": self.rate_limited,
                "progress_pct": round(self.done / self.total * 100, 1) if self.total else 0.0,
            }


_state = _ScanState()


def get_status() -> dict:
    """Return live scan progress merged with the last cached ranked results."""
    cache = _load_cache()
    status = _state.snapshot()
    # While a scan is running, surface the partial live ranking so the UI fills in.
    if status["running"]:
        with _state._lock:
            live = sorted(_state._live_results, key=_rank_key, reverse=True)
        results = live if live else cache.get("results", [])
        errors = _state._live_errors
    else:
        results = cache.get("results", [])
        errors = cache.get("errors", [])
    return {
        "status": status,
        "results": results,
        "errors": errors,
        "last_scan": cache.get("last_scan"),
        "universe_size": len(load_universe()),
        "universe_refresh": refresh_status(),
    }


def _value_with_retry(valuator: Callable[[str], Optional[dict]], tk: str,
                      max_retries: int = 4) -> Optional[dict]:
    """
    Call the valuator, retrying with exponential backoff when the failure looks
    like Yahoo rate-limiting or a transient network error. Non-transient errors
    (e.g. ticker delisted / no data) raise immediately so they're recorded once.
    """
    delay = 4.0
    for attempt in range(max_retries + 1):
        try:
            row = valuator(tk)
            with _state._lock:
                _state.rate_limited = False
            return row
        except Exception as exc:
            if _looks_rate_limited(str(exc)) and attempt < max_retries:
                with _state._lock:
                    _state.rate_limited = True
                logger.warning(f"Screener: {tk} rate-limited, backing off {delay:.0f}s "
                               f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                delay = min(delay * 2, 90.0)
                continue
            raise


def _run(valuator: Callable[[str], Optional[dict]], tickers: list[str],
         throttle: float, results: list[dict], errors: list[dict]) -> None:
    since_save = 0
    for tk in tickers:
        with _state._lock:
            _state.current = tk
        try:
            row = _value_with_retry(valuator, tk)
            if row is not None:
                results.append(row)
                with _state._lock:
                    _state._live_results.append(row)
        except Exception as exc:  # never let one ticker kill the scan
            logger.warning(f"Screener: {tk} failed: {exc}")
            err = {"ticker": tk, "error": str(exc)[:200]}
            errors.append(err)
            with _state._lock:
                _state._live_errors.append(err)
        with _state._lock:
            _state.done += 1
        since_save += 1
        # Persist partial progress periodically so a crash/restart is recoverable.
        if since_save >= _SAVE_EVERY:
            ranked = sorted(results, key=_rank_key, reverse=True)
            _save_cache(ranked, errors)
            since_save = 0
        if throttle > 0:
            time.sleep(throttle)

    results.sort(key=_rank_key, reverse=True)
    _save_cache(results, errors)
    with _state._lock:
        _state.running = False
        _state.current = None
        _state.rate_limited = False
    logger.info(f"Screener scan complete: {len(results)} valued, {len(errors)} errors")


def start_scan(valuator: Callable[[str], Optional[dict]],
               universe: Optional[list[str]] = None,
               throttle: Optional[float] = None,
               resume: bool = True) -> dict:
    """
    Kick off a background scan. Returns immediately with the initial status.
    No-op (returns current status) if a scan is already running.

    resume=True continues from the last cached results, skipping tickers already
    valued (or already errored) — so an interrupted multi-hour scan can pick up
    where it left off. throttle defaults to an automatic value scaled to the
    universe size to stay under Yahoo's rate limits.
    """
    with _state._lock:
        if _state.running:
            return {"started": False, "reason": "already_running", **_state.snapshot()}

        tickers = universe if universe is not None else load_universe()

        # Auto-throttle: big universes need pacing to avoid Yahoo bans.
        if throttle is None:
            throttle = 1.2 if len(tickers) > 200 else 0.0

        # Seed from cache when resuming so we don't re-value completed tickers.
        # Successfully valued tickers and *permanent* errors (no data / delisted)
        # are considered done; transient rate-limit / network errors are NOT —
        # they get retried, so a scan run during a Yahoo throttle isn't poisoned.
        seed_results: list[dict] = []
        seed_errors: list[dict] = []
        done_set: set[str] = set()
        if resume:
            cache = _load_cache()
            seed_results = [r for r in cache.get("results", []) if r.get("ticker")]
            seed_errors = [e for e in cache.get("errors", []) if e.get("ticker")
                           and not _looks_rate_limited(e.get("error", ""))]
            done_set = {r["ticker"] for r in seed_results} | {e["ticker"] for e in seed_errors}
        pending = [t for t in tickers if t not in done_set]

        _state.running = True
        _state.total = len(tickers)
        _state.done = len(done_set)
        _state.current = None
        _state.rate_limited = False
        _state.started_at = datetime.now(timezone.utc).isoformat()
        _state._live_results = list(seed_results)
        _state._live_errors = list(seed_errors)

    thread = threading.Thread(
        target=_run, args=(valuator, pending, throttle, seed_results, seed_errors),
        daemon=True, name="screener-scan",
    )
    thread.start()
    return {"started": True, "pending": len(pending), **_state.snapshot()}
