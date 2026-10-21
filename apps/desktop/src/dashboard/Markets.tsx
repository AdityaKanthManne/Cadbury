import { useEffect, useState } from "react";
import { api, type MarketRow, type Markets as MarketsData } from "../api";
import { clock } from "./format";

export function fmtLast(r: MarketRow): string {
  if (r.kind === "rate") return `${r.last.toFixed(2)}%`;
  if (r.kind === "vol") return r.last.toFixed(2);
  const digits = r.last >= 1000 ? 0 : 2;
  return r.last.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtChange(r: MarketRow): string {
  if (r.kind === "rate" && r.change_bp != null) return `${r.change_bp > 0 ? "+" : ""}${r.change_bp.toFixed(0)} bp`;
  return `${r.change_pct > 0 ? "+" : ""}${r.change_pct.toFixed(2)}%`;
}

/** One line for the masthead: "S&P 500 −2.06%, VIX 18.20, 10-year Treasury yield 4.18%". */
export function marketLine(rows: MarketRow[]): string {
  const pick = ["^GSPC", "^IXIC", "^VIX", "^TNX"];
  return rows
    .filter((r) => pick.includes(r.ticker))
    .map((r) => (r.kind === "vol" || r.kind === "rate" ? `${r.name} ${fmtLast(r)}` : `${r.name} ${fmtChange(r).replace("-", "−")}`))
    .join(", ");
}

export function Markets({ refreshKey }: { refreshKey?: unknown }) {
  const [data, setData] = useState<MarketsData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.markets().then(setData).catch(() => setFailed(true));
  }, [refreshKey]);

  if (failed) return <p className="loading">Couldn't load market data from the backend.</p>;
  if (!data) return <p className="loading">Loading…</p>;

  const rows = data.markets?.rows ?? [];
  const macro = data.macro;
  return (
    <div className="markets">
      <div className="toolbar"><h2>Market</h2><p className="toolbar-blurb">Prices at the last briefing, and macro data.</p></div>

      {data.unavailable ? (
        <div className="empty"><p>No market data here.</p><p className="empty-sub">{data.unavailable}</p></div>
      ) : rows.length === 0 ? (
        <div className="empty">
          <p>No prices yet.</p>
          <p className="empty-sub">They arrive with the next briefing, or fetch now from the top of this window.</p>
        </div>
      ) : (
        <>
          <div className="table-wrap">
            <table className="mkt">
              <thead>
                <tr><th>Instrument</th><th className="num">Last</th><th className="num">Day</th><th>As of</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.ticker}>
                    <td><span className="mkt-name">{r.name}</span> <span className="mkt-ticker">{r.ticker}</span></td>
                    <td className="num">{fmtLast(r)}</td>
                    <td className={`num ${r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : ""}`}>{fmtChange(r)}</td>
                    <td>{r.as_of}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="list-foot">
            Yahoo Finance prices via yfinance, delayed, captured {clock(data.markets?.taken_at)}. For a personal dashboard, not for trading.
          </p>
        </>
      )}

      <div className="toolbar"><h2>Macro</h2></div>
      {!data.fred_enabled ? (
        <p className="empty-sub">FRED is turned off in <code>configs/user_profile.yaml</code>.</p>
      ) : !macro || macro.needs_key ? (
        <div className="empty">
          <p>Add a free FRED key to see CPI, unemployment and rates.</p>
          <p className="empty-sub">
            Create a free account at fred.stlouisfed.org and request an API key, then run{" "}
            <code>bash scripts/setup_mac.sh</code> again and paste it when asked. Or add{" "}
            <code>FRED_API_KEY=your-key</code> to <code>.env</code> in the butler's data folder and restart the app.
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="mkt">
            <thead>
              <tr><th>Series</th><th className="num">Latest</th><th className="num">Previous</th><th>Date</th></tr>
            </thead>
            <tbody>
              {macro.rows.map((r) => (
                <tr key={r.id}>
                  <td><span className="mkt-name">{r.name}</span> <span className="mkt-ticker">{r.id}</span></td>
                  <td className="num">
                    {r.latest.toLocaleString()}{r.units === "%" ? "%" : ""}
                    {r.yoy_pct != null && <span className="mkt-ticker"> ({r.yoy_pct > 0 ? "+" : ""}{r.yoy_pct}% y/y)</span>}
                  </td>
                  <td className="num">{r.previous != null ? `${r.previous.toLocaleString()}${r.units === "%" ? "%" : ""}` : "–"}</td>
                  <td>{r.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
