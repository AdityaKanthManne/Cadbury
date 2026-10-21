// The dashboard's four sections. Mirrors services/butler/butler/sections.py.

import type { Paper } from "../api";

export type SectionKey = "market" | "research" | "news" | "tech";

export const SECTIONS: { key: SectionKey; label: string; blurb: string }[] = [
  { key: "market", label: "Market", blurb: "Price moves, Federal Reserve releases, market and macro news." },
  { key: "research", label: "Research", blurb: "New papers from arXiv, ranked against your interests." },
  { key: "news", label: "News", blurb: "Quant firms, funds and the industry." },
  { key: "tech", label: "Tech developments", blurb: "AI labs, engineering blogs, Hacker News, AI and infrastructure news." },
];

const BY_SOURCE: Record<string, SectionKey> = {
  market_move: "market", official: "market", academic_paper: "research",
  lab_blog: "tech", research_blog: "tech", discussion: "tech",
};
const NEWS_BY_AREA: Record<string, SectionKey> = { markets_macro: "market", ai_ml: "tech", infra: "tech" };

/** The backend assigns sections; this fallback covers items scored before sections existed. */
export function sectionOf(p: Pick<Paper, "section" | "source_type" | "area">): SectionKey {
  if (p.section && SECTIONS.some((s) => s.key === p.section)) return p.section as SectionKey;
  const bySource = BY_SOURCE[p.source_type ?? "academic_paper"];
  if (bySource) return bySource;
  return NEWS_BY_AREA[p.area ?? ""] ?? "news";
}

/** Briefing items grouped in section order, keeping their ranked order inside each group. */
export function groupBySection<T extends Pick<Paper, "section" | "source_type" | "area">>(items: T[]) {
  return SECTIONS.map((s) => ({ ...s, items: items.filter((i) => sectionOf(i) === s.key) })).filter((g) => g.items.length);
}

export function isSectionKey(x: string): x is SectionKey {
  return SECTIONS.some((s) => s.key === x);
}
