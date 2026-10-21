// What the butler does next when nobody is asking anything of him.
// Pure: all randomness and screen state come in as arguments, so it's testable.

import type { Mood, Pose } from "./mood";

export interface Pos { x: number; y: number }
/** Where the butler window's top-left corner may go (logical px). */
export interface Bounds { x: number; y: number; w: number; h: number }

export type Activity =
  | { kind: "walk"; to: Pos }
  | { kind: "pose"; pose: Extract<Pose, "read" | "dust" | "sleep" | "idle" | "think">; ms: number }
  | { kind: "deliver"; paperId: string; to: Pos };

export interface ChooseInput {
  mood: Mood;
  hour: number;
  pos: Pos;
  bounds: Bounds;
  /** briefing papers he hasn't left a note about yet, best first */
  undelivered: string[];
  briefingSeen: boolean;
  notesOnScreen: number;
  rand: () => number; // 0..1
}

export const MAX_NOTES = 3;

/** Roaming only happens in calm moods; the others own the stage. */
export function canRoam(mood: Mood): boolean {
  return mood === "idle" || mood === "delivered" || mood === "alert" || mood === "trouble";
}

const between = (r: () => number, a: number, b: number) => a + (b - a) * r();

export function randomSpot(b: Bounds, r: () => number, from?: Pos, minDist = 160): Pos {
  let best: Pos = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
  for (let i = 0; i < 8; i++) {
    const p = { x: Math.round(between(r, b.x, b.x + b.w)), y: Math.round(between(r, b.y, b.y + b.h)) };
    best = p;
    if (!from || Math.hypot(p.x - from.x, p.y - from.y) >= minDist) break;
  }
  return best;
}

/** Where to present a note: across the middle of the screen, a different third for each note on the desk. */
export function presentingSpot(b: Bounds, r: () => number, notesOnScreen = 0): Pos {
  const bands: [number, number][] = [[0.3, 0.5], [0.6, 0.85], [0.08, 0.25]];
  const [a, z] = bands[notesOnScreen % bands.length];
  return {
    x: Math.round(b.x + b.w * between(r, a, z)),
    y: Math.round(b.y + b.h * between(r, 0.35, 0.75)),
  };
}

export function chooseActivity(i: ChooseInput): Activity {
  const r = i.rand;
  const night = i.hour >= 21 || i.hour < 7;

  // Papers first: an unread briefing is the reason he exists.
  const canDeliver = i.undelivered.length > 0 && i.notesOnScreen < MAX_NOTES;
  if (canDeliver && r() < (i.briefingSeen ? 0.15 : 0.55)) {
    return { kind: "deliver", paperId: i.undelivered[0], to: presentingSpot(i.bounds, r, i.notesOnScreen) };
  }
  if (i.mood === "trouble") {
    return r() < 0.5 ? { kind: "pose", pose: "think", ms: between(r, 6000, 12000) } : { kind: "walk", to: randomSpot(i.bounds, r, i.pos) };
  }

  const roll = r();
  // the armchair is for evenings once the work is done
  const workPending = !i.briefingSeen && i.undelivered.length > 0;
  if (night && !workPending && roll < 0.35) return { kind: "pose", pose: "sleep", ms: between(r, 30000, 60000) };
  if (roll < 0.5) return { kind: "walk", to: randomSpot(i.bounds, r, i.pos) };
  if (roll < 0.66) return { kind: "pose", pose: "read", ms: between(r, 9000, 18000) };
  if (roll < 0.79) return { kind: "pose", pose: "dust", ms: between(r, 4000, 8000) };
  if (roll < 0.84) return workPending ? { kind: "pose", pose: "read", ms: between(r, 6000, 10000) } : { kind: "pose", pose: "sleep", ms: between(r, 15000, 25000) };
  return { kind: "pose", pose: "idle", ms: between(r, 5000, 10000) };
}

/** Straight-line walk, one point per frame. Speed in px per second. */
export function walkPath(from: Pos, to: Pos, speed = 120, fps = 30): Pos[] {
  const dist = Math.hypot(to.x - from.x, to.y - from.y);
  const steps = Math.max(1, Math.round((dist / speed) * fps));
  return Array.from({ length: steps }, (_, k) => {
    const t = (k + 1) / steps;
    return { x: Math.round(from.x + (to.x - from.x) * t), y: Math.round(from.y + (to.y - from.y) * t) };
  });
}

/** Put a note beside the butler, on whichever side has room. */
export function notePosition(butler: Pos, b: Bounds, noteW = 280, butlerW = 240): Pos {
  const screenRight = b.x + b.w + butlerW;
  const left = butler.x - noteW + 30;
  const x = left >= b.x - 20 ? left : Math.min(butler.x + butlerW - 30, screenRight - noteW);
  return { x: Math.round(x), y: Math.round(butler.y + 70) };
}
