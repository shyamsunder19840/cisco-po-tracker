import { useEffect, useState } from "react";
import { getHistory } from "./api.js";

const STATE = {
  done: { text: "Done", cls: "d-done" },
  checked: { text: "Checked, not synced", cls: "d-checked" },
  pending: { text: "Pending today", cls: "d-pending" },
  none: { text: "No activity", cls: "d-none" },
};
const TABS = { po: "PO Numbers", t1: "Customer PO Numbers", date: "PO Order Date" };
const fmtDay = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
const fmtTime = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

function syncText(s) {
  if (s.status !== "done") return `Sync failed${s.error ? `: ${s.error}` : ""}`;
  const c = s.counts || {};
  return `Synced: ${c.updated || 0} updated, ${c.unchanged || 0} unchanged, ${c.no_match || 0} not found, ${c.error || 0} errors`;
}

export default function DailyTracker({ onStart }) {
  const [days, setDays] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  useEffect(() => {
    getHistory().then(setDays).catch((e) => setError(e.message));
  }, []);

  const today = days?.[0];
  return (
    <section className="card">
      <div className="today">
        <div>
          <h2>Daily tracker</h2>
          {today && (
            <p className="muted">
              Today, {fmtDay(today.date)} — <span className={`dpill ${STATE[today.state].cls}`}>{STATE[today.state].text}</span>
              {today.checks > 0 && ` · ${today.checks} check${today.checks > 1 ? "s" : ""}, ${today.syncs} sync${today.syncs === 1 ? "" : "s"}`}
            </p>
          )}
        </div>
        <button className="primary" onClick={onStart}>
          {today && today.checks > 0 ? "Start another run" : "Start today's task"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {!days && !error && <p className="muted">Loading…</p>}
      {days && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Day</th><th>Status</th><th>Checks</th><th>Syncs</th><th /></tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <FragmentRows key={d.date} d={d} open={open === d.date} toggle={() => setOpen(open === d.date ? null : d.date)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function FragmentRows({ d, open, toggle }) {
  const st = STATE[d.state];
  return (
    <>
      <tr>
        <td>{fmtDay(d.date)}</td>
        <td><span className={`dpill ${st.cls}`}>{st.text}</span></td>
        <td>{d.checks}</td>
        <td>{d.syncs}</td>
        <td>{d.runs.length > 0 && <button className="icon" onClick={toggle}>{open ? "Hide" : "Details"}</button>}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} className="wrap">
            <ul className="runs">
              {d.runs.map((r) => (
                <li key={r.job_id + r.ts}>
                  <b>{fmtTime(r.ts)}</b> · {TABS[r.tab] || "Check"}{r.label ? ` (${r.label})` : ""} — {r.pos} PO(s), {r.lines} line(s)
                  {r.errors > 0 && <span className="err"> · {r.errors} failed</span>}
                  {r.syncs.length === 0 && <div className="muted">Not synced to Business Central</div>}
                  {r.syncs.map((s, i) => (
                    <div key={i} className={s.status === "done" ? "" : "err"}>{fmtTime(s.ts)} · {syncText(s)}</div>
                  ))}
                </li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}
