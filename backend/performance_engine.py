"""
Performance & Benchmarking Engine
==================================
Calcula el rendimiento real de la cartera y lo compara con el S&P 500 (SPY).

Enfoque correcto:
  - Reconstruye el valor diario de la cartera desde la primera compra usando
    precios históricos reales de yfinance (NO snapshots manuales).
  - Para cada día de trading:
      cash(t)  = capital_inicial - sum(cost_basis de posiciones compradas en t o antes)
      valor(t) = cash(t) + sum(shares_i × precio_i(t))
  - Compara contra SPY normalizado a 100 desde la misma fecha de inicio.
  - TWR correcto: descuenta aportaciones de capital de la rentabilidad.

Storage: portfolio_history solo se usa para aportaciones de capital.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf

from price_cache import get_history_batch, get_live_prices, get_live_price

DB_PATH = Path(__file__).parent.parent / "portfolio.db"
logger = logging.getLogger("performance-engine")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

@contextmanager
def _conn():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def bootstrap_history():
    """Crea la tabla portfolio_history si no existe (para aportaciones de capital)."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS portfolio_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                date            TEXT    NOT NULL,
                total_value     REAL    NOT NULL,
                cash_balance    REAL    NOT NULL,
                invested_value  REAL    NOT NULL,
                contribution    REAL    NOT NULL DEFAULT 0,
                event           TEXT    NOT NULL DEFAULT 'snapshot'
            );
            CREATE INDEX IF NOT EXISTS idx_history_date ON portfolio_history (date);
        """)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PerformanceData:
    history: list[dict]           # [{date, total_value, cash, invested}]
    twr_pct: float                # time-weighted return %
    total_contributions: float
    initial_capital: float


def _live_price(ticker: str) -> float:
    """Live yfinance price (cacheado, vía fast_info); mirrors main._fetch_live_price
    so chart endpoints match the top-bar live return."""
    return get_live_price(ticker)


def _append_live_snapshot(history: list[dict], positions) -> None:
    """Mutate `history` in place: append (or replace last) with a 'live' point
    that uses the DB's real cash balance and ALL current positions at live
    prices, so chart endpoints match /api/portfolio/live (top bar).

    Necesario porque positions compradas después del último cierre histórico
    (e.g. fines de semana) no aparecen en `_reconstruct_daily`, y los precios
    live divergen de los cierres auto-ajustados de yfinance.history()."""
    from portfolio_db import portfolio_db

    if not positions:
        return

    # Precios live de TODAS las posiciones en una sola tanda (paralelo + caché)
    live_prices = get_live_prices([p.ticker for p in positions])
    live_market_value = 0.0
    for p in positions:
        lp = live_prices.get(p.ticker) or 0.0
        if lp <= 0:
            lp = p.purchase_price
        live_market_value += p.shares * lp

    cash = portfolio_db.get_cash()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    live_point = {
        "date": today,
        "total_value": round(cash + live_market_value, 2),
        "cash": round(cash, 2),
        "invested": round(live_market_value, 2),
        "contribution": 0.0,
        "event": "live",
    }

    # Si el último punto ya es de hoy (rara vez), reemplázalo; si no, añade.
    if history and history[-1]["date"] >= today:
        history[-1] = live_point
    else:
        history.append(live_point)


@dataclass
class BenchmarkData:
    dates: list[str]
    portfolio_indexed: list[float]   # base 100
    spy_indexed: list[float]         # base 100
    portfolio_return_pct: float
    spy_return_pct: float
    alpha_pct: float


# ---------------------------------------------------------------------------
# Aportaciones de capital
# ---------------------------------------------------------------------------

def record_snapshot(
    total_value: float,
    cash_balance: float,
    invested_value: float,
    contribution: float = 0.0,
    event: str = "snapshot",
    date_override: Optional[str] = None,
):
    bootstrap_history()
    now = date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as con:
        con.execute(
            "INSERT INTO portfolio_history (date,total_value,cash_balance,invested_value,contribution,event) VALUES (?,?,?,?,?,?)",
            (now, total_value, cash_balance, invested_value, contribution, event),
        )
    logger.info(f"Snapshot: {event} | value={total_value:.2f} | contrib={contribution:.2f}")


def record_capital_injection(amount: float, new_cash_balance: float, new_total_value: float):
    record_snapshot(
        total_value=new_total_value,
        cash_balance=new_cash_balance,
        invested_value=new_total_value - new_cash_balance,
        contribution=amount,
        event="capital_injection",
    )


def _get_contributions() -> list[dict]:
    """Devuelve todas las aportaciones de capital registradas."""
    bootstrap_history()
    with _conn() as con:
        rows = con.execute(
            "SELECT date, contribution FROM portfolio_history WHERE contribution > 0 ORDER BY date ASC"
        ).fetchall()
    return [{"date": r["date"][:10], "amount": r["contribution"]} for r in rows]


def _contributions_by_date() -> dict[str, float]:
    """Aportaciones agregadas por fecha (YYYY-MM-DD)."""
    by_date: dict[str, float] = {}
    for c in _get_contributions():
        by_date[c["date"]] = by_date.get(c["date"], 0.0) + c["amount"]
    return by_date


def _compute_twr_series(
    history: list[dict],
    contribs_by_date: dict[str, float],
    initial_capital: float,
) -> tuple[float, list[float]]:
    """
    Time-Weighted Return correcto, eliminando el efecto de las aportaciones.

    Para cada sub-período (cierre t-1 → cierre t):
        r_t = (V_t - C_t) / V_(t-1)        # V_t SIN la aportación de hoy

    Donde:
        V_t = total_value al cierre del día t (incluye la aportación de t)
        C_t = aportación recibida el día t (0 si no hay)
        V_(t-1) = total_value al cierre del día anterior (ya con su propia aportación)

    El primer sub-período va de initial_capital al primer cierre.

    Devuelve:
        - factor TWR final (1.05 == +5%)
        - serie indexada a initial_capital, alineada con `history`,
          para gráficos sin saltos por cash flows.
    """
    if not history or initial_capital <= 0:
        return 1.0, []

    twr_factor = 1.0
    indexed: list[float] = []
    prev_value = initial_capital

    for point in history:
        day = point["date"]
        v_today_raw = point["total_value"]
        contrib_today = contribs_by_date.get(day, 0.0)
        v_today_pre = v_today_raw - contrib_today

        if prev_value > 0:
            twr_factor *= v_today_pre / prev_value

        indexed.append(round(twr_factor * initial_capital, 2))
        # Para el siguiente sub-período, el "cierre anterior" sí incluye la aportación de hoy
        prev_value = v_today_raw

    return twr_factor, indexed


# ---------------------------------------------------------------------------
# Reconstrucción del historial diario
# ---------------------------------------------------------------------------

def _reconstruct_daily(period: str = "all") -> list[dict]:
    """
    Reconstruye el valor diario de la cartera desde la primera compra.

    Para cada día de trading desde la primera purchase_date:
      cash(t)   = initial_capital - sum(cost_basis de posiciones compradas en t o antes)
      value(t)  = cash(t) + sum(shares_i × close_i(t) para posiciones activas en t)

    Las aportaciones mensuales se suman al capital_inicial acumulado desde su fecha.
    """
    from portfolio_db import portfolio_db

    positions = portfolio_db.get_positions()
    if not positions:
        return []

    initial_capital = portfolio_db.get_initial_capital()

    # Fecha de inicio = compra más antigua
    start_date = min(p.purchase_date[:10] for p in positions)

    # Filtro de período
    period_cutoff: Optional[str] = None
    if period == "week":
        period_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    elif period == "month":
        period_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    elif period == "year":
        period_cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

    # La reconstrucción siempre empieza desde el inicio para calcular correctamente;
    # el filtro de período se aplica al output final
    tickers = [p.ticker for p in positions]

    # Descarga histórica de TODAS las posiciones en UNA sola petición (batch + caché)
    price_data = get_history_batch(tickers, start_date)

    if not price_data:
        return []

    # Conjunto de todos los días de trading disponibles
    all_trading_days = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))

    # Aportaciones de capital acumuladas (ajustan el capital inicial desde su fecha)
    contributions = _get_contributions()
    cash_now = portfolio_db.get_cash()

    result = []
    for day in all_trading_days:
        # Posiciones activas en este día (compradas en ese día o antes)
        active = [p for p in positions if p.purchase_date[:10] <= day]
        if not active:
            continue

        # Efectivo del día: parte del saldo real de hoy y devuelve el coste de lo
        # aún no comprado en esa fecha. Ver _cash_on: derivarlo de
        # `capital_inicial − coste` daba negativo con plusvalías realizadas y el
        # clamp a 0 hacía que el gráfico no cuadrase con /api/portfolio/live.
        cash = _cash_on(positions, day, cash_now)

        # Valor de mercado de las posiciones activas en este día
        market_value = 0.0
        for p in active:
            ticker = p.ticker
            if ticker in price_data:
                prices = price_data[ticker]
                if day in prices:
                    market_value += p.shares * prices[day]
                else:
                    # forward-fill: último precio disponible antes de este día
                    prev = [d for d in prices if d <= day]
                    if prev:
                        market_value += p.shares * prices[max(prev)]
                    else:
                        market_value += p.cost_basis_total

        total = round(cash + market_value, 2)

        result.append({
            "date": day,
            "total_value": total,
            "cash": round(cash, 2),
            "invested": round(market_value, 2),
            "contribution": 0.0,
            "event": "reconstructed",
        })

    # Aplicar filtro de período al output
    if period_cutoff:
        result = [r for r in result if r["date"] >= period_cutoff]

    return result


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def get_performance(period: str = "all") -> PerformanceData:
    """
    Devuelve el historial diario reconstruido y el retorno total de la cartera.

    El retorno se calcula desde el capital inicial real (100k) hasta el valor
    actual, sin importar cuántos días de cierre tenga el historial.

    Se añade un punto inicial artificial en capital_inicial para que el gráfico
    arranque siempre desde el dinero invertido y no desde el primer cierre.
    """
    from portfolio_db import portfolio_db

    initial_capital = portfolio_db.get_initial_capital()
    total_contributions = sum(c["amount"] for c in _get_contributions())
    history = _reconstruct_daily(period)

    if not history:
        return PerformanceData(
            history=[], twr_pct=0.0,
            total_contributions=total_contributions,
            initial_capital=initial_capital,
        )

    # Sobrescribe el último cierre con precios LIVE para que el gráfico
    # coincida con /api/portfolio/live (top bar).
    positions = portfolio_db.get_positions()
    _append_live_snapshot(history, positions)

    # Añadir punto de inicio en capital_inicial para que el gráfico arranque en 100k
    first_date = history[0]["date"]
    start_point = {
        "date": first_date,          # misma fecha, pero al inicio del día
        "total_value": round(initial_capital, 2),
        "cash": round(initial_capital, 2),
        "invested": 0.0,
        "contribution": 0.0,
        "event": "start",
    }
    # Solo añadir si el primer punto ya tiene valor distinto de initial_capital
    if history[0]["total_value"] != initial_capital:
        history = [start_point] + history

    # TWR correcto: encadena returns sub-período DESCONTANDO las aportaciones
    # de cada día (si no, las cash injections se contabilizan como rentabilidad).
    full_history = _reconstruct_daily("all")
    if full_history:
        _append_live_snapshot(full_history, positions)
        contribs_by_date = _contributions_by_date()
        twr_factor, _ = _compute_twr_series(full_history, contribs_by_date, initial_capital)
        twr_pct = round((twr_factor - 1) * 100, 2)
    else:
        twr_pct = 0.0

    return PerformanceData(
        history=history,
        twr_pct=twr_pct,
        total_contributions=round(total_contributions, 2),
        initial_capital=round(initial_capital, 2),
    )


# ---------------------------------------------------------------------------
# Time machine — la cartera tal y como estaba en una fecha concreta
# ---------------------------------------------------------------------------

def _cash_on(positions, day: str, cash_now: float) -> float:
    """Efectivo disponible al cierre de `day`.

    Se parte del efectivo REAL de hoy y se devuelve al bote el coste de las
    posiciones que en esa fecha aún no se habían comprado. Así, en t = hoy el
    resultado es exactamente el saldo del que informa /api/portfolio/live.

    El cálculo anterior (`capital_inicial − coste de las posiciones activas`)
    daba negativo en cuanto había plusvalías realizadas: al vender con ganancia,
    el efectivo recibido supera el coste original, se reinvierte, y la suma de
    cost_basis acaba por encima del capital inicial (aquí: 127.696 € de coste
    frente a 100.000 € de capital). El clamp a 0 escondía el descuadre.
    """
    return cash_now + sum(
        p.cost_basis_total for p in positions if p.purchase_date[:10] > day
    )


def _price_on(series: dict[str, float], day: str) -> Optional[float]:
    """Cierre de `day`, o el último anterior (forward-fill) si no cotizó ese día.

    Devuelve None si no hay ningún cierre en o antes de `day`, que es lo que pasa
    al pedir una fecha previa a la salida a bolsa o al inicio del histórico.
    """
    exact = series.get(day)
    if exact is not None:
        return exact
    earlier = [d for d in series if d <= day]
    return series[max(earlier)] if earlier else None


def get_portfolio_as_of(target_date: str, compare_sessions: int = 5) -> dict:
    """Reconstruye la cartera completa a cierre de `target_date` (YYYY-MM-DD).

    Devuelve el detalle por posición (precio, valor, retorno desde compra) más los
    totales, y la variación respecto a `compare_sessions` sesiones antes — 5 por
    defecto, es decir una semana de bolsa.

    LIMITACIÓN IMPORTANTE: la tabla `positions` solo guarda lo que se tiene ahora
    (una venta borra la fila), así que la reconstrucción refleja las posiciones
    ACTUALES aplicadas hacia atrás. Si se vendió algo, ese valor no aparece en el
    pasado. Es la misma limitación que ya tenía `_reconstruct_daily`; corregirla
    exigiría un libro de transacciones.
    """
    from portfolio_db import portfolio_db

    positions = portfolio_db.get_positions()
    if not positions:
        return {
            "date": target_date, "requested_date": target_date,
            "positions": [], "cash": 0.0, "invested": 0.0, "total_value": 0.0,
            "return_pct": 0.0, "capital_at_date": 0.0,
            "available_from": None, "available_to": None,
            "message": "No hay posiciones en la cartera.",
        }

    first_purchase = min(p.purchase_date[:10] for p in positions)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Acotamos la fecha pedida al rango con datos, en vez de devolver un error:
    # el slider de la UI puede pedir un extremo y es más útil enseñar el borde.
    day = max(first_purchase, min(target_date, today))

    tickers = [p.ticker for p in positions]
    price_data = get_history_batch(tickers, first_purchase)
    if not price_data:
        return {
            "date": day, "requested_date": target_date,
            "positions": [], "cash": 0.0, "invested": 0.0, "total_value": 0.0,
            "return_pct": 0.0, "capital_at_date": 0.0,
            "available_from": first_purchase, "available_to": today,
            "message": "No se pudieron descargar precios históricos.",
        }

    # Días de bolsa reales, para resolver la sesión efectiva y la de comparación.
    trading_days = sorted(set().union(*[set(s.keys()) for s in price_data.values()]))
    prior = [d for d in trading_days if d <= day]
    effective = prior[-1] if prior else day
    is_trading_day = day in trading_days

    idx = len(prior) - 1
    cmp_idx = idx - compare_sessions
    comparison_date = prior[cmp_idx] if cmp_idx >= 0 else None

    initial_capital = portfolio_db.get_initial_capital()
    capital_at_date = initial_capital + sum(
        c["amount"] for c in _get_contributions() if c["date"] <= effective
    )

    active = [p for p in positions if p.purchase_date[:10] <= effective]
    cash = _cash_on(positions, effective, portfolio_db.get_cash())

    rows: list[dict] = []
    invested = 0.0
    for p in active:
        series = price_data.get(p.ticker, {})
        price = _price_on(series, effective)
        # Sin cotización usable, el coste es el fallback honesto (mismo criterio
        # que _reconstruct_daily), y se marca para que la UI lo pueda avisar.
        stale = price is None or price <= 0
        if stale:
            price = p.purchase_price
        value = p.shares * price
        invested += value

        cmp_price = _price_on(series, comparison_date) if comparison_date else None
        rows.append({
            "ticker": p.ticker,
            "company_name": p.company_name,
            "sector": p.sector,
            "shares": p.shares,
            "purchase_price": round(p.purchase_price, 4),
            "purchase_date": p.purchase_date[:10],
            "price_at_date": round(price, 4),
            "market_value": round(value, 2),
            "cost_basis": round(p.cost_basis_total, 2),
            "return_pct": round((price / p.purchase_price - 1) * 100, 2) if p.purchase_price > 0 else 0.0,
            "period_pct": (
                round((price / cmp_price - 1) * 100, 2)
                if cmp_price and cmp_price > 0 else None
            ),
            "stale_price": stale,
        })

    total = cash + invested
    for r in rows:
        r["weight_pct"] = round(r["market_value"] / total * 100, 2) if total > 0 else 0.0
    rows.sort(key=lambda r: r["market_value"], reverse=True)

    # Valor total en la fecha de comparación, para la variación del período.
    period_change_pct = None
    if comparison_date:
        cmp_active = [p for p in positions if p.purchase_date[:10] <= comparison_date]
        if cmp_active:
            cmp_cash = _cash_on(positions, comparison_date, portfolio_db.get_cash())
            cmp_invested = 0.0
            for p in cmp_active:
                cp = _price_on(price_data.get(p.ticker, {}), comparison_date) or p.purchase_price
                cmp_invested += p.shares * cp
            cmp_total = cmp_cash + cmp_invested
            if cmp_total > 0:
                period_change_pct = round((total / cmp_total - 1) * 100, 2)

    return {
        "date": effective,
        "requested_date": target_date,
        "is_trading_day": is_trading_day,
        "positions": rows,
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "total_value": round(total, 2),
        "capital_at_date": round(capital_at_date, 2),
        "return_pct": round((total / capital_at_date - 1) * 100, 2) if capital_at_date > 0 else 0.0,
        "period_change_pct": period_change_pct,
        "comparison_date": comparison_date,
        "compare_sessions": compare_sessions,
        "n_positions": len(rows),
        "available_from": first_purchase,
        "available_to": trading_days[-1] if trading_days else today,
        "trading_days": trading_days,
    }


# ---------------------------------------------------------------------------
# Rendimientos diarios por posición (para el heatmap)
# ---------------------------------------------------------------------------

def get_daily_returns(days: int = 30) -> dict:
    """Matriz de rendimientos diarios % por posición para los últimos `days` naturales.

    Devuelve {tickers, dates, returns: {ticker: {date: pct}}, stats}. Alimenta el
    heatmap que acompaña a la matriz de correlación: la correlación dice si dos
    valores se mueven juntos, esto enseña qué hizo cada uno cada día.
    """
    from portfolio_db import portfolio_db

    positions = portfolio_db.get_positions()
    if not positions:
        return {"tickers": [], "dates": [], "returns": {}, "stats": {}, "n_days": 0}

    # Se descarga un margen extra: para el primer día del rango hace falta el
    # cierre anterior, y hay que absorber fines de semana y festivos.
    start = (datetime.now(timezone.utc) - timedelta(days=days + 15)).strftime("%Y-%m-%d")
    tickers = [p.ticker for p in positions]
    price_data = get_history_batch(tickers, start)
    if not price_data:
        return {"tickers": [], "dates": [], "returns": {}, "stats": {}, "n_days": 0}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    returns: dict[str, dict[str, float]] = {}
    stats: dict[str, dict] = {}
    for ticker in tickers:
        series = price_data.get(ticker)
        if not series:
            continue
        dates = sorted(series.keys())
        daily: dict[str, float] = {}
        for i in range(1, len(dates)):
            d = dates[i]
            if d < cutoff:
                continue
            prev_close = series[dates[i - 1]]
            if prev_close > 0:
                daily[d] = round((series[d] / prev_close - 1) * 100, 2)
        if not daily:
            continue
        returns[ticker] = daily

        vals = list(daily.values())
        wins = sum(1 for v in vals if v > 0)
        stats[ticker] = {
            "mean": round(sum(vals) / len(vals), 2),
            "best": max(vals),
            "worst": min(vals),
            "win_rate": round(wins / len(vals) * 100, 1),
            "cumulative": round(
                (_compound(vals) - 1) * 100, 2
            ),
        }

    all_dates = sorted({d for series in returns.values() for d in series})
    return {
        "tickers": [t for t in tickers if t in returns],
        "dates": all_dates,
        "returns": returns,
        "stats": stats,
        "n_days": len(all_dates),
        "period_days": days,
    }


def _compound(pcts: list[float]) -> float:
    """Producto de (1 + r) de una lista de rendimientos en %."""
    factor = 1.0
    for p in pcts:
        factor *= (1 + p / 100)
    return factor


def get_benchmark() -> BenchmarkData:
    """
    Compara la cartera contra el S&P 500 (SPY), ambos normalizados a 100.

    Usa el historial reconstruido de la cartera (precios reales), no snapshots.
    El punto de inicio es la fecha de la primera compra.
    """
    from portfolio_db import portfolio_db

    positions = portfolio_db.get_positions()
    if not positions:
        return BenchmarkData(
            dates=[], portfolio_indexed=[], spy_indexed=[],
            portfolio_return_pct=0.0, spy_return_pct=0.0, alpha_pct=0.0,
        )

    start_date = min(p.purchase_date[:10] for p in positions)

    # Historial completo de la cartera
    portfolio_history = _reconstruct_daily("all")
    if not portfolio_history:
        return BenchmarkData(
            dates=[], portfolio_indexed=[], spy_indexed=[],
            portfolio_return_pct=0.0, spy_return_pct=0.0, alpha_pct=0.0,
        )

    # Cartera indexada por TWR (sin saltos por aportaciones)
    from portfolio_db import portfolio_db as _pdb
    base_port = _pdb.get_initial_capital()
    contribs_by_date = _contributions_by_date()

    # Sobrescribe el último cierre con precios LIVE para que el gráfico y el
    # `portfolio_return_pct` coincidan con /api/portfolio/live (top bar).
    # yfinance.history() devuelve precios auto-ajustados (split/dividendo), que
    # divergen de los precios raw que usa el cálculo live.
    _append_live_snapshot(portfolio_history, positions)

    _, port_twr_indexed = _compute_twr_series(portfolio_history, contribs_by_date, base_port)
    port_indexed_dict = {p["date"]: v for p, v in zip(portfolio_history, port_twr_indexed)}

    # Descarga SPY desde la misma fecha de inicio (batch + caché)
    spy_dict = get_history_batch(["SPY"], start_date).get("SPY", {})
    if not spy_dict:
        logger.warning("No se pudo descargar SPY")
        return BenchmarkData(
            dates=[], portfolio_indexed=[], spy_indexed=[],
            portfolio_return_pct=0.0, spy_return_pct=0.0, alpha_pct=0.0,
        )
    logger.info(f"SPY descargado: {len(spy_dict)} días desde {start_date}")

    # Asegura que SPY tenga un punto para "hoy" (la fecha del live snapshot de
    # la cartera): usa el precio live, o si no, forward-fill desde el último
    # cierre disponible. Sin esto, common_dates excluiría el live snapshot.
    today = portfolio_history[-1]["date"]
    spy_live = _live_price("SPY")
    if spy_live > 0:
        spy_dict[today] = spy_live
    elif today not in spy_dict and spy_dict:
        spy_dict[today] = spy_dict[max(spy_dict.keys())]

    # Fechas comunes (días de trading donde ambos tienen datos)
    common_dates = sorted(set(port_indexed_dict.keys()) & set(spy_dict.keys()))
    if not common_dates:
        return BenchmarkData(
            dates=[], portfolio_indexed=[], spy_indexed=[],
            portfolio_return_pct=0.0, spy_return_pct=0.0, alpha_pct=0.0,
        )

    # SPY normalizado al mismo base (capital inicial) desde su precio en el primer día común
    base_spy = spy_dict[common_dates[0]]
    portfolio_indexed = [port_indexed_dict[d] for d in common_dates]
    spy_indexed       = [round(spy_dict[d] / base_spy * base_port, 2) for d in common_dates]

    port_ret = round((portfolio_indexed[-1] / base_port - 1) * 100, 2)
    spy_ret  = round((spy_indexed[-1]      / base_port - 1) * 100, 2)

    return BenchmarkData(
        dates=common_dates,
        portfolio_indexed=portfolio_indexed,
        spy_indexed=spy_indexed,
        portfolio_return_pct=port_ret,
        spy_return_pct=spy_ret,
        alpha_pct=round(port_ret - spy_ret, 2),
    )
