// Browser demo: answers the same API calls from a snapshot produced by the real
// backend (tests/demo + the real ranking pipeline). Bookmarks and votes live in memory.

import type { Briefing, Latest, Markets, Paper, Profile, Status } from "../api";
import { sectionOf } from "../dashboard/sections";

interface Snapshot {
  status: Status;
  latest: Latest;
  profile: Profile;
  briefings: Briefing[];
  papers: Paper[];
  source_note: string;
}

let snap: Snapshot | null = null;
let loading: Promise<Snapshot> | null = null;
const bookmarks = new Set<string>();
const votes = new Map<string, "relevant" | "not_relevant">();
let collectingUntil = 0;

async function load(): Promise<Snapshot> {
  if (snap) return snap;
  loading ??= fetch("demo/snapshot.json").then((r) => {
    if (!r.ok) throw new Error(`snapshot ${r.status}`);
    return r.json() as Promise<Snapshot>;
  });
  snap = await loading;
  return snap;
}

const withState = (p: Paper): Paper => ({ ...p, bookmarked: bookmarks.has(p.id), feedback: votes.get(p.id) ?? null });

function greeting(owner: string): string {
  const h = new Date().getHours();
  const part = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return owner ? `${part}, ${owner}.` : `${part}.`;
}

/** Next 8:00 / 20:00 America/New_York instants, computed in the viewer's browser. */
function nextRuns(n = 2): string[] {
  const tz = "America/New_York";
  const offsetMin = (d: Date) => {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(d);
    const g = (t: string) => Number(parts.find((p) => p.type === t)?.value);
    return (Date.UTC(g("year"), g("month") - 1, g("day"), g("hour"), g("minute")) - d.getTime()) / 60000;
  };
  const now = Date.now();
  const out: string[] = [];
  const today = new Date();
  for (let day = -1; day < 3 && out.length < n; day++) {
    for (const h of [8, 20]) {
      const guess = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() + day, h));
      const t = new Date(guess.getTime() - offsetMin(guess) * 60000);
      if (t.getTime() > now && out.length < n) out.push(t.toISOString());
    }
  }
  return out;
}

export const demoApi = {
  status: async (): Promise<Status> => {
    const s = await load();
    const section_counts: Record<string, number> = {};
    s.papers.forEach((p) => (section_counts[sectionOf(p)] = (section_counts[sectionOf(p)] ?? 0) + 1));
    return { ...s.status, section_counts, collecting: Date.now() < collectingUntil, collecting_trigger: Date.now() < collectingUntil ? "manual" : null,
      next_runs: nextRuns() };
  },
  latest: async (): Promise<Latest> => {
    const s = await load();
    return { ...s.latest, greeting: greeting(s.profile.owner), items: s.latest.items.map(withState) };
  },
  profile: async () => (await load()).profile,
  briefings: async (limit = 10) => (await load()).briefings.slice(0, limit),
  paper: async (id: string): Promise<Paper> => {
    const p = (await load()).papers.find((x) => x.id === id);
    if (!p) throw new Error("paper not found");
    return withState(p);
  },
  markets: async (): Promise<Markets> => ({
    markets: null, macro: null, fred_enabled: false,
    unavailable: "Market prices load on your Mac at each briefing. This demo page can't reach Yahoo Finance or FRED, so it shows no numbers rather than made-up ones.",
  }),
  papers: async (o: { area?: string; q?: string; sort?: "score" | "date"; bookmarked?: boolean; limit?: number; kind?: "papers" | "news"; section?: string }) => {
    const s = await load();
    const q = o.q?.trim().toLowerCase();
    const isPaper = (p: Paper) => (p.source_type ?? "academic_paper") === "academic_paper";
    let list = s.papers.map(withState).filter((p) =>
      (!o.kind || (o.kind === "papers") === isPaper(p)) &&
      (!o.section || sectionOf(p) === o.section) &&
      (!o.area || p.area === o.area) &&
      (!o.bookmarked || p.bookmarked) &&
      (!q || `${p.title} ${p.abstract} ${p.authors.join(" ")}`.toLowerCase().includes(q)));
    list = list.sort((a, b) => o.sort === "date"
      ? (b.published_at ?? "").localeCompare(a.published_at ?? "")
      : (b.score ?? 0) - (a.score ?? 0));
    return list.slice(0, o.limit ?? 60);
  },
  runNow: async () => {
    if (Date.now() < collectingUntil) return { started: false, reason: "already collecting" };
    collectingUntil = Date.now() + 5000;
    return { started: true, reason: null };
  },
  feedback: async (id: string, kind: "relevant" | "not_relevant" | "opened") => {
    if (kind !== "opened") votes.set(id, kind);
    return { ok: true };
  },
  bookmark: async (id: string, on: boolean) => {
    if (on) bookmarks.add(id);
    else bookmarks.delete(id);
    return { ok: true };
  },
  resetPersonal: async () => {
    bookmarks.clear();
    votes.clear();
    return { ok: true };
  },
  sourceNote: async () => (await load()).source_note,
};
