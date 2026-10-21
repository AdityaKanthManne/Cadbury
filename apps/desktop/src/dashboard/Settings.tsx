import { useEffect, useState } from "react";
import { api, type Briefing, type Profile, type Status } from "../api";
import * as P from "../platform";
import { clock } from "./format";

interface Props {
  status: Status | null;
  profile: Profile | null;
  onReset: () => void;
}

export function Settings({ status, profile, onReset }: Props) {
  const [s, setS] = useState(P.loadSettings());
  const [autostart, setAutostartState] = useState(false);
  const [history, setHistory] = useState<Briefing[]>([]);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    void P.autostartEnabled().then(setAutostartState).catch(() => {});
    void api.briefings(8).then(setHistory).catch(() => {});
    const u = P.onSettingsChanged(setS);
    return () => void u.then((f) => f());
  }, [status?.last_attempt?.id]);

  const update = (next: Partial<P.Settings>) => {
    const v = { ...s, ...next };
    setS(v);
    void P.saveSettings(v);
  };

  return (
    <div className="settings">
      <section>
        <h2>Butler</h2>
        <Toggle label="Quiet mode" help="He won't point at urgent papers; new briefings still wait on his tray."
          checked={s.quiet} onChange={(v) => update({ quiet: v })} />
        <Toggle label="Keep on top of other windows" checked={s.onTop} onChange={(v) => update({ onTop: v })} />
        <Toggle label="Let him roam" help="He walks around your screen, reads, dusts, naps, and leaves notes about papers you haven't read. Pauses in quiet mode or with reduced motion."
          checked={s.wander} onChange={(v) => update({ wander: v })} />
        <Toggle label="Start Desktop Butler when I log in" checked={autostart} disabled={!P.inTauri}
          onChange={(v) => void P.setAutostart(v).then(() => setAutostartState(v))} />
      </section>

      <section>
        <h2>Schedule</h2>
        <p>
          Briefings run at {status?.schedule.join(" and ") ?? "08:00 and 20:00"} ({status?.timezone ?? "America/New_York"}).
          If your Mac is asleep at those times, the butler catches up within 15 minutes of waking.
        </p>
        <dl className="facts">
          <dt>Next briefings</dt><dd>{status?.next_runs.map(clock).join(", ") ?? "unknown"}</dd>
          <dt>Last successful</dt><dd>{status?.last_success ? clock(status.last_success.started_at) : "never"}</dd>
          <dt>Papers stored</dt><dd>{status?.paper_count ?? 0}</dd>
          <dt>Data folder</dt><dd><code>{status?.data_dir ?? "unknown"}</code></dd>
        </dl>
      </section>

      <section>
        <h2>Recent fetches</h2>
        {history.length === 0 ? <p>No fetches yet.</p> : (
          <table className="history">
            <thead><tr><th>When</th><th>Trigger</th><th>Result</th><th>Found</th><th>Problems</th></tr></thead>
            <tbody>
              {history.map((b) => (
                <tr key={b.id} className={`st-${b.status}`}>
                  <td>{clock(b.started_at)}</td>
                  <td>{b.trigger}</td>
                  <td>{b.status}</td>
                  <td>{b.new_papers} new of {b.fetched}</td>
                  <td>{b.errors?.length ? b.errors.map((e) => `${e.source}: ${e.error}`).join("; ") : "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Your interests</h2>
        <p>Edit <code>configs/user_profile.yaml</code> in the Cadbury folder to change weights or keywords, then restart the app.</p>
        <ul className="areas">
          {profile?.areas.map((a) => (
            <li key={a.key}>
              <span className="area-name">{a.label}</span>
              <span className="area-w">{a.weight}</span>
              <span className="area-kw">{a.keywords.slice(0, 8).join(", ")}{a.keywords.length > 8 ? ", …" : ""}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Your data</h2>
        <p>Saved papers and your relevant / not-for-me votes stay on this Mac. Nothing is sent anywhere.</p>
        {confirmReset ? (
          <p>
            Delete all saved papers and votes?{" "}
            <button type="button" className="btn-danger" onClick={async () => { await api.resetPersonal(); setConfirmReset(false); onReset(); }}>
              Delete saved papers and votes
            </button>{" "}
            <button type="button" className="link" onClick={() => setConfirmReset(false)}>Keep them</button>
          </p>
        ) : (
          <button type="button" className="link" onClick={() => setConfirmReset(true)}>Reset saved papers and votes…</button>
        )}
      </section>
    </div>
  );
}

function Toggle(props: { label: string; help?: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className={`toggle ${props.disabled ? "is-disabled" : ""}`}>
      <input type="checkbox" checked={props.checked} disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.checked)} />
      <span className="toggle-text">
        <span>{props.label}</span>
        {props.help && <small>{props.help}</small>}
      </span>
    </label>
  );
}
