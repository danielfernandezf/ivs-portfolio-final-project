"""
Universe Fetcher — pull the full US small/mid-cap universe from Yahoo Finance
============================================================================
Yahoo's screener endpoint returns at most ~250 rows per query and caps how far
you can page. To retrieve the *entire* small/mid-cap universe (~2000+ names) we
partition the market-cap range into sub-bands, recursively splitting any band
that still holds more than one page of results. The union of all leaf bands is
the complete universe.

Design:
  - Uses yfinance's authenticated session (cookie + crumb) so we don't have to
    re-implement Yahoo's auth handshake. yfinance itself is NOT upgraded.
  - Throttled + retried with exponential backoff on 429 / connection resets,
    because Yahoo aggressively rate-limits the screener endpoint.
  - Pure data-gathering: returns a de-duplicated, sorted list of tickers.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Callable, Optional

from yfinance.data import YfData

logger = logging.getLogger("universe-fetcher")

_UA_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "application/json",
}

_PAGE_MAX = 250          # Yahoo screener hard cap per request
_THROTTLE = 1.0          # seconds between screener requests (politeness)
_MAX_RETRIES = 5         # per-request retries on rate-limit / connection error
_MAX_DEPTH = 30          # recursion guard for band splitting

# Standard "small + mid cap" definition, in USD.
DEFAULT_MIN_CAP = 300_000_000        # $300M
DEFAULT_MAX_CAP = 10_000_000_000     # $10B


class _YahooScreener:
    """Thin authenticated client for Yahoo's screener endpoint."""

    def __init__(self) -> None:
        self._yf = YfData()
        self._crumb: Optional[str] = None
        self._session = None

    def _ensure_auth(self) -> None:
        if self._crumb and self._session is not None:
            return
        # yfinance's _get_cookie_and_crumb() returns (crumb, strategy); the
        # session itself carries the matching cookie.
        result = self._yf._get_cookie_and_crumb()
        crumb = result[0] if isinstance(result, (list, tuple)) else result
        if not crumb:
            raise RuntimeError("Could not obtain Yahoo crumb (auth failed)")
        self._crumb = crumb
        self._session = self._yf._session

    def _post(self, min_cap: float, max_cap: float, offset: int, size: int) -> dict:
        self._ensure_auth()
        body = {
            "size": size,
            "offset": offset,
            "sortField": "intradaymarketcap",
            "sortType": "asc",
            "quoteType": "EQUITY",
            "query": {"operator": "and", "operands": [
                {"operator": "eq", "operands": ["region", "us"]},
                {"operator": "btwn", "operands": ["intradaymarketcap", min_cap, max_cap]},
                # Restrict to the three real US equity exchanges (NASDAQ / NYSE /
                # NYSE American) to exclude OTC pink-sheets and foreign ADRs that
                # carry no usable financials.
                {"operator": "or", "operands": [
                    {"operator": "eq", "operands": ["exchange", "NMS"]},
                    {"operator": "eq", "operands": ["exchange", "NYQ"]},
                    {"operator": "eq", "operands": ["exchange", "ASE"]},
                ]},
            ]},
            "userId": "",
            "userIdType": "guid",
        }
        params = {
            "crumb": self._crumb,
            "lang": "en-US",
            "region": "US",
            "formatted": "false",
            "corsDomain": "finance.yahoo.com",
        }
        headers = dict(_UA_HEADERS)

        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
                    url = f"https://{host}/v1/finance/screener"
                    resp = self._session.post(
                        url, params=params, headers=headers,
                        data=json.dumps(body), timeout=30,
                    )
                    if resp.status_code == 200:
                        return resp.json().get("finance", {}).get("result", [{}])[0]
                    if resp.status_code in (401, 403):
                        # Stale crumb — force re-auth and retry.
                        self._crumb = None
                        self._ensure_auth()
                        params["crumb"] = self._crumb
                    last_exc = RuntimeError(f"HTTP {resp.status_code} from {host}")
            except Exception as exc:  # connection reset, timeout, etc.
                last_exc = exc
            backoff = _THROTTLE * (2 ** attempt)
            logger.warning(f"Screener request failed (attempt {attempt + 1}), "
                           f"backing off {backoff:.0f}s: {last_exc}")
            time.sleep(backoff)
        raise RuntimeError(f"Yahoo screener unreachable after {_MAX_RETRIES} tries: {last_exc}")

    def collect(self, min_cap: float, max_cap: float,
                out: set[str], depth: int,
                progress: Optional[Callable[[int], None]]) -> None:
        """Recursively gather every ticker in [min_cap, max_cap]."""
        result = self._post(min_cap, max_cap, offset=0, size=_PAGE_MAX)
        time.sleep(_THROTTLE)
        total = int(result.get("total") or 0)
        quotes = result.get("quotes") or []

        # Leaf band: everything fits in one page.
        if total <= _PAGE_MAX or depth >= _MAX_DEPTH or max_cap / max(min_cap, 1) < 1.01:
            for q in quotes:
                sym = q.get("symbol")
                if sym:
                    out.add(str(sym).upper().strip())
            if total > len(quotes) and depth >= _MAX_DEPTH:
                logger.warning(f"Band [{min_cap:.0f},{max_cap:.0f}] truncated: "
                               f"{total} names but recursion capped")
            if progress:
                progress(len(out))
            return

        # Split geometrically (market caps are heavily skewed toward the low end).
        mid = math.sqrt(min_cap * max_cap)
        self.collect(min_cap, mid, out, depth + 1, progress)
        self.collect(mid, max_cap, out, depth + 1, progress)


def fetch_smallmid_universe(
    min_cap: float = DEFAULT_MIN_CAP,
    max_cap: float = DEFAULT_MAX_CAP,
    progress: Optional[Callable[[int], None]] = None,
) -> list[str]:
    """
    Return the full sorted list of US equities with market cap in [min_cap, max_cap].
    `progress(count)` is called as tickers accumulate (optional).
    """
    logger.info(f"Fetching Yahoo small/mid-cap universe (${min_cap/1e6:.0f}M–${max_cap/1e9:.0f}B)…")
    screener = _YahooScreener()
    found: set[str] = set()
    screener.collect(min_cap, max_cap, found, depth=0, progress=progress)
    tickers = sorted(found)
    logger.info(f"Universe fetch complete: {len(tickers)} tickers")
    return tickers
