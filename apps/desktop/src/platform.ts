// Thin wrappers over Tauri APIs. Everything degrades to a no-op (or a browser
// equivalent) outside Tauri, so the UI can be previewed and tested in a browser.

import { invoke } from "@tauri-apps/api/core";
import { emit, listen, type UnlistenFn } from "@tauri-apps/api/event";
import { CheckMenuItem, Menu, MenuItem, PredefinedMenuItem } from "@tauri-apps/api/menu";
import { getCurrentWindow, currentMonitor } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { LogicalPosition } from "@tauri-apps/api/dpi";
import type { Bounds, Pos } from "./butler/behavior";

export const inTauri = "__TAURI_INTERNALS__" in window;
export const inDemo = import.meta.env.VITE_DEMO === "1";

/** In the browser demo, the "desktop" page listens on this bus for window actions. */
export const demoBus = new EventTarget();
export const demoState = { dashboardOpen: false };
export type DemoMenuDetail = MenuHandlers & { x: number; y: number };
let lastPointer = { x: 0, y: 0 };
if (inDemo) window.addEventListener("pointerdown", (e) => (lastPointer = { x: e.clientX, y: e.clientY }), true);
if (inDemo) window.addEventListener("contextmenu", (e) => (lastPointer = { x: e.clientX, y: e.clientY }), true);
const demoSend = (type: string, detail?: unknown) => demoBus.dispatchEvent(new CustomEvent(type, { detail }));

export function windowLabel(): string {
  const v = new URLSearchParams(window.location.search).get("view");
  if (v === "note") return "note";
  if (inDemo) return "demo";
  if (v) return v;
  return inTauri ? getCurrentWindow().label : "dashboard";
}

// ---- settings shared by both windows -------------------------------------
export interface Settings {
  quiet: boolean;      // no alert pose / attention while on
  onTop: boolean;      // keep butler above other windows
  wander: boolean;     // let him roam the screen, read, dust and leave notes
}
const DEFAULTS: Settings = { quiet: false, onTop: true, wander: true };
const KEY = "butler.settings";

export function loadSettings(): Settings {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

export async function saveSettings(s: Settings): Promise<void> {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable: keep in memory only */
  }
  if (inTauri) await emit("settings-changed", s);
  else window.dispatchEvent(new CustomEvent("settings-changed", { detail: s }));
}

export async function onSettingsChanged(cb: (s: Settings) => void): Promise<UnlistenFn> {
  if (inTauri) return listen<Settings>("settings-changed", (e) => cb(e.payload));
  const h = (e: Event) => cb((e as CustomEvent<Settings>).detail);
  window.addEventListener("settings-changed", h);
  return () => window.removeEventListener("settings-changed", h);
}

// ---- "seen" briefing marker (drives the tray-with-papers pose) -------------
const SEEN = "butler.seenBriefing";
export function seenBriefingId(): number {
  try {
    return Number(localStorage.getItem(SEEN) ?? 0);
  } catch {
    return 0;
  }
}
export async function markBriefingSeen(id: number): Promise<void> {
  try {
    localStorage.setItem(SEEN, String(id));
  } catch {
    /* ignore */
  }
  if (inTauri) await emit("briefing-seen", id);
  else window.dispatchEvent(new CustomEvent("briefing-seen", { detail: id }));
}
export async function onBriefingSeen(cb: (id: number) => void): Promise<UnlistenFn> {
  if (inTauri) return listen<number>("briefing-seen", (e) => cb(e.payload));
  const h = (e: Event) => cb((e as CustomEvent<number>).detail);
  window.addEventListener("briefing-seen", h);
  return () => window.removeEventListener("briefing-seen", h);
}

