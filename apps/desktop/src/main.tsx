import React from "react";
import ReactDOM from "react-dom/client";
import "./theme.css";
import { windowLabel } from "./platform";
import { ButlerWindow } from "./butler/ButlerWindow";
import { Dashboard } from "./dashboard/Dashboard";
import { DemoDesktop } from "./demo/DemoDesktop";
import { NoteWindow } from "./butler/NoteCard";

const view = windowLabel();
document.documentElement.classList.add(`view-${view}`);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{view === "note" ? <NoteWindow /> : view === "demo" ? <DemoDesktop /> : view === "butler" ? <ButlerWindow /> : <Dashboard />}</React.StrictMode>,
);
