// Runs the butler's life while he's left alone: pick an activity, do it, pause, repeat.

import { useEffect, useRef } from "react";
import type { Latest } from "../api";
import * as P from "../platform";
import { chooseActivity, notePosition, walkPath, type Pos } from "./behavior";
import type { Mood, Pose } from "./mood";

interface Options {
  enabled: boolean;
  mood: Mood;
  latest: Latest | null;
  briefingSeen: boolean;
  setPose: (p: Pose | null) => void;
}

const WALK_SPEED = 120; // px per second
const FPS = 30;

class Aborted extends Error {}

export function useRoaming(o: Options) {
  // the loop reads fresh values through refs instead of restarting on every poll
  const ref = useRef(o);
  ref.current = o;

  useEffect(() => {
    if (!o.enabled) return;
    const ctrl = new AbortController();
    const sig = ctrl.signal;
    const check = () => {
      if (sig.aborted) throw new Aborted();
    };
    const sleep = (ms: number) =>
      new Promise<void>((resolve, reject) => {
        const t = window.setTimeout(resolve, ms);
        sig.addEventListener("abort", () => {
          window.clearTimeout(t);
          reject(new Aborted());
        }, { once: true });
      });

    const walk = async (from: Pos, to: Pos) => {
      const path = walkPath(from, to, WALK_SPEED, FPS);
      ref.current.setPose(to.x < from.x ? "walk_l" : "walk_r");
      for (const p of path) {
        check();
        await P.moveButler(p);
        await sleep(1000 / FPS);
      }
      ref.current.setPose(null);
    };

    (async () => {
      const speed = await P.behaviorSpeed();
      const wait = (ms: number) => sleep(ms / speed);
      await wait(4000);
      for (;;) {
        check();
        const bounds = await P.roamBounds();
        if (!bounds) return;
        const pos = await P.butlerPos();
        const cur = ref.current;
        const noted = P.notedIds();
        const undelivered = (cur.latest?.items ?? [])
          .filter((p) => !noted.has(p.id) && !p.bookmarked && p.feedback !== "not_relevant")
          .map((p) => p.id);
        const act = chooseActivity({
          mood: cur.mood, hour: new Date().getHours(), pos, bounds, undelivered,
          briefingSeen: cur.briefingSeen, notesOnScreen: await P.noteCount(), rand: Math.random,
        });

        if (act.kind === "walk") {
          await walk(pos, act.to);
        } else if (act.kind === "pose") {
          cur.setPose(act.pose);
          await wait(act.ms);
          ref.current.setPose(null);
        } else {
          await walk(pos, act.to);
          ref.current.setPose("serve");
          await wait(1500);
          await P.spawnNote(act.paperId, notePosition(await P.butlerPos(), bounds));
          P.markNoted(act.paperId);
          ref.current.setPose("bow");
          await wait(1200);
          ref.current.setPose(null);
        }
        await wait(3000 + Math.random() * 7000);
      }
    })()
      .catch((e) => {
        if (!(e instanceof Aborted)) console.error("roaming stopped:", e);
      })
      .finally(() => ref.current.setPose(null));

    return () => ctrl.abort();
  }, [o.enabled]);
}
