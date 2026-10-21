"""Market snapshot via yfinance, and macro series via fredapi (needs a free FRED key).

Prices come from Yahoo Finance through the unofficial `yfinance` library: fine for a
personal dashboard, delayed, and not for trading decisions.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import SourceResult, base_item, now_iso, short_error

log = logging.getLogger("butler.markets")


def _default_history(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker).history(period="1mo", interval="1d", auto_adjust=False)


class MarketSource:
    """instruments: [{ticker, name, kind}] where kind is index|rate|fx|commodity|crypto|vol.

    Produces a snapshot (last, change, 1-month closes per instrument) and, for big moves,
    a `market_move` item so the butler can bring it up.
    """

    def __init__(self, instruments: List[Dict], move_threshold: Dict[str, float] | None = None,
                 history: Optional[Callable] = None):
        self.instruments = instruments
        # daily % change that counts as notable, per kind
        # notable daily move per kind: % change, except rates in basis points
        self.threshold = {"index": 1.5, "fx": 1.0, "commodity": 3.0, "crypto": 5.0, "vol": 15.0, "rate": 10.0,
                          **(move_threshold or {})}
        self.history = history or _default_history

    def collect(self) -> SourceResult:
        out = SourceResult()
        rows = []
        for ins in self.instruments:
            t, name, kind = ins["ticker"], ins["name"], ins.get("kind", "index")
            try:
                df = self.history(t)
                closes = [float(x) for x in df["Close"].tolist() if x is not None and not math.isnan(float(x))]
                if len(closes) < 2:
                    raise ValueError("no prices returned (offline, or Yahoo didn't answer)")
                dates = [d.strftime("%Y-%m-%d") for d in df.index[-len(closes):]]
                last, prev = closes[-1], closes[-2]
                chg = (last / prev - 1) * 100 if prev else 0.0
                bp = (last - prev) * 100  # for yields quoted in percent
                rows.append({"ticker": t, "name": name, "kind": kind, "last": round(last, 4),
                             "prev": round(prev, 4), "change_pct": round(chg, 2),
                             "change_bp": round(bp, 1) if kind == "rate" else None, "as_of": dates[-1],
                             "closes": [round(c, 4) for c in closes[-22:]]})
                out.fetched += 1
                size = abs(bp) if kind == "rate" else abs(chg)
                if size >= self.threshold.get(kind, 2.0):
                    out.items.update(self._move_item(t, name, kind, last, prev, chg, bp, dates[-1]))
            except Exception as e:
                log.warning("Market data '%s' failed: %s", t, e)
                out.errors.append(short_error(f"Markets: {name}", e))
        out.extra["markets"] = {"taken_at": now_iso(), "rows": rows}
        return out

    @staticmethod
    def _move_item(ticker, name, kind, last, prev, chg, bp, day) -> Dict[str, Dict]:
        verb = "rose" if last > prev else "fell"
        if kind == "rate":
            title = f"{name} {verb} {abs(bp):.0f} bp to {last:.2f}% on {day}"
            body = f"{name} moved from {prev:.2f}% to {last:.2f}% ({bp:+.0f} basis points)."
        else:
            title = f"{name} {verb} {abs(chg):.1f}% on {day}"
            body = f"{name} closed at {last:,.2f}, {chg:+.2f}% from the previous close of {prev:,.2f}."
        iid = f"mkt:{ticker}:{day}"
        return {iid: base_item(
            id=iid, title=title,
            abstract=body + " Source: Yahoo Finance via yfinance (delayed data).",
            published_at=datetime.strptime(day, "%Y-%m-%d").replace(hour=21, tzinfo=timezone.utc).isoformat(timespec="seconds"),
            url=f"https://finance.yahoo.com/quote/{ticker}", source="Markets", source_type="market_move",
            content_access="computed", meta={"ticker": ticker, "change_pct": round(chg, 2), "kind": kind},
        )}


# ---- FRED -------------------------------------------------------------------------

def fred_key(data_dir: Path) -> Optional[str]:
    """FRED_API_KEY from the environment, or from <data dir>/.env (written by setup)."""
    if os.environ.get("FRED_API_KEY"):
        return os.environ["FRED_API_KEY"].strip()
    env = data_dir / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"') or None
    return None


class FredSource:
    """series: [{id, name, units}] e.g. CPIAUCSL, UNRATE, FEDFUNDS, DGS10, T10Y2Y."""

    def __init__(self, series: List[Dict], api_key: Optional[str], fetch: Optional[Callable] = None):
        self.series = series
        self.api_key = api_key
        self.fetch = fetch

    def collect(self) -> SourceResult:
        out = SourceResult()
        if not self.api_key:
            out.extra["macro"] = {"taken_at": now_iso(), "rows": [], "needs_key": True}
            return out
        fetch = self.fetch
        if fetch is None:
            from fredapi import Fred
            fred = Fred(api_key=self.api_key)
            fetch = lambda sid: fred.get_series(sid).dropna().tail(13)  # noqa: E731
        rows = []
        for s in self.series:
            try:
                ser = fetch(s["id"])
                if ser is None or len(ser) == 0:
                    raise ValueError("no observations")
                vals = [float(v) for v in ser.tolist()]
                dates = [d.strftime("%Y-%m-%d") for d in ser.index]
                row = {"id": s["id"], "name": s["name"], "units": s.get("units", ""),
                       "latest": round(vals[-1], 4), "date": dates[-1],
                       "previous": round(vals[-2], 4) if len(vals) > 1 else None,
                       "url": f"https://fred.stlouisfed.org/series/{s['id']}"}
                if s.get("yoy") and len(vals) >= 13:
                    row["yoy_pct"] = round((vals[-1] / vals[-13] - 1) * 100, 2)
                rows.append(row)
                out.fetched += 1
            except Exception as e:
                log.warning("FRED '%s' failed: %s", s["id"], e)
                out.errors.append(short_error(f"FRED: {s['name']}", e))
        out.extra["macro"] = {"taken_at": now_iso(), "rows": rows, "needs_key": False}
        return out
