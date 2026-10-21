import { useState } from "react";
import type { Paper, Signal } from "../api";
import { api } from "../api";
import { inTauri, openExternal } from "../platform";
import { authors, shortDate } from "./format";

const SIGNALS: { key: Signal; name: string; weight: number; hint: string }[] = [
  { key: "R", name: "Relevance", weight: 30, hint: "match to your interest profile" },
  { key: "Q", name: "Source quality", weight: 20, hint: "outlet, publication status, community votes" },
  { key: "N", name: "Novelty", weight: 15, hint: "unlike papers you've already seen" },
  { key: "I", name: "Impact", weight: 15, hint: "benchmarks, real data, large-scale results" },
  { key: "F", name: "Freshness", weight: 10, hint: "how recently it was published; news fades fastest" },
  { key: "P", name: "Learning value", weight: 10, hint: "code released, implementable method" },
];

interface Props {
  paper: Paper;
  areaLabel: string;
  alertThreshold: number;
  onChange: (p: Paper) => void;
}

export function PaperRow({ paper, areaLabel, alertThreshold, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const score = Math.round(paper.score ?? 0);
  const high = score >= alertThreshold;

  const toggleSave = async () => {
    const on = !paper.bookmarked;
    onChange({ ...paper, bookmarked: on });
    await api.bookmark(paper.id, on).catch(() => onChange(paper));
  };
  const vote = async (kind: "relevant" | "not_relevant") => {
    onChange({ ...paper, feedback: kind });
    await api.feedback(paper.id, kind).catch(() => onChange(paper));
  };
  const https = (url: string | null) => (url ? url.replace(/^http:/, "https:") : "");
  const openLink = (url: string | null) => {
    if (!url) return;
    void api.feedback(paper.id, "opened").catch(() => {});
    void openExternal(https(url));
  };
  // Real <a> links; inside the desktop app they're routed through the system browser.
  const linkProps = (url: string | null) => ({
    href: https(url),
    target: "_blank",
    rel: "noopener noreferrer",
    onClick: (e: React.MouseEvent) => {
      if (inTauri) {
        e.preventDefault();
        openLink(url);
      } else {
        void api.feedback(paper.id, "opened").catch(() => {});
      }
    },
  });
  const kind = paper.source_type ?? "academic_paper";
  const meta = paper.meta ?? {};
  const host = (() => {
    try {
      return new URL(paper.url).hostname.replace(/^www\./, "");
    } catch {
      return paper.source;
    }
  })();
  const source = sourceLine(paper, areaLabel);
  const primaryLabel =
    kind === "academic_paper" ? "Open on arXiv"
    : kind === "market_move" ? "View on Yahoo Finance"
    : kind === "discussion" ? (paper.url === meta.discussion_url ? "Open discussion" : `Open link (${host})`)
    : `Read on ${meta.domain || host}`;
  const detail = detailText(paper);

  const onKey = (e: React.KeyboardEvent<HTMLElement>) => {
    if (e.target !== e.currentTarget) return;
    const row = e.currentTarget;
    if (e.key === "ArrowDown" || e.key === "j") {
      e.preventDefault();
      (row.nextElementSibling as HTMLElement | null)?.focus();
    } else if (e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      (row.previousElementSibling as HTMLElement | null)?.focus();
    } else if (e.key === "Enter") {
      setOpen((o) => !o);
    } else if (e.key === "s") {
      void toggleSave();
    } else if (e.key === "o") {
      openLink(paper.url);
    }
  };

  return (
    <article className={`paper ${high ? "is-high" : ""}`} tabIndex={0} onKeyDown={onKey} aria-expanded={open}>
      <div className="paper-score" title={`Score ${score} of 100`}>
        <span className="score-num">{score}</span>
      </div>

      <div className="paper-body">
        <h3 className="paper-title">
          <button type="button" onClick={() => setOpen((o) => !o)}>{paper.title}</button>
        </h3>
        {paper.why && <p className="paper-why">{paper.why}</p>}
        <p className="paper-meta">{source}</p>

        <div className="paper-actions">
          <a className="link" {...linkProps(paper.url)}>{primaryLabel}</a>
          {paper.pdf_url && <a className="link" {...linkProps(paper.pdf_url)}>PDF</a>}
          {kind === "discussion" && meta.discussion_url && paper.url !== meta.discussion_url && (
            <a className="link" {...linkProps(meta.discussion_url)}>Discussion ({meta.comments ?? 0})</a>
          )}
          <button type="button" className={`chip ${paper.bookmarked ? "is-on" : ""}`} aria-pressed={paper.bookmarked} onClick={toggleSave}>
            {paper.bookmarked ? "Saved" : "Save for later"}
          </button>
          <span className="vote" role="group" aria-label="Was this relevant?">
            <button type="button" className={`chip ${paper.feedback === "relevant" ? "is-on" : ""}`}
              aria-pressed={paper.feedback === "relevant"} onClick={() => vote("relevant")}>Relevant</button>
            <button type="button" className={`chip ${paper.feedback === "not_relevant" ? "is-on" : ""}`}
              aria-pressed={paper.feedback === "not_relevant"} onClick={() => vote("not_relevant")}>Not for me</button>
          </span>
        </div>

        {open && (
          <div className="paper-detail">
            <div className="abstract">
              <h4>{detail.heading}</h4>
              {paper.abstract && <p>{paper.abstract}</p>}
              <p className="note">{detail.note}</p>
              {meta.coverage && meta.coverage.length > 0 && (
                <p className="note">Also reported by {meta.coverage.join(", ")}.</p>
              )}
            </div>
            <div className="signals">
              <h4>How it scored {score}</h4>
              <ul>
                {SIGNALS.map((s) => {
                  const v = paper.breakdown?.[s.key] ?? 0;
                  return (
                    <li key={s.key} title={s.hint}>
                      <span className="sig-name">{s.name}</span>
                      <span className="sig-bar" aria-hidden><span style={{ width: `${v * 100}%` }} /></span>
                      <span className="sig-val">{Math.round(v * 100)}</span>
                      <span className="sig-w">×{s.weight}%</span>
                    </li>
                  );
                })}
              </ul>
              {paper.breakdown?.filtered && <p className="note">Halved: barely matches your interests.</p>}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

/** One plain line saying where this came from. */
function sourceLine(p: Paper, area: string): string {
  const m = p.meta ?? {};
  const when = shortDate(p.published_at);
  switch (p.source_type ?? "academic_paper") {
    case "academic_paper":
      return `${authors(p.authors)}. ${area}, ${p.primary_category ?? "arXiv"}, published ${when}.`;
    case "news": {
      const more = m.coverage?.length ? ` and ${m.coverage.length} other outlet${m.coverage.length === 1 ? "" : "s"}` : "";
      return `${m.domain || p.source}${more}. ${area}, seen ${when}.`;
    }
    case "discussion":
      return `Hacker News, ${m.points ?? 0} points, ${m.comments ?? 0} comments. ${area}, posted ${when}.`;
    case "market_move":
      return `Yahoo Finance via yfinance (delayed). ${area}, ${when}.`;
    default:
      return `${p.source}${p.authors.length ? `, ${authors(p.authors)}` : ""}. ${area}, published ${when}.`;
  }
}

function detailText(p: Paper): { heading: string; note: string } {
  switch (p.content_access) {
    case "paraphrase":
      return { heading: "Summary", note: "A short paraphrase of the abstract, made for this demo. The original abstract is on arXiv." };
    case "summary":
      return { heading: "From the publisher's feed", note: "This is the feed's own summary. Open the article for the full text." };
    case "headline_only":
      return { heading: "Headline only", note: "The butler only has the headline for this one. Open the article for the story." };
    case "computed":
      return { heading: "Details", note: "Computed from delayed market data, not a news report." };
    default:
      return { heading: "Abstract", note: "The butler has only read the abstract; the full paper is on arXiv." };
  }
}
