import { describe, expect, it } from "vitest";
import type { Briefing, Latest, Paper, Status } from "../api";
import { deriveMood, moodLine } from "./mood";

const brief = (id: number, status: Briefing["status"] = "ok"): Briefing => ({
  id, trigger: "scheduled", status, started_at: "2026-10-20T12:00:00+00:00", finished_at: null,
  fetched: 10, new_papers: 3, item_ids: [], errors: [],
});
const paper = (id: string, score: number) => ({ id, title: `Paper ${id}`, score } as Paper);
const status = (o: Partial<Status> = {}): Status => ({
  collecting: false, collecting_trigger: null, scheduler_running: true, timezone: "America/New_York",
  schedule: ["08:00", "20:00"], next_runs: ["2026-10-21T12:00:00+00:00"], last_success: null,
  last_attempt: null, paper_count: 0, area_counts: {}, alert_threshold: 80, data_dir: "/tmp", ...o,
});
const latest = (b: Briefing | null, items: Paper[] = [], alerts: string[] = []): Latest =>
  ({ briefing: b, greeting: "Good evening.", items, alerts });

const base = { status: status(), latest: latest(brief(1), [paper("a", 70)]), backendUp: true, seenId: 1, quiet: false, hour: 14 };

describe("deriveMood", () => {
  it("is idle when the briefing has been seen", () => expect(deriveMood(base)).toBe("idle"));
  it("serves an unseen briefing", () => expect(deriveMood({ ...base, seenId: 0 })).toBe("delivered"));
  it("points at an urgent paper", () =>
    expect(deriveMood({ ...base, seenId: 0, latest: latest(brief(1), [paper("a", 90)], ["a"]) })).toBe("alert"));
  it("quiet mode suppresses the alert but still serves", () =>
    expect(deriveMood({ ...base, seenId: 0, quiet: true, latest: latest(brief(1), [paper("a", 90)], ["a"]) })).toBe("delivered"));
  it("is on the phone while collecting", () =>
    expect(deriveMood({ ...base, status: status({ collecting: true }) })).toBe("collecting"));
  it("reports trouble when the latest attempt failed", () =>
    expect(deriveMood({ ...base, status: status({ last_attempt: brief(2, "failed") }) })).toBe("trouble"));
  it("sleeps at night", () => expect(deriveMood({ ...base, hour: 2 })).toBe("sleeping"));
  it("a waiting briefing wakes him up", () => expect(deriveMood({ ...base, hour: 2, seenId: 0 })).toBe("delivered"));
  it("knows when the backend is down", () => expect(deriveMood({ ...base, backendUp: false })).toBe("no_backend"));
  it("an empty briefing is not 'delivered'", () =>
    expect(deriveMood({ ...base, seenId: 0, latest: latest(brief(1), []) })).toBe("idle"));
});

describe("moodLine", () => {
  it("names the top pick", () => {
    const i = { ...base, seenId: 0 };
    expect(moodLine("delivered", i)).toContain("Paper a");
  });
});
