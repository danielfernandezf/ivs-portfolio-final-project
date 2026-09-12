"""
Portfolio Database — SQLite-backed position ledger
====================================================
Persists to portfolio.db one level above the backend package (valuation-system/).

Schema:
  positions — one row per ticker (averaged if added in multiple tranches)
  portfolio_meta — key/value store for cash_balance, initial_capital

Capital: starts at €100,000 virtual.  All monetary values in the portfolio
currency (mix is allowed; position values shown in native currency, but
portfolio math uses market_value at purchase in EUR equivalents).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "portfolio.db"
INITIAL_CAPITAL: float = 100_000.0   # €


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PortfolioPosition:
    id: int
    ticker: str
    company_name: str
    shares: float
    purchase_price: float            # weighted-average cost basis per share
    purchase_date: str               # ISO 8601
    sector: str
    currency: str
    intrinsic_price_at_purchase: float
    mos_at_purchase: float           # margin of safety % at time of entry
    allocated_weight_pct: float      # % of total portfolio at time of purchase
    cost_basis_total: float          # shares × purchase_price
    is_manual_override: bool = False # True if user changed the system recommendation


@dataclass
class PortfolioSummary:
    positions: list[PortfolioPosition]
    cash_balance: float
    initial_capital: float
    invested_capital: float          # sum of cost_basis_total across positions
    total_portfolio_value: float     # invested + cash (at cost — updated live via /live)


# ---------------------------------------------------------------------------
# DB connection helper
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


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def _bootstrap():
    """Create tables and seed initial cash if DB is new."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker                      TEXT    NOT NULL UNIQUE,
                company_name                TEXT    NOT NULL DEFAULT '',
                shares                      REAL    NOT NULL DEFAULT 0,
                purchase_price              REAL    NOT NULL DEFAULT 0,
                purchase_date               TEXT    NOT NULL,
                sector                      TEXT    NOT NULL DEFAULT 'N/A',
                currency                    TEXT    NOT NULL DEFAULT 'USD',
                intrinsic_price_at_purchase REAL    NOT NULL DEFAULT 0,
                mos_at_purchase             REAL    NOT NULL DEFAULT 0,
                allocated_weight_pct        REAL    NOT NULL DEFAULT 0,
                cost_basis_total            REAL    NOT NULL DEFAULT 0,
                is_manual_override          INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS portfolio_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # Migrate existing DB: add is_manual_override if missing
        try:
            con.execute("ALTER TABLE positions ADD COLUMN is_manual_override INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # column already exists

        # Seed only if fresh
        con.execute(
            "INSERT OR IGNORE INTO portfolio_meta (key, value) VALUES (?, ?)",
            ("initial_capital", str(INITIAL_CAPITAL)),
        )
        con.execute(
            "INSERT OR IGNORE INTO portfolio_meta (key, value) VALUES (?, ?)",
            ("cash_balance", str(INITIAL_CAPITAL)),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PortfolioDatabase:

    def __init__(self):
        _bootstrap()

    # ------------------------------------------------------------------
    # Meta / cash
    # ------------------------------------------------------------------

    def get_cash(self) -> float:
        with _conn() as con:
            row = con.execute(
                "SELECT value FROM portfolio_meta WHERE key='cash_balance'"
            ).fetchone()
        return float(row["value"]) if row else INITIAL_CAPITAL

    def get_initial_capital(self) -> float:
        with _conn() as con:
            row = con.execute(
                "SELECT value FROM portfolio_meta WHERE key='initial_capital'"
            ).fetchone()
        return float(row["value"]) if row else INITIAL_CAPITAL

    def _set_cash(self, amount: float, con: sqlite3.Connection):
        con.execute(
            "INSERT OR REPLACE INTO portfolio_meta (key, value) VALUES ('cash_balance', ?)",
            (str(round(amount, 4)),),
        )

    # ------------------------------------------------------------------
    # Read positions
    # ------------------------------------------------------------------

    def get_positions(self) -> list[PortfolioPosition]:
        with _conn() as con:
            rows = con.execute(
                "SELECT * FROM positions ORDER BY cost_basis_total DESC"
            ).fetchall()
        return [self._row_to_position(r) for r in rows]

    def get_position(self, ticker: str) -> Optional[PortfolioPosition]:
        with _conn() as con:
            row = con.execute(
                "SELECT * FROM positions WHERE ticker=?", (ticker.upper(),)
            ).fetchone()
        return self._row_to_position(row) if row else None

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> PortfolioPosition:
        return PortfolioPosition(
            id=row["id"],
            ticker=row["ticker"],
            company_name=row["company_name"],
            shares=row["shares"],
            purchase_price=row["purchase_price"],
            purchase_date=row["purchase_date"],
            sector=row["sector"],
            currency=row["currency"],
            intrinsic_price_at_purchase=row["intrinsic_price_at_purchase"],
            mos_at_purchase=row["mos_at_purchase"],
            allocated_weight_pct=row["allocated_weight_pct"],
            cost_basis_total=row["cost_basis_total"],
            is_manual_override=bool(row["is_manual_override"]),
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> PortfolioSummary:
        positions = self.get_positions()
        cash = self.get_cash()
        invested = sum(p.cost_basis_total for p in positions)
        return PortfolioSummary(
            positions=positions,
            cash_balance=cash,
            initial_capital=self.get_initial_capital(),
            invested_capital=invested,
            total_portfolio_value=invested + cash,
        )

    # ------------------------------------------------------------------
    # Buy / add position
    # ------------------------------------------------------------------

    def buy(
        self,
        ticker: str,
        company_name: str,
        shares: float,
        price_per_share: float,
        sector: str,
        currency: str,
        intrinsic_price: float,
        mos_pct: float,
        allocated_weight_pct: float,
        is_manual_override: bool = False,
    ) -> PortfolioPosition:
        """
        Add or average-up a position.
        Deducts total_cost from cash_balance.
        Raises ValueError if insufficient cash.
        """
        ticker = ticker.upper()
        total_cost = shares * price_per_share
        cash = self.get_cash()

        if total_cost > cash + 0.01:   # 1-cent tolerance
            raise ValueError(
                f"Insufficient cash. Need {total_cost:.2f}, available {cash:.2f}."
            )

        with _conn() as con:
            existing = con.execute(
                "SELECT * FROM positions WHERE ticker=?", (ticker,)
            ).fetchone()

            now = datetime.now(timezone.utc).isoformat()

            if existing:
                # Weighted-average cost basis
                old_shares = existing["shares"]
                old_price = existing["purchase_price"]
                new_total_shares = old_shares + shares
                new_avg_price = (
                    (old_shares * old_price + shares * price_per_share) / new_total_shares
                )
                new_cost_total = new_total_shares * new_avg_price

                con.execute(
                    """UPDATE positions SET
                        shares=?, purchase_price=?, cost_basis_total=?,
                        intrinsic_price_at_purchase=?, mos_at_purchase=?,
                        allocated_weight_pct=?
                    WHERE ticker=?""",
                    (
                        new_total_shares, new_avg_price, new_cost_total,
                        intrinsic_price, mos_pct, allocated_weight_pct,
                        ticker,
                    ),
                )
            else:
                con.execute(
                    """INSERT INTO positions
                        (ticker, company_name, shares, purchase_price, purchase_date,
                         sector, currency, intrinsic_price_at_purchase, mos_at_purchase,
                         allocated_weight_pct, cost_basis_total, is_manual_override)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ticker, company_name, shares, price_per_share, now,
                        sector, currency, intrinsic_price, mos_pct,
                        allocated_weight_pct, total_cost,
                        int(is_manual_override),
                    ),
                )

            self._set_cash(cash - total_cost, con)

        return self.get_position(ticker)

    # ------------------------------------------------------------------
    # Sell position
    # ------------------------------------------------------------------

    def sell(self, ticker: str) -> float:
        """
        Fully liquidate a position at cost basis (for virtual portfolio).
        In a live system, yfinance live price would be used instead.
        Returns the proceeds credited back to cash.
        """
        ticker = ticker.upper()
        pos = self.get_position(ticker)
        if not pos:
            raise ValueError(f"No position found for {ticker}.")

        proceeds = pos.cost_basis_total
        with _conn() as con:
            con.execute("DELETE FROM positions WHERE ticker=?", (ticker,))
            self._set_cash(self.get_cash() + proceeds, con)

        return proceeds

    def sell_at_price(self, ticker: str, current_price: float) -> float:
        """
        Liquidate a position at a given market price.
        Returns proceeds = shares × current_price.
        """
        ticker = ticker.upper()
        pos = self.get_position(ticker)
        if not pos:
            raise ValueError(f"No position found for {ticker}.")

        proceeds = pos.shares * current_price
        with _conn() as con:
            con.execute("DELETE FROM positions WHERE ticker=?", (ticker,))
            self._set_cash(self.get_cash() + proceeds, con)

        return proceeds

    # ------------------------------------------------------------------
    # Reset (for testing)
    # ------------------------------------------------------------------

    def inject_capital(self, amount: float):
        """
        Add a capital injection (e.g. monthly contribution).
        Increases both cash_balance and initial_capital.
        """
        with _conn() as con:
            cash = self.get_cash()
            self._set_cash(cash + amount, con)
            initial = self.get_initial_capital()
            con.execute(
                "INSERT OR REPLACE INTO portfolio_meta (key, value) VALUES ('initial_capital', ?)",
                (str(round(initial + amount, 4)),),
            )

    def reset(self):
        with _conn() as con:
            con.execute("DELETE FROM positions")
            self._set_cash(INITIAL_CAPITAL, con)


# Singleton
portfolio_db = PortfolioDatabase()
