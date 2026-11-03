import { useEffect, useRef, useState } from "react";
import { getSync, startSync } from "./api.js";

const LABELS = {
  updated: "Updated",
  would_update: "Would update",
  unchanged: "Already up to date",
  no_match: "Not found in BC",
  error: "Errors",
};
const FIELD_NAMES = {
  ciscoSOLineNo: "CISCO SO Line No.",
  shipset: "Shipset",
  ciscoDeliveryStatus: "CISCO Delivery Status",
  scheduledDate: "Scheduled_Date",
  previousScheduledDate: "Previous Scheduled Date",
  estimateDeliveryDate: "Estimate Delivery Date",
};

export default function SyncDialog({ job, onClose }) {
  const [phase, setPhase] = useState("confirm"); // confirm | running | done
  const [st, setSt] = useState(null);
  const [error, setError] = useState("");
  const timer = useRef(null);

  const rows = job.rows;
  const poCount = new Set(rows.map((r) => r["PO ID"])).size;

  useEffect(() => () => clearInterval(timer.current), []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && phase !== "running" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, phase]);

  async function run(dry) {
    setError("");
    setSt(null);
    setPhase("running");
    try {
      const { sync_id } = await startSync(job.id, dry);
      timer.current = setInterval(async () => {
        try {
          const p = await getSync(sync_id, false);
          if (p.status === "running") return setSt(p);
          clearInterval(timer.current);
          setSt(await getSync(sync_id, true));
          setPhase("done");
        } catch (e) {
          clearInterval(timer.current);
          setError(e.message);
          setPhase("done");
        }
      }, 1000);
    } catch (e) {
      setError(e.message);
      setPhase("done");
    }
  }

  const pct = st?.total ? Math.round((st.done / st.total) * 100) : 0;
  const failed = st?.status === "failed";

  return (
    <div className="overlay center" onMouseDown={(e) => e.target === e.currentTarget && phase !== "running" && onClose()}>
      <div className="modal" role="dialog" aria-label="Sync into Business Central">
        <div className="drawer-head">
          <h2>Sync into Business Central</h2>
          {phase !== "running" && <button className="icon" onClick={onClose} aria-label="Close">✕</button>}
        </div>

        <div className="modal-body">
          {phase === "confirm" && (
            <>
              <p>
                Sync <b>{rows.length}</b> line(s) from <b>{poCount}</b> PO(s) into the Business Central purchase lines.
              </p>
              <ul className="steps">
                <li>Lines are found by <b>PO No. + “-M” and “-S”</b> and <b>Buyers Line No. = PO Line Number</b>.</li>
                <li>Updated: CISCO SO Line No. ← SO Line Ref · Shipset ← Line ID Set · CISCO Delivery Status ← Status Code ·
                  Scheduled_Date ← Final Scheduled Ship Date (the old date is added to Previous Scheduled Date).</li>
                <li>Estimate Delivery Date ← the latest Final Scheduled Ship Date of the PO + the days set in Settings (14); if that lands on a Saturday or Sunday it moves to the following Monday.</li>
                <li>After the purchase lines of a PO are updated, its <b>T1 Process Data</b> lines are rebuilt in Business Central (same logic as Report 80000).</li>
                <li>Blank Cisco values never overwrite what is already in Business Central.</li>
                <li>Only the fetched rows are synced (rows hidden by the Status Code filter are not); the table search box has no effect.</li>
              </ul>
              <div className="warn">This writes to the live Business Central database. Use <b>Preview</b> first to see what would change.</div>
            </>
          )}

          {phase === "running" && (
            <>
              <div className="progress-head">
                <strong>{st?.dry_run ? "Previewing…" : "Syncing…"}</strong>
                <span>{st?.done ?? 0}/{st?.total ?? poCount} POs</span>
              </div>
              <div className="bar"><div style={{ width: `${pct}%` }} /></div>
              <div className="activity"><span className="spin" aria-hidden /> {st?.activity || "Starting…"}</div>
              {st && (
                <ul className="stepper">
                  <li className={st.lines_done >= st.total ? "done" : "active"}>
                    <b>1 · Updating purchase lines</b>
                    <span>{st.lines_done}/{st.total} POs{st.dry_run ? " (preview)" : ""}</span>
                  </li>
                  <li className={st.t1.skipped ? "skip" : st.done >= st.total ? "done" : st.lines_done > 0 ? "active" : ""}>
                    <b>2 · Updating T1 Process Data</b>
                    <span>
                      {st.dry_run
                        ? `${st.t1.would} order(s) would be refreshed`
                        : st.t1.skipped
                          ? "skipped — see the note after the sync"
                          : `${st.t1.docs} order(s) refreshed${st.t1.rows != null ? ` · ${st.t1.rows} lines` : ""}`}
                    </span>
                  </li>
                </ul>
              )}
            </>
          )}

          {phase === "done" && (
            <>
              {(error || failed) && <div className="error">{error || st.error}</div>}
              {st && !failed && (
                <>
                  <div className="info">
                    {st.dry_run ? "Preview only — nothing was written to Business Central." : "Sync finished."}
                  </div>
                  <div className="counts">
                    {Object.entries(LABELS).map(([k, label]) => (
                      <div key={k} className={`count-box c-${k} ${st.counts[k] ? "has" : ""}`}>
                        <b>{st.counts[k]}</b>
                        <span>{label}</span>
                      </div>
                    ))}
                  </div>
                  {!st.dry_run && st.t1.skipped && (
                    <div className="warn">
                      The purchase lines were synced, but <b>T1 Process Data was not updated</b>: {st.t1.skipped}
                    </div>
                  )}
                  {!st.dry_run && !st.t1.skipped && (
                    <div className={st.t1.errors ? "warn" : "info"}>
                      T1 Process Data: {st.t1.docs} purchase order document(s) refreshed
                      {st.t1.rows != null ? `, ${st.t1.rows} lines created` : ""}
                      {st.t1.errors > 0 && ` — ${st.t1.errors} PO(s) could not be refreshed (see the warnings below)`}.
                    </div>
                  )}
                  {st.dry_run && st.t1.would > 0 && (
                    <div className="info">After a real sync, T1 Process Data would be rebuilt for {st.t1.would} purchase order document(s).</div>
                  )}
                  {st.po_errors.length > 0 && (
                    <div className="error">
                      {st.po_errors.length} PO(s) failed:{" "}
                      {st.po_errors.slice(0, 5).map((e) => `${e.po} (${e.error})`).join("; ")}
                    </div>
                  )}
                  {st.details.length > 0 && (
                    <div className="table-wrap small">
                      <table>
                        <thead>
                          <tr><th>PO</th><th>Line</th><th>BC document</th><th>Result</th><th>Details</th></tr>
                        </thead>
                        <tbody>
                          {st.details.map((d, i) => (
                            <tr key={i}>
                              <td>{d.po}</td>
                              <td>{d.line}</td>
                              <td>{d.doc || "—"}</td>
                              <td><span className={`pill sync-${d.status}`}>{LABELS[d.status]}</span></td>
                              <td className="wrap">
                                {Object.entries(d.changes).map(([k, v]) => `${FIELD_NAMES[k] || k}: ${v}`).join(" · ")}
                                {d.error && <span className="err"> {d.error}</span>}
                                {d.warnings.map((w, j) => <span key={j} className="warn-text"> ⚠ {w}</span>)}
                                {d.status === "no_match" && "No -M/-S purchase line with this Buyers Line No."}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {st.details.length >= 1000 && <small>Showing the first 1000 results.</small>}
                </>
              )}
            </>
          )}
        </div>

        <div className="drawer-foot">
          <div className="row">
            <span className="spacer" />
            {phase === "confirm" && (
              <>
                <button onClick={onClose}>Cancel</button>
                <button onClick={() => run(true)}>Preview (no changes)</button>
                <button className="primary" onClick={() => run(false)}>Sync now</button>
              </>
            )}
            {phase === "done" && (
              <>
                <button onClick={onClose}>Close</button>
                {st?.dry_run && !failed && <button className="primary" onClick={() => run(false)}>Sync now</button>}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
