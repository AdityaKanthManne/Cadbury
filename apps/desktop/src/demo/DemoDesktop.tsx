import { useCallback, useEffect, useRef, useState } from "react";
import { ButlerWindow } from "../butler/ButlerWindow";
import { Dashboard } from "../dashboard/Dashboard";
import { demoApi } from "./mockApi";
import { Face } from "../butler/Sprite";
import { NoteCard } from "../butler/NoteCard";
import * as P from "../platform";
import "./demo.css";

type Pos = { x: number; y: number };
const BUTLER_W = 240, BUTLER_H = 290;

function defaultPos(): Pos {
  return { x: Math.max(8, window.innerWidth - BUTLER_W - 12), y: Math.max(40, window.innerHeight - BUTLER_H - 8) };
}

export function DemoDesktop() {
  const [dashMounted, setDashMounted] = useState(false);
  const [dashOpen, setDashOpen] = useState(false);
  const [pos, setPos] = useState<Pos>(defaultPos);
  const [menu, setMenu] = useState<P.DemoMenuDetail | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [source, setSource] = useState("");
  const [now, setNow] = useState(new Date());
  const placed = useRef(false);
  const [notes, setNotes] = useState<{ id: string; x: number; y: number }[]>([]);
  const posRef = useRef(pos);
  posRef.current = pos;
  const notesRef = useRef(notes);
  notesRef.current = notes;

  // let the butler move himself and leave notes on this desk
  useEffect(() => {
    P.registerDesk({
      getPos: () => posRef.current,
      setPos: (p) => {
        placed.current = true;
        setPos(p);
      },
      bounds: () => ({ x: -20, y: 30 - 90, w: Math.max(0, window.innerWidth - BUTLER_W + 40), h: Math.max(0, window.innerHeight - BUTLER_H + 80) }),
      spawnNote: (id, at) =>
        setNotes((n) => (n.some((x) => x.id === id) ? n : [...n, {
          id,
          x: Math.min(Math.max(8, at.x), window.innerWidth - 290),
          y: Math.min(Math.max(36, at.y), window.innerHeight - 200),
        }])),
      noteCount: () => notesRef.current.length,
    });
    return () => P.registerDesk(null);
  }, []);

  useEffect(() => {
    void demoApi.sourceNote().then(setSource).catch(() => {});
    const t = setInterval(() => setNow(new Date()), 30_000);
    const onResize = () => {
      if (!placed.current) setPos(defaultPos());
      else setPos((p) => clamp(p));
    };
    window.addEventListener("resize", onResize);
    return () => {
      clearInterval(t);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const openDash = useCallback(() => {
    P.demoState.dashboardOpen = true;
    setDashMounted(true);
    setDashOpen(true);
  }, []);
  const closeDash = useCallback(() => {
    P.demoState.dashboardOpen = false;
    setDashOpen(false);
  }, []);

  useEffect(() => {
    const bus = P.demoBus;
    const onOpen = () => openDash();
    const onMenu = (e: Event) => setMenu((e as CustomEvent<P.DemoMenuDetail>).detail);
    const onNote = (e: Event) => {
      setNote((e as CustomEvent<string>).detail);
      window.setTimeout(() => setNote(null), 4000);
    };
    const onDrag = (e: Event) => {
      const start = (e as CustomEvent<Pos>).detail;
      placed.current = true;
      let origin: Pos | null = null;
      setPos((p) => (origin = p));
      const move = (ev: PointerEvent) => {
        if (!origin) return;
        setPos(clamp({ x: origin.x + ev.clientX - start.x, y: origin.y + ev.clientY - start.y }));
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
    bus.addEventListener("open-dashboard", onOpen);
    bus.addEventListener("menu", onMenu);
    bus.addEventListener("note", onNote);
    bus.addEventListener("start-drag", onDrag);
    return () => {
      bus.removeEventListener("open-dashboard", onOpen);
      bus.removeEventListener("menu", onMenu);
      bus.removeEventListener("note", onNote);
      bus.removeEventListener("start-drag", onDrag);
    };
  }, [openDash]);

  useEffect(() => {
    if (!menu && !dashOpen) return;
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (menu) setMenu(null);
      else closeDash();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [menu, dashOpen, closeDash]);

  return (
    <div className="desk">
      <header className="menubar">
        <span className="menubar-app">Desktop Butler</span>
        <span className="menubar-right">
          <button type="button" className="menubar-icon" aria-label="Open briefing" onClick={openDash}>
            <Face name="smile" size={20} />
          </button>
          <time>{now.toLocaleTimeString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}</time>
        </span>
      </header>

      <section className="intro" aria-label="About this demo">
        <h1>Desktop Butler, running on real arXiv papers</h1>
        <p>
          This is the real app running in your browser. Its briefing comes from the real backend: the
          papers arXiv announced in quantitative finance on Monday, October 19, ranked by the same code
          that will run on your Mac at 8 AM and 8 PM.
        </p>
        <ul>
          <li>Click the butler to open the briefing.</li>
          <li>Drag him anywhere. Hover for his status.</li>
          <li>Leave him alone and he roams: reads, dusts, naps, and walks over to leave notes about papers you haven't read.</li>
          <li>Right-click him for quiet mode, fetch now and the rest.</li>
        </ul>
        <p className="intro-small">
          Titles, authors and links are exact. Summaries are short paraphrases of the abstracts, labelled as such.
          “Fetch papers now” is simulated here because this page can't reach arXiv. {source && <>Source: {source}.</>}
        </p>
      </section>

      {dashMounted && (
        <div className={`win ${dashOpen ? "is-open" : ""}`} hidden={!dashOpen} role="dialog" aria-label="Desktop Butler briefing">
          <div className="win-bar">
            <button type="button" className="win-close" aria-label="Close briefing window" onClick={closeDash}>
              <span aria-hidden>×</span>
            </button>
            <span className="win-title">Desktop Butler</span>
          </div>
          <div className="win-body">
            <Dashboard />
          </div>
        </div>
      )}

      {notes.map((n) => (
        <div key={n.id} className="desk-note" style={{ left: n.x, top: n.y }}>
          <NoteCard id={n.id} onClose={() => setNotes((all) => all.filter((x) => x.id !== n.id))} />
        </div>
      ))}

      <div className={`butler-dock ${dashOpen ? "with-window" : ""}`} style={{ left: pos.x, top: pos.y }}>
        <ButlerWindow />
      </div>

      {menu && <DemoMenu menu={menu} onClose={() => setMenu(null)} />}
      {note && <div className="toast" role="status">{note}</div>}
    </div>
  );
}

function clamp(p: Pos): Pos {
  return {
    x: Math.min(Math.max(-60, p.x), window.innerWidth - BUTLER_W + 60),
    y: Math.min(Math.max(20, p.y), window.innerHeight - BUTLER_H + 20),
  };
}

function DemoMenu({ menu, onClose }: { menu: P.DemoMenuDetail; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector("button")?.focus();
    const away = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && onClose();
    window.addEventListener("pointerdown", away, true);
    return () => window.removeEventListener("pointerdown", away, true);
  }, [onClose]);

  const s = menu.settings;
  const run = (fn: () => void) => () => {
    fn();
    onClose();
  };
  const x = Math.min(menu.x, window.innerWidth - 230), y = Math.min(menu.y, window.innerHeight - 330);
  return (
    <div className="ctx" ref={ref} role="menu" style={{ left: Math.max(8, x), top: Math.max(30, y) }}>
      <button role="menuitem" type="button" onClick={run(menu.openBriefing)}>Open briefing</button>
      <button role="menuitem" type="button" onClick={run(menu.fetchNow)}>Fetch papers now</button>
      <hr />
      <Check label="Quiet mode" on={s.quiet} act={run(() => menu.onSettings({ ...s, quiet: !s.quiet }))} />
      <Check label="Keep on top" on={s.onTop} act={run(() => menu.onSettings({ ...s, onTop: !s.onTop }))} />
      <Check label="Let him roam" on={s.wander} act={run(() => menu.onSettings({ ...s, wander: !s.wander }))} />
      <Check label="Start at login" on={false} disabled act={() => {}} hint="On your Mac" />
      <hr />
      <button role="menuitem" type="button" onClick={run(() => void P.hideButler())}>Hide butler</button>
      <button role="menuitem" type="button" onClick={run(() => void P.quitApp())}>Quit Desktop Butler</button>
    </div>
  );
}

function Check(p: { label: string; on: boolean; act: () => void; disabled?: boolean; hint?: string }) {
  return (
    <button role="menuitemcheckbox" aria-checked={p.on} type="button" onClick={p.act} disabled={p.disabled}>
      <span className="ctx-check" aria-hidden>{p.on ? "✓" : ""}</span>
      {p.label}
      {p.hint && <small>{p.hint}</small>}
    </button>
  );
}
