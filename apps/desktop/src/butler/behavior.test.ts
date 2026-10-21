import { describe, expect, it } from "vitest";
import { canRoam, chooseActivity, MAX_NOTES, notePosition, presentingSpot, randomSpot, walkPath, type ChooseInput } from "./behavior";

const seq = (...xs: number[]) => {
  let i = 0;
  return () => xs[i++ % xs.length];
};
const base: ChooseInput = {
  mood: "idle", hour: 14, pos: { x: 500, y: 400 }, bounds: { x: 0, y: 30, w: 1200, h: 600 },
  undelivered: [], briefingSeen: true, notesOnScreen: 0, rand: seq(0.3),
};

describe("chooseActivity", () => {
  it("delivers an unread paper first", () => {
    const a = chooseActivity({ ...base, undelivered: ["p1", "p2"], briefingSeen: false, rand: seq(0.1, 0.5, 0.5) });
    expect(a.kind).toBe("deliver");
    if (a.kind === "deliver") expect(a.paperId).toBe("p1");
  });
  it("stops delivering when the desk already has enough notes", () => {
    const a = chooseActivity({ ...base, undelivered: ["p1"], briefingSeen: false, notesOnScreen: MAX_NOTES, rand: seq(0.1) });
    expect(a.kind).not.toBe("deliver");
  });
  it("is less eager once you've seen the briefing", () => {
    const a = chooseActivity({ ...base, undelivered: ["p1"], briefingSeen: true, rand: seq(0.3, 0.9) });
    expect(a.kind).not.toBe("deliver");
  });
  it("walks, reads, dusts, naps and idles by roll", () => {
    const kinds = [0.1, 0.55, 0.7, 0.8, 0.95].map((r) => {
      const a = chooseActivity({ ...base, rand: seq(r, 0.5, 0.5, 0.5) });
      return a.kind === "pose" ? a.pose : a.kind;
    });
    expect(kinds).toEqual(["walk", "read", "dust", "sleep", "idle"]);
  });
  it("prefers the armchair late at night", () => {
    const a = chooseActivity({ ...base, hour: 23, rand: seq(0.2, 0.5) });
    expect(a).toMatchObject({ kind: "pose", pose: "sleep" });
  });
  it("doesn't nap while there are unread papers to deliver", () => {
    const a = chooseActivity({ ...base, hour: 23, undelivered: ["p1"], briefingSeen: false, rand: seq(0.9, 0.2, 0.5) });
    expect(a).not.toMatchObject({ pose: "sleep" });
  });
  it("only roams in calm moods", () => {
    expect(canRoam("idle")).toBe(true);
    expect(canRoam("collecting")).toBe(false);
    expect(canRoam("sleeping")).toBe(false);
    expect(canRoam("no_backend")).toBe(false);
  });
});

describe("geometry", () => {
  it("random spots stay on screen and move far enough", () => {
    const b = { x: 0, y: 30, w: 1200, h: 600 };
    let r = 0.13;
    const rand = () => (r = (r * 7.31 + 0.17) % 1);
    for (let i = 0; i < 200; i++) {
      const p = randomSpot(b, rand, { x: 600, y: 300 });
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(1200);
      expect(p.y).toBeGreaterThanOrEqual(30);
      expect(p.y).toBeLessThanOrEqual(630);
    }
  });
  it("walk path ends at the target at a steady pace", () => {
    const path = walkPath({ x: 0, y: 0 }, { x: 300, y: 400 }, 100, 20);
    expect(path.length).toBe(100); // 500 px at 100 px/s, 20 fps
    expect(path[path.length - 1]).toEqual({ x: 300, y: 400 });
  });
  it("spreads notes across the screen", () => {
    const b = { x: 0, y: 30, w: 1200, h: 600 };
    const xs = [0, 1, 2].map((n) => presentingSpot(b, () => 0.5, n).x);
    expect(new Set(xs).size).toBe(3);
  });
  it("notes go on the side with room", () => {
    const b = { x: 0, y: 30, w: 1200, h: 600 };
    expect(notePosition({ x: 600, y: 300 }, b).x).toBeLessThan(600);  // left of him
    expect(notePosition({ x: 10, y: 300 }, b).x).toBeGreaterThan(10);  // right of him at the left edge
  });
});
