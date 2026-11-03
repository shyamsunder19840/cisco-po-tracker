import { useEffect, useRef, useState } from "react";
import { cancelSync, getSync, startSync } from "./api.js";

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
  const [phase, setPhase] = useState("running"); // running | done  (the sync starts as soon as the window opens)
  const [st, setSt] = useState(null);
  const [error, setError] = useState("");
  const timer = useRef(null);
  const syncId = useRef(null);
  const started = useRef(false);

  const rows = job.rows;
  const poCount = new Set(rows.map((r) => r["PO ID"])).size;

  useEffect(() => () => clearInterval(timer.current), []);
  useEffect(() => {
    if (!started.current) {
      started.current = true;
      run(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
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
      syncId.current = sync_id;
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
                    {st.dry_run ? "Preview only — nothing was written to Business Central."
                      : st.status === "cancelled" ? "Sync cancelled — lines already processed stay saved in Business Central; the rest were not touched."
                      : "Sync finished."}
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
                    <details className="details-box">
                      <summary>
                        Show details ({st.details.length} line{st.details.length === 1 ? "" : "s"}
                        {st.details.some((d) => d.warnings.length || d.error) ? ", with warnings" : ""})
                      </summary>
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
                    </details>
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
            {phase === "running" && (
              <button
                onClick={() => syncId.current && cancelSync(syncId.current).catch((e) => setError(e.message))}
                disabled={!syncId.current || st?.cancel}
                title="Stop after the PO that is being processed right now; what is already saved stays saved"
              >
                {st?.cancel ? "Cancelling…" : "Cancel"}
              </button>
            )}
            {phase === "done" && <button onClick={onClose}>Close</button>}
          </div>
        </div>
      </div>
    </div>
  );
}
