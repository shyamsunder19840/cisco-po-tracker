import { useEffect, useState } from "react";
import { downloadT1Report } from "./api.js";

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";

function Section({ title, open, children }) {
  return (
    <details className="filter-section" open={open}>
      <summary>{title}</summary>
      {children}
    </details>
  );
}

// prefill: the filter of the last "Check status" run ({ cpos, ppos, from, to }), so the report starts with the same values
export default function T1Dialog({ onClose, prefill = {} }) {
  const [from, setFrom] = useState(prefill.from || monthStart());
  const [to, setTo] = useState(prefill.to || today());
  const [bsos, setBsos] = useState("");
  const [cpos, setCpos] = useState(prefill.cpos || "");
  const [ppos, setPpos] = useState(prefill.ppos || "");
  // only the filters that were filled from the last Check status are open; the others are minimized
  const openDates = !!prefill.from || !(prefill.cpos || prefill.ppos);
  const byNumber = !!(bsos.trim() || cpos.trim() || ppos.trim()); // numbers entered -> the date range is not applied
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
      await downloadT1Report({
        from_date: byNumber ? "" : from, to_date: byNumber ? "" : to,
        bso_nos: bsos, customer_pos: cpos, proactive_pos: ppos,
      });
      onClose(); // the report is downloaded: close this window
      return;
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    }
    setBusy(false);
  }

  return (
    <div className="overlay center" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal narrow" role="dialog" aria-label="T1 Report">
        <div className="drawer-head">
          <h2>T1 Report</h2>
          {!busy && <button className="icon" onClick={onClose} aria-label="Close">✕</button>}
        </div>

        <div className="modal-body">
          <Section title="BSO Order Date range" open={openDates}>
            <div className="dates">
              <label>from <input type="date" value={from} disabled={byNumber} onChange={(e) => setFrom(e.target.value)} /></label>
              <label>to <input type="date" value={to} disabled={byNumber} onChange={(e) => setTo(e.target.value)} /></label>
            </div>
            {byNumber && <small>A number filter is entered, so the date range is not applied.</small>}
          </Section>
          <Section title="Customer PO numbers" open={!!prefill.cpos}>
            <textarea rows={2} value={cpos} placeholder="4500348821 (comma, space or newline separated)" onChange={(e) => setCpos(e.target.value)} />
          </Section>
          <Section title="Proactive PO numbers" open={!!prefill.ppos}>
            <textarea rows={2} value={ppos} placeholder="POCSIN262700355 (-M/-S endings are matched automatically)" onChange={(e) => setPpos(e.target.value)} />
          </Section>
          <Section title="BSO numbers" open={false}>
            <textarea rows={2} value={bsos} placeholder="BSOCSIN262700264" onChange={(e) => setBsos(e.target.value)} />
          </Section>
          {msg && <div className={`msg ${msg.type}`}>{msg.text}</div>}
        </div>

        <div className="drawer-foot">
          <div className="row">
            <span className="spacer" />
            <button onClick={onClose} disabled={busy}>Close</button>
            <button className="primary" onClick={run} disabled={busy || (!byNumber && (!from || !to))}>
              {busy ? "Working…" : "Download Excel"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