// ---- windows ---------------------------------------------------------------
export async function openDashboard(section?: string): Promise<void> {
  if (inDemo) {
    demoSend("open-dashboard", section);
    return;
  }
  if (!inTauri) {
    window.open(`?view=dashboard${section ? `#${section}` : ""}`, "_blank");
    return;
  }
  const dash = await WebviewWindow.getByLabel("dashboard");
  if (!dash) return;
  await dash.unminimize();
  await dash.show();
  await dash.setFocus();
  if (section) await emit("dashboard-section", section);
}

/** Is this window actually on screen? (Hidden Tauri windows still run their page.) */
export async function windowVisible(): Promise<boolean> {
  if (inDemo) return demoState.dashboardOpen;
  if (inTauri) return getCurrentWindow().isVisible();
  return document.visibilityState === "visible";
}

/** Fires when this window gains focus (Tauri) or becomes visible (browser). */
export async function onWindowShown(cb: () => void): Promise<UnlistenFn> {
  if (inDemo) {
    const h = () => cb();
    demoBus.addEventListener("open-dashboard", h);
    return () => demoBus.removeEventListener("open-dashboard", h);
  }
  if (inTauri) return getCurrentWindow().onFocusChanged(({ payload }) => payload && cb());
  const h = () => document.visibilityState === "visible" && cb();
  document.addEventListener("visibilitychange", h);
  return () => document.removeEventListener("visibilitychange", h);
}

export async function onDashboardSection(cb: (s: string) => void): Promise<UnlistenFn> {
  if (inDemo) {
    const h = (e: Event) => (e as CustomEvent<string | undefined>).detail && cb((e as CustomEvent<string>).detail);
    demoBus.addEventListener("open-dashboard", h);
    return () => demoBus.removeEventListener("open-dashboard", h);
  }
  if (!inTauri) return () => {};
  return listen<string>("dashboard-section", (e) => cb(e.payload));
}

export async function startDrag(): Promise<void> {
  if (inDemo) return void demoSend("start-drag", lastPointer);
  if (inTauri) await getCurrentWindow().startDragging();
}

export async function setOnTop(on: boolean): Promise<void> {
  if (inTauri) await getCurrentWindow().setAlwaysOnTop(on);
}

export async function hideButler(): Promise<void> {
  if (inDemo) return void demoSend("note", "On your Mac this hides the butler; bring him back from the menu-bar icon.");
  if (inTauri) await getCurrentWindow().hide();
}

export async function quitApp(): Promise<void> {
  if (inDemo) return void demoSend("note", "On your Mac this quits Desktop Butler and stops its backend.");
  if (inTauri) await invoke("quit_app");
}

export async function openExternal(url: string): Promise<void> {
  if (!/^https:\/\//.test(url)) return; // only open https links from retrieved content
  if (inTauri) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
  } else {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

/** First launch: park the butler in the bottom-right corner of the current screen. */
export async function placeButlerFirstTime(): Promise<void> {
  if (!inTauri) return;
  try {
    if (localStorage.getItem("butler.placed")) return;
    const mon = await currentMonitor();
    if (!mon) return;
    const sf = mon.scaleFactor;
    const w = mon.size.width / sf, h = mon.size.height / sf;
    const x = mon.position.x / sf + w - 260, y = mon.position.y / sf + h - 340;
    await getCurrentWindow().setPosition(new LogicalPosition(x, y));
    localStorage.setItem("butler.placed", "1");
  } catch {
    /* non-fatal */
  }
}

// ---- roaming: position, screen bounds, notes ---------------------------------
const BUTLER_W = 240, BUTLER_H = 290;
/** The top ~90px of the butler window is the (usually invisible) speech bubble. */
const BUBBLE_H = 90;

export interface DeskHandlers {
  getPos(): Pos;
  setPos(p: Pos): void;
  bounds(): Bounds;
  spawnNote(id: string, at: Pos): void;
  noteCount(): number;
}
let desk: DeskHandlers | null = null;
/** The browser demo's desktop registers itself here. */
export function registerDesk(d: DeskHandlers | null): void {
  desk = d;
}

export async function butlerPos(): Promise<Pos> {
  if (inDemo) return desk?.getPos() ?? { x: 0, y: 0 };
  if (!inTauri) return { x: 0, y: 0 };
  const w = getCurrentWindow();
  const p = (await w.outerPosition()).toLogical(await w.scaleFactor());
  return { x: Math.round(p.x), y: Math.round(p.y) };
}

export async function moveButler(p: Pos): Promise<void> {
  if (inDemo) return desk?.setPos(p);
  if (inTauri) await getCurrentWindow().setPosition(new LogicalPosition(p.x, p.y));
}

/** Where the butler window may roam: the screen minus menu bar and Dock. */
export async function roamBounds(): Promise<Bounds | null> {
  if (inDemo) return desk?.bounds() ?? null;
  if (!inTauri) return null;
  const mon = await currentMonitor();
  if (!mon) return null;
  const sf = mon.scaleFactor;
  const area = mon.workArea ?? { position: mon.position, size: mon.size };
  const x = area.position.x / sf, y = area.position.y / sf;
  const w = area.size.width / sf, h = area.size.height / sf;
  return { x: x - 20, y: y - BUBBLE_H, w: Math.max(0, w - BUTLER_W + 40), h: Math.max(0, h - BUTLER_H + BUBBLE_H) };
}

const noteLabel = (id: string) => `note-${id.replace(/[^A-Za-z0-9_-]/g, "_")}`;

export async function spawnNote(id: string, at: Pos): Promise<void> {
  if (inDemo) return desk?.spawnNote(id, at);
  if (!inTauri) return;
  const label = noteLabel(id);
  if (await WebviewWindow.getByLabel(label)) return;
  new WebviewWindow(label, {
    url: `index.html?view=note&id=${encodeURIComponent(id)}`,
    x: at.x, y: at.y, width: 290, height: 250,
    // notes sit at normal window level: the butler stays above them, your apps can cover them
    transparent: true, decorations: false, alwaysOnTop: false, skipTaskbar: true,
    resizable: false, shadow: false, focus: false, visibleOnAllWorkspaces: true,
  });
}

export async function noteCount(): Promise<number> {
  if (inDemo) return desk?.noteCount() ?? 0;
  if (!inTauri) return 0;
  return (await WebviewWindow.getAll()).filter((w) => w.label.startsWith("note-")).length;
}

export async function closeThisWindow(): Promise<void> {
  if (inTauri) await getCurrentWindow().close();
}

/** Speeds up roaming for testing: BUTLER_BEHAVIOR_FAST=1 (app) or ?fast (browser). */
export async function behaviorSpeed(): Promise<number> {
  if (inTauri) return invoke<number>("behavior_speed").catch(() => 1);
  return new URLSearchParams(window.location.search).has("fast") ? 6 : 1;
}

const NOTED = "butler.noted";
export function notedIds(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(NOTED) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}
export function markNoted(id: string): void {
  const s = notedIds();
  s.add(id);
  try {
    localStorage.setItem(NOTED, JSON.stringify([...s].slice(-200)));
  } catch {
    /* ignore */
  }
}

// ---- autostart (explicit opt-in) ------------------------------------------
export async function autostartEnabled(): Promise<boolean> {
  if (!inTauri) return false;
  const { isEnabled } = await import("@tauri-apps/plugin-autostart");
  return isEnabled();
}
export async function setAutostart(on: boolean): Promise<void> {
  if (!inTauri) return;
  const m = await import("@tauri-apps/plugin-autostart");
  if (on) await m.enable();
  else await m.disable();
}

// ---- native context menu ---------------------------------------------------
export interface MenuHandlers {
  openBriefing: () => void;
  fetchNow: () => void;
  settings: Settings;
  onSettings: (s: Settings) => void;
  autostart: boolean;
  onAutostart: (on: boolean) => void;
}

export async function showButlerMenu(h: MenuHandlers): Promise<boolean> {
  if (inDemo) {
    demoSend("menu", { ...h, ...lastPointer });
    return true;
  }
  if (!inTauri) return false;
  const s = h.settings;
  const menu = await Menu.new({
    items: [
      await MenuItem.new({ text: "Open briefing", action: h.openBriefing }),
      await MenuItem.new({ text: "Fetch papers now", action: h.fetchNow }),
      await PredefinedMenuItem.new({ item: "Separator" }),
      await CheckMenuItem.new({ text: "Quiet mode", checked: s.quiet, action: () => h.onSettings({ ...s, quiet: !s.quiet }) }),
      await CheckMenuItem.new({ text: "Keep on top", checked: s.onTop, action: () => h.onSettings({ ...s, onTop: !s.onTop }) }),
      await CheckMenuItem.new({ text: "Let him roam", checked: s.wander, action: () => h.onSettings({ ...s, wander: !s.wander }) }),
      await CheckMenuItem.new({ text: "Start at login", checked: h.autostart, action: () => h.onAutostart(!h.autostart) }),
      await PredefinedMenuItem.new({ item: "Separator" }),
      await MenuItem.new({ text: "Hide butler", action: () => void hideButler() }),
      await MenuItem.new({ text: "Quit Desktop Butler", action: () => void quitApp() }),
    ],
  });
  await menu.popup();
  return true;
}
