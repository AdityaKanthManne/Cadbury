import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Latest, type Status } from "../api";
import * as P from "../platform";
import { deriveMood, MOOD_POSE, moodLine, type Pose } from "./mood";
import { canRoam } from "./behavior";
import { useRoaming } from "./useRoaming";
import { prefersReducedMotion, Sprite } from "./Sprite";
import "./butler.css";

const POLL_MS = P.inDemo ? 2_000 : 20_000;
const DRAG_THRESHOLD = 4;

export function ButlerWindow() {
  const [status, setStatus] = useState<Status | null>(null);
  const [latest, setLatest] = useState<Latest | null>(null);
  const [backendUp, setBackendUp] = useState(true);
  const [seenId, setSeenId] = useState(P.seenBriefingId());
  const [settings, setSettings] = useState(P.loadSettings());
  const [hover, setHover] = useState(false);
  const [override, setOverride] = useState<Pose | null>(null); // short reactions: wave, bow, walk
  const [autostart, setAutostart] = useState(false);
  const press = useRef<{ x: number; y: number; dragging: boolean } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([api.status(), api.latest()]);
      setStatus(s);
      setLatest(l);
      setBackendUp(true);
    } catch {
      setBackendUp(false);
    }
  }, []);

  // polling (faster while collecting so the phone call ends promptly)
  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, status?.collecting ? 3000 : POLL_MS);
    return () => clearInterval(t);
  }, [refresh, status?.collecting]);

  useEffect(() => {
    void P.placeButlerFirstTime();
    void P.autostartEnabled().then(setAutostart).catch(() => {});
    const subs = [
      P.onSettingsChanged((s) => setSettings(s)),
      P.onBriefingSeen((id) => setSeenId(id)),
    ];
    return () => subs.forEach((p) => void p.then((u) => u()));
  }, []);

  useEffect(() => {
    void P.setOnTop(settings.onTop);
  }, [settings.onTop]);

  const hour = new Date().getHours();
  const input = { status, latest, backendUp, seenId, quiet: settings.quiet, hour };
  const mood = deriveMood(input);
  const pose: Pose = override ?? MOOD_POSE[mood];
  const line = moodLine(mood, input);

  const react = useCallback((p: Pose, ms: number) => {
    setOverride(p);
    window.setTimeout(() => setOverride(null), ms);
  }, []);

  // his life when left alone: roam, read, dust, nap, leave notes about unread papers
  useRoaming({
    enabled: settings.wander && !settings.quiet && !hover && !prefersReducedMotion() && canRoam(mood),
    mood,
    latest,
    briefingSeen: !!latest?.briefing && latest.briefing.id <= seenId,
    setPose: (p) => setOverride(p),
  });

  // a paper worth interrupting for: a little jump, then he points at it
  const prevMood = useRef(mood);
  useEffect(() => {
    if (mood === "alert" && prevMood.current !== "alert" && !prefersReducedMotion()) react("jump", 520);
    prevMood.current = mood;
  }, [mood, react]);

  const openBriefing = useCallback(() => {
    react("bow", 1200);
    void P.openDashboard("briefing");
  }, [react]);

  const fetchNow = useCallback(async () => {
    await api.runNow().catch(() => {});
    void refresh();
  }, [refresh]);

  const changeSettings = useCallback((s: typeof settings) => {
    setSettings(s);
    void P.saveSettings(s);
  }, []);

  // --- pointer: click opens, drag moves -----------------------------------
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    press.current = { x: e.clientX, y: e.clientY, dragging: false };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const p = press.current;
    if (!p || p.dragging) return;
    if (Math.hypot(e.clientX - p.x, e.clientY - p.y) > DRAG_THRESHOLD) {
      p.dragging = true;
      void P.startDrag().finally(() => (press.current = null));
    }
  };
  const onPointerUp = () => {
    const p = press.current;
    press.current = null;
    if (p && !p.dragging) openBriefing();
  };
  const onContextMenu = async (e: React.MouseEvent) => {
    e.preventDefault();
    await P.showButlerMenu({
      openBriefing,
      fetchNow,
      settings,
      onSettings: changeSettings,
      autostart,
      onAutostart: (on) => void P.setAutostart(on).then(() => setAutostart(on)),
    });
  };

  const unseenCount = mood === "delivered" || mood === "alert" ? latest?.items.length ?? 0 : 0;

  return (
    <div className="butler-stage" data-mood={mood}>
      <div className={`bubble ${hover ? "is-visible" : ""}`} role="status" aria-live="polite">
        {line}
      </div>
      <button
        type="button"
        className="butler-hit"
        aria-label={`Desktop Butler. ${line} Click to open the briefing.`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onContextMenu={onContextMenu}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && openBriefing()}
        onMouseEnter={() => {
          setHover(true);
          if (mood === "idle" && !override) react("wave", 1400);
        }}
        onMouseLeave={() => setHover(false)}
      >
        <Sprite pose={pose} className={`butler-sprite pose-${pose}`} label={line} />
        {unseenCount > 0 && <span className="badge" aria-hidden>{unseenCount}</span>}
        {mood === "sleeping" && <span className="zzz" aria-hidden>z z z</span>}
      </button>
    </div>
  );
}
