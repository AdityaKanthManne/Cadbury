// What the butler is doing right now — a pure function so it can be unit tested.

import type { Latest, Status } from "../api";

export type Pose =
  | "idle" | "think" | "walk_r" | "walk_l" | "wave" | "point"
  | "bow" | "serve" | "phone" | "read" | "sleep" | "dust" | "jump";

export type Mood =
  | "collecting"   // on the phone to arXiv
  | "alert"        // unseen paper above the alert threshold (and not quiet)
  | "delivered"    // unseen briefing waiting on the tray
  | "trouble"      // last attempt failed (offline / arXiv down)
  | "no_backend"   // can't reach the local API
  | "sleeping"     // night hours, nothing new
  | "idle";

export interface MoodInput {
  status: Status | null;
  latest: Latest | null;
  backendUp: boolean;
  seenId: number;
  quiet: boolean;
  hour: number; // local hour 0-23
}

export function deriveMood(i: MoodInput): Mood {
  if (!i.backendUp) return "no_backend";
  if (i.status?.collecting) return "collecting";
  const b = i.latest?.briefing;
  const unseen = !!b && b.id > i.seenId && (i.latest?.items.length ?? 0) > 0;
  if (unseen && !i.quiet && (i.latest?.alerts?.length ?? 0) > 0) return "alert";
  if (unseen) return "delivered";
  const attempt = i.status?.last_attempt;
  if (attempt && attempt.status === "failed" && (!b || attempt.id > b.id)) return "trouble";
  if (i.hour >= 23 || i.hour < 7) return "sleeping";
  return "idle";
}

export const MOOD_POSE: Record<Mood, Pose> = {
  collecting: "phone",
  alert: "point",
  delivered: "serve",
  trouble: "think",
  no_backend: "think",
  sleeping: "sleep",
  idle: "idle",
};

function fmtTime(iso: string | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** One or two short sentences for the hover bubble. */
export function moodLine(mood: Mood, i: MoodInput): string {
  const next = fmtTime(i.status?.next_runs[0]);
  const items = i.latest?.items ?? [];
  const top = items[0];
  switch (mood) {
    case "collecting":
      return "Gathering papers, news and prices. Back shortly.";
    case "alert": {
      const hot = items.find((p) => i.latest?.alerts?.includes(p.id)) ?? top;
      return `This one stands out: “${hot.title}” (score ${Math.round(hot.score ?? 0)}). Click to read.`;
    }
    case "delivered":
      return `Your briefing is ready: ${items.length} item${items.length === 1 ? "" : "s"}. Top pick: “${top.title}”.`;
    case "trouble":
      return "I couldn't reach my sources last time. I'll try again every 30 minutes.";
    case "no_backend":
      return "My research desk isn't answering. Quit and reopen Desktop Butler.";
    case "sleeping":
      return next ? `Resting until ${next}. Click for the last briefing.` : "Resting. Click for the last briefing.";
    default:
      return next ? `Next briefing at ${next}. Click to see the latest one.` : "Click to see the latest briefing.";
  }
}
