import { useEffect, useState } from "react";
import { downloadT1Report } from "./api.js";

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";

export default function T1Dialog({ onClose }) {
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [bsos, setBsos] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {type, text}

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  async function run() {
    setBusy(true);
    setMsg({ type: "info", text: "Reading T1 Process data from Business Central…" });
    try {
      const { rows, name } = await downloadT1Report(from, to, bsos);
      setMsg({ type: "ok", text: `Downloaded ${name} (${rows.toLocaleString()} rows).` });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    }
    setBusy(false);
  }

  return (
    <div className="overlay center" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal narrow" role="dialog" aria-label="T1 Process Report">
        <div className="drawer-head">
          <h2>T1 Process Report</h2>
          {!busy && <button className="icon" onClick={onClose} aria-label="Close">✕</button>}
        </div>

        <div className="modal-body">
          <p className="muted">
            Excel output of Report 80000 (T1 Process Batch): one row per BSO line, with the report&apos;s columns in the
            same order. It shows the data saved by the last T1 batch run in Business Central.
          </p>
          <div className="dates">
            <label>BSO Order Date from <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label>to <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          </div>
          <label>
            BSO numbers (optional — comma, space or newline separated)
            <textarea rows={3} value={bsos} placeholder="BSOCSIN262700264" onChange={(e) => setBsos(e.target.value)} />
          </label>
          {msg && <div className={`msg ${msg.type}`}>{msg.text}</div>}
        </div>

        <div className="drawer-foot">
          <div className="row">
            <span className="spacer" />
            <button onClick={onClose} disabled={busy}>Close</button>
            <button className="primary" onClick={run} disabled={busy || !from || !to}>
              {busy ? "Working…" : "Download Excel"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
