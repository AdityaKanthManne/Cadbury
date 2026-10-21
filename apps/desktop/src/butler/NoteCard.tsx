import { useEffect, useState } from "react";
import { api, type Paper } from "../api";
import * as P from "../platform";
import { Face } from "./Sprite";
import "./note.css";

/** A card the butler leaves on your desk about one paper. */
export function NoteCard({ id, onClose }: { id: string; onClose: () => void }) {
  const [paper, setPaper] = useState<Paper | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.paper(id).then(setPaper).catch(() => setFailed(true));
  }, [id]);

  const read = async () => {
    void api.feedback(id, "opened").catch(() => {});
    // open the briefing before this note closes, or the request dies with the window
    await P.openDashboard("briefing").catch(() => {});
    onClose();
  };

  if (failed) return null;
  const score = Math.round(paper?.score ?? 0);
  return (
    <div className="note" role="dialog" aria-label="A note from your butler">
      <div className="note-head" data-tauri-drag-region>
        <Face name="smile" size={26} />
        <span data-tauri-drag-region>A note from your butler</span>
        <button type="button" className="note-x" aria-label="Dismiss note" onClick={onClose}>×</button>
      </div>
      {paper ? (
        <>
          <p className="note-title">
            <span className="note-score">{score}</span> {paper.title}
          </p>
          {paper.why && <p className="note-why">{paper.why}</p>}
          <div className="note-actions">
            <button type="button" className="note-read" onClick={() => void read()}>Read it</button>
            <button type="button" className="note-later" onClick={() => { void api.bookmark(id, true); onClose(); }}>
              Save for later
            </button>
          </div>
        </>
      ) : (
        <p className="note-why">Fetching the paper…</p>
      )}
    </div>
  );
}

/** Standalone note window in the desktop app (label note-<id>). */
export function NoteWindow() {
  const id = new URLSearchParams(window.location.search).get("id") ?? "";
  return (
    <div className="note-stage">
      <NoteCard id={id} onClose={() => void P.closeThisWindow()} />
    </div>
  );
}
