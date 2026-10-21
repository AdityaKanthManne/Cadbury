// Typed client for the local Python backend (services/butler).

const params = new URLSearchParams(window.location.search);
export const API_BASE = params.get("api") ?? "http://127.0.0.1:8765";

export type Signal = "R" | "Q" | "N" | "I" | "F" | "P";

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  abstract: string;
  published_at: string | null;
  retrieved_at: string;
  url: string;
  pdf_url: string | null;
  source: string;
  source_type: string;
  content_access: string;
  primary_category: string | null;
  categories: string[];
  area: string | null;
  score: number | null;
  breakdown: (Record<Signal, number> & { filtered?: boolean }) | null;
  why: string | null;
  matched: Record<string, string[]> | null;
  bookmarked: boolean;
  feedback: "relevant" | "not_relevant" | null;
  section?: "market" | "research" | "news" | "tech" | null;
  meta?: {
    domain?: string; via?: string; top_outlet?: boolean; coverage?: string[];
    points?: number; comments?: number; discussion_url?: string;
    ticker?: string; change_pct?: number; feed?: string;
  };
}

export interface MarketRow {
  ticker: string; name: string; kind: string; last: number; prev: number;
  change_pct: number; change_bp: number | null; as_of: string; closes: number[];
}
export interface MacroRow {
  id: string; name: string; units: string; latest: number; date: string;
  previous: number | null; yoy_pct?: number; url: string;
}
export interface Markets {
  markets: { taken_at: string; rows: MarketRow[] } | null;
  macro: { taken_at: string; rows: MacroRow[]; needs_key: boolean } | null;
  fred_enabled: boolean;
  unavailable?: string; // demo: why there's no data
}

export interface Briefing {
  id: number;
  trigger: string;
  status: "running" | "ok" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  fetched: number;
  new_papers: number;
  item_ids: string[] | null;
  errors: { source: string; error: string }[] | null;
}

export interface Latest {
  briefing: Briefing | null;
  greeting: string;
  items: Paper[];
  alerts?: string[];
}

export interface Status {
  collecting: boolean;
  collecting_trigger: string | null;
  scheduler_running: boolean;
  timezone: string;
  schedule: string[];
  next_runs: string[];
  last_success: Briefing | null;
  last_attempt: Briefing | null;
  paper_count: number;
  area_counts: Record<string, number>;
  section_counts?: Record<string, number>;
  alert_threshold: number;
  data_dir: string;
}

export interface Area {
  key: string;
  label: string;
  weight: number;
  keywords: string[];
}

export interface Profile {
  owner: string;
  areas: Area[];
  searches: { name: string; query: string; max_results: number }[];
  briefing_size: number;
  alert_threshold: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
  return res.json() as Promise<T>;
}

const realApi = {
  status: () => req<Status>("/api/status"),
  latest: () => req<Latest>("/api/briefings/latest"),
  profile: () => req<Profile>("/api/profile"),
  briefings: (limit = 10) => req<Briefing[]>(`/api/briefings?limit=${limit}`),
  paper: (id: string) => req<Paper>(`/api/papers/${encodeURIComponent(id)}`),
  markets: () => req<Markets>("/api/markets"),
  papers: (o: { area?: string; q?: string; sort?: "score" | "date"; bookmarked?: boolean; limit?: number; kind?: "papers" | "news"; section?: string }) => {
    const p = new URLSearchParams();
    if (o.section) p.set("section", o.section);
    if (o.kind) p.set("kind", o.kind);
    if (o.area) p.set("area", o.area);
    if (o.q) p.set("q", o.q);
    if (o.sort) p.set("sort", o.sort);
    if (o.bookmarked) p.set("bookmarked", "true");
    p.set("limit", String(o.limit ?? 60));
    return req<Paper[]>(`/api/papers?${p}`);
  },
  runNow: () => req<{ started: boolean; reason: string | null }>("/api/briefings/run", { method: "POST" }),
  feedback: (id: string, kind: "relevant" | "not_relevant" | "opened") =>
    req(`/api/papers/${encodeURIComponent(id)}/feedback`, { method: "POST", body: JSON.stringify({ kind }) }),
  bookmark: (id: string, on: boolean) =>
    req(`/api/papers/${encodeURIComponent(id)}/bookmark`, { method: "POST", body: JSON.stringify({ on }) }),
  resetPersonal: () => req("/api/personal-data/reset", { method: "POST" }),
};

import { demoApi } from "./demo/mockApi";
export const DEMO = import.meta.env.VITE_DEMO === "1";
export const api: typeof realApi = DEMO ? demoApi : realApi;
