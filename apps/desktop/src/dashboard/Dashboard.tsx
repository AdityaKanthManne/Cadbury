import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Briefing, type Latest, type MarketRow, type Paper, type Profile, type Status } from "../api";
import * as P from "../platform";
import { Sprite } from "../butler/Sprite";
import { PaperRow } from "./PaperRow";
import { Markets, marketLine } from "./Markets";
import { Settings } from "./Settings";
import { clock } from "./format";
import { groupBySection, isSectionKey, SECTIONS } from "./sections";
import "./dashboard.css";

type Section = "briefing" | "saved" | "settings" | string; // string = area key

function initialSection(): Section {
  const h = window.location.hash.replace("#", "");
  return h === "saved" || h === "settings" || isSectionKey(h) ? h : "briefing";
}

export function Dashboard() {
  const [section, setSection] = useState<Section>(initialSection);
  const [status, setStatus] = useState<Status | null>(null);
  const [latest, setLatest] = useState<Latest | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [list, setList] = useState<Paper[] | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"score" | "date">("score");
  const [error, setError] = useState<string | null>(null);
  const [fetchMsg, setFetchMsg] = useState<string | null>(null);
  const [mkt, setMkt] = useState<MarketRow[]>([]);

  const areaLabel = useMemo(() => {
    const m: Record<string, string> = {};
    profile?.areas.forEach((a) => (m[a.key] = a.label));
    return (k: string | null) => (k && m[k]) || "Other";
  }, [profile]);

  const load = useCallback(async () => {
    try {
      const [s, l, p] = await Promise.all([api.status(), api.latest(), api.profile()]);
      api.markets().then((m) => setMkt(m.markets?.rows ?? [])).catch(() => setMkt([]));
      setStatus(s);
      setLatest(l);
      setProfile(p);
      setError(null);
      // only count it as seen when this window is really on screen
      if (l.briefing && (await P.windowVisible())) void P.markBriefingSeen(l.briefing.id);
    } catch {
      setError("The butler's research desk isn't answering on 127.0.0.1:8765.");
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(load, status?.collecting ? 3000 : 30_000);
    return () => clearInterval(t);
  }, [load, status?.collecting]);

  useEffect(() => {
    const subs = [P.onDashboardSection((s) => setSection(s)), P.onWindowShown(() => void load())];
    return () => subs.forEach((u) => void u.then((f) => f()));
  }, [load]);

  // section lists
  useEffect(() => {
    if (section === "briefing" || section === "settings") return;
    setList(null);
    const t = setTimeout(() => {
      api
        .papers(section === "saved" ? { bookmarked: true, q, sort } : { section, q, sort })
        .then(setList)
        .catch(() => setList([]));
    }, q ? 200 : 0);
    return () => clearTimeout(t);
  }, [section, q, sort, status?.last_success?.id]);

  const fetchNow = async () => {
    setFetchMsg(null);
    try {
      const r = await api.runNow();
      setFetchMsg(r.started ? null : "Already collecting. Hang on.");
      void load();
    } catch {
      setFetchMsg("Couldn't start a fetch: the backend isn't running.");
    }
  };

  const updatePaper = (p: Paper) => {
    setLatest((l) => (l ? { ...l, items: l.items.map((x) => (x.id === p.id ? p : x)) } : l));
    setList((l) => (l ? l.map((x) => (x.id === p.id ? p : x)) : l));
  };

  const b = latest?.briefing;
  const items = latest?.items ?? [];
  const collecting = !!status?.collecting;
  const lastAttempt = status?.last_attempt;
  const failedSince = lastAttempt && lastAttempt.status === "failed" && (!b || lastAttempt.id > b.id) ? lastAttempt : null;

  const groups = groupBySection(items);
  const mix = groups.map((g) => `${g.items.length} in ${g.label}`);
  const mixText = mix.length > 1 ? `${mix.slice(0, -1).join(", ")} and ${mix[mix.length - 1]}` : mix[0] ?? "";
  const mline = marketLine(mkt);
  const current = SECTIONS.find((s2) => s2.key === section);

  const nav: { key: Section; label: string; count?: number }[] = [
    { key: "briefing", label: "Today's briefing", count: items.length || undefined },
    ...SECTIONS.map((s2) => ({ key: s2.key, label: s2.label, count: status?.section_counts?.[s2.key] })),
    { key: "saved", label: "Saved" },
  ];

  return (
    <div className="dash">
      <header className="masthead">
        <Sprite pose={collecting ? "phone" : items.length ? "serve" : "idle"} scale={0.92} className="mast-butler" />
        <div className="mast-text">
          <h1>{latest?.greeting ?? "Good day."}</h1>
          <p className="mast-sub">
            {collecting
              ? "Gathering papers, news and prices. This takes a minute or two."
              : b && items.length
                ? <>From the {clock(b.started_at)} briefing: {mixText}.</>
                : "No briefing yet. The first one arrives at the next scheduled time, or fetch now."}
          </p>
          {mline && <p className="mast-markets">{mline}</p>}
          <p className="mast-meta">
            Briefings at 8:00 AM and 8:00 PM Eastern.
            {status?.next_runs[0] && <> Next: {clock(status.next_runs[0])}.</>}
          </p>
        </div>
        <div className="mast-actions">
          <button type="button" className="btn-primary" onClick={fetchNow} disabled={collecting || !!error}>
            {collecting ? "Fetching…" : "Fetch now"}
          </button>
          {fetchMsg && <p className="mast-msg">{fetchMsg}</p>}
        </div>
      </header>

      <div className="layout">
        <nav className="sidenav" aria-label="Sections">
          <ul>
            {nav.map((n) => (
              <li key={n.key}>
                <button type="button" aria-current={section === n.key ? "page" : undefined} onClick={() => setSection(n.key)}>
                  <span>{n.label}</span>
                  {n.count ? <span className="count">{n.count}</span> : null}
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="nav-settings" aria-current={section === "settings" ? "page" : undefined}
            onClick={() => setSection("settings")}>
            Settings and diagnostics
          </button>
        </nav>

        <main className="main">
          {error && (
            <div className="notice is-error" role="alert">
              <strong>{error}</strong> Quit Desktop Butler from the menu bar and open it again. If that doesn't help,
              check <code>butler.log</code> in the data folder shown under Settings.
            </div>
          )}
          {failedSince && !error && (
            <div className="notice" role="status">
              <strong>The {clock(failedSince.started_at)} fetch didn't reach arXiv.</strong>{" "}
              {failedSince.errors?.[0]?.error ?? ""} You're seeing the last successful briefing; the butler retries every 30 minutes.
            </div>
          )}

          {section === "settings" ? (
            <Settings status={status} profile={profile} onReset={load} />
          ) : section === "briefing" ? (
            <section aria-label="Today's briefing">
              {items.length === 0 ? (
                <div className="empty">
                  <p>Nothing on the tray yet.</p>
                  <p className="empty-sub">Fetch now, or wait for the next briefing at {clock(status?.next_runs[0])}.</p>
                </div>
              ) : (
                groups.map((g) => (
                  <section key={g.key} className="brief-group" aria-label={g.label}>
                    <div className="group-head">
                      <h2>{g.label}</h2>
                      <button type="button" className="link" onClick={() => setSection(g.key)}>
                        See all in {g.label}
                      </button>
                    </div>
                    <div className="list">
                      {g.items.map((p) => (
                        <PaperRow key={p.id} paper={p} areaLabel={areaLabel(p.area)} alertThreshold={status?.alert_threshold ?? 80} onChange={updatePaper} />
                      ))}
                    </div>
                  </section>
                ))
              )}
              {b && <BriefingFooter b={b} />}
            </section>
          ) : (
            <section aria-label={current?.label ?? "Saved"}>
              {section === "market" && <Markets refreshKey={status?.last_success?.id} />}
              <div className="toolbar">
                <h2>{section === "market" ? "Moves, releases and market news" : current?.label ?? "Saved"}</h2>
                {current && section !== "market" && <p className="toolbar-blurb">{current.blurb}</p>}
                <input type="search" placeholder="Search titles, summaries, authors" value={q}
                  onChange={(e) => setQ(e.target.value)} aria-label={`Search ${current?.label ?? "saved items"}`} />
                <div className="seg" role="group" aria-label="Sort">
                  <button type="button" aria-pressed={sort === "score"} onClick={() => setSort("score")}>Best match</button>
                  <button type="button" aria-pressed={sort === "date"} onClick={() => setSort("date")}>Newest</button>
                </div>
              </div>
              {list === null ? (
                <p className="loading">Loading…</p>
              ) : list.length === 0 ? (
                <div className="empty">
                  <p>{section === "saved" ? "Nothing saved yet." : q ? `Nothing matches “${q}”.` : "Nothing here yet."}</p>
                  <p className="empty-sub">
                    {section === "saved" ? "Use “Save for later” on anything to keep it here." : "Items appear here after the next briefing."}
                  </p>
                </div>
              ) : (
                <div className="list">
                  {list.map((p) => (
                    <PaperRow key={p.id} paper={p} areaLabel={areaLabel(p.area)} alertThreshold={status?.alert_threshold ?? 80} onChange={updatePaper} />
                  ))}
                </div>
              )}
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function BriefingFooter({ b }: { b: Briefing }) {
  return (
    <p className="list-foot">
      Briefing {b.id} looked at {b.fetched} results from arXiv, news feeds and markets and found {b.new_papers} new item{b.new_papers === 1 ? "" : "s"}.
      {b.status === "partial" && " Some searches failed; see Settings and diagnostics."}
      {" "}Use ↑ ↓ to move, Enter to expand, S to save, O to open.
    </p>
  );
}
