import { useEffect, useMemo, useRef, useState } from "react";
import Settings from "./Settings.jsx";
import SyncDialog from "./SyncDialog.jsx";
import T1Dialog from "./T1Dialog.jsx";
import DailyTracker from "./DailyTracker.jsx";
import { getInfo, downloadComplete, downloadExcel, getProgress, submitByDate, submitByT1, submitPOs } from "./api.js";

// Preferred column order; any other field Cisco returns is appended after these.
const KNOWN = [
  "BC PO No.", "PO Order Date", "PO ID", "Order Status", "Web Order ID", "Last Product Ship",
  "Sales Order Reference", "PO Line Number", "SO Line Number", "SO Line Ref", "Major/Minor",
  "Line ID Set", "Item ID", "Quantity", "Status Code", "Ship From",
  "Estimated Ship DateTime", "Shipment DateTime", "Promised Delivery DateTime",
  "Est. Delivery DateTime", "Recommit DateTime", "Recommit Reason",
  "Delivery Status", "Final Scheduled Ship Date",
];

// T1 report filter taken from the last Check status: PO numbers -> Proactive PO, Customer PO -> Customer PO, dates -> dates
function t1Prefill(run) {
  if (!run) return {};
  const list = (txt) => txt.split(/[\s,;]+/).filter(Boolean).join("\n");
  if (run.tab === "po") return { ppos: list(run.poText) };
  if (run.tab === "t1") return { cpos: list(run.bsoText) };
  return { from: run.from, to: run.to };
}

const USER = { name: "Shyam Sunder Singh", initials: "SSS" }; // shown at the right of the header
const PAGE = 100;
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";

export default function App() {
  const [view, setView] = useState("home"); // home = daily tracker (first page), run = do the task
  const [tab, setTab] = useState("po");
  const [poText, setPoText] = useState("");
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [bsoText, setBsoText] = useState("");
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [page, setPage] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [showSync, setShowSync] = useState(false);
  const [showT1, setShowT1] = useState(false);
  const [lastRun, setLastRun] = useState(null); // inputs of the last Check status, used to prefill the T1 report
  const timer = useRef(null);

  const [database, setDatabase] = useState("");
  const loadInfo = () => getInfo().then((i) => setDatabase(i.database || "")).catch(() => {});
  useEffect(() => { loadInfo(); }, []);

  useEffect(() => () => clearInterval(timer.current), []);

  function poll(jobId) {
    clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const p = await getProgress(jobId, false);
        if (p.status === "done") {
          clearInterval(timer.current);
          setJob(await getProgress(jobId, true));
          setBusy(false);
        } else {
          setJob(p);
        }
      } catch (e) {
        clearInterval(timer.current);
        setBusy(false);
        setError(e.message);
      }
    }, 1000);
  }

  async function run() {
    setError("");
    setJob(null);
    setPage(0);
    setBusy(true);
    setLastRun({ tab, poText, bsoText, from, to });
    try {
      const res = tab === "po" ? await submitPOs(poText)
        : tab === "t1" ? await submitByT1(bsoText)
        : await submitByDate(from, to);
      setJob({ id: res.job_id, status: "running", total: res.total, done: 0, rows: [], errors: [], not_found: [] });
      poll(res.job_id);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const rows = job?.rows ?? [];
  const COLUMNS = useMemo(() => {
    const present = new Set(rows.flatMap((r) => Object.keys(r)));
    const extra = [...present].filter((c) => !KNOWN.includes(c)).sort();
    return [...KNOWN.filter((c) => present.has(c)), ...extra];
  }, [rows]);
  const statuses = useMemo(() => ["All", ...new Set(rows.map((r) => r["Delivery Status"]))], [rows]);
  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (statusFilter === "All" || r["Delivery Status"] === statusFilter) &&
        (!q || Object.values(r).some((v) => String(v).toLowerCase().includes(q)))
    );
  }, [rows, filter, statusFilter]);

  const pages = Math.max(1, Math.ceil(visible.length / PAGE));
  const cur = Math.min(page, pages - 1);
  const shown = visible.slice(cur * PAGE, (cur + 1) * PAGE);
  const pct = job?.total ? Math.round((job.done / job.total) * 100) : 0;
  const canRun = tab === "po" ? poText.trim() : tab === "t1" ? bsoText.trim() : from && to;
  const dateLabel = "Check status";

  return (
    <>
      <header className="shellbar">
        <span className="launcher" aria-hidden>
          {Array.from({ length: 9 }, (_, i) => <i key={i} />)}
        </span>
        <h1>Cisco PO Status Tracker</h1>
        <span className="grow" />
        <span className="company-badge" aria-hidden>PDS</span>
        {database && (
          <span className="env" title="Business Central database (environment)">
            <small>Environment:</small>
            <b>{database}</b>
          </span>
        )}
        <button className="gear" onClick={() => setShowSettings(true)} title="Settings" aria-label="Settings">&#9881;</button>
        <span className="user">{USER.name}</span>
        <span className="avatar" aria-hidden>{USER.initials}</span>
      </header>
      <nav className="subnav">
        <span className="company">Proactive Data Systems Pvt. Ltd.</span>
        <span className="sep" aria-hidden />
        <button className={view === "home" ? "active" : ""} disabled={busy} onClick={() => setView("home")}>Home</button>
        <button className={view === "run" ? "active" : ""} onClick={() => setView("run")}>Cisco Orders</button>
        <button onClick={() => setShowSettings(true)}>Settings</button>
      </nav>
    <div className="page">
      {showSettings && <Settings onClose={() => setShowSettings(false)} onSaved={loadInfo} />}
      {showSync && <SyncDialog job={job} onClose={() => setShowSync(false)} />}
      {showT1 && <T1Dialog onClose={() => setShowT1(false)} prefill={t1Prefill(lastRun)} />}

      {view === "home" && <DailyTracker onStart={() => setView("run")} />}
      {view === "run" && (
      <>
      <section className="card">
        <div className="tabs">
          <button className={tab === "po" ? "active" : ""} onClick={() => setTab("po")}>
            A · PO Numbers
          </button>
          <button className={tab === "t1" ? "active" : ""} onClick={() => setTab("t1")}>
            B · Customer PO No.
          </button>
          <button className={tab === "date" ? "active" : ""} onClick={() => setTab("date")}>
            C · PO Order Date
          </button>
        </div>

        {tab === "t1" ? (
          <label>
            Customer PO numbers (comma, space or newline separated)
            <textarea rows={5} value={bsoText} placeholder={"4500348821\n4500349133"} onChange={(e) => setBsoText(e.target.value)} />
            <small>
              Each Customer PO No. is looked up in the T1 Process Report (Customer_PO_No); its Proactive PO No. is then checked against Cisco.
            </small>
          </label>
        ) : tab === "po" ? (
          <label>
            PO numbers (comma, space or newline separated; -M/-S suffixes are stripped)
            <textarea
              rows={5}
              value={poText}
              placeholder={"POCSIN262700356\nPOCSIN262700357"}
              onChange={(e) => setPoText(e.target.value)}
            />
          </label>
        ) : (
          <div className="dates">
            <label>From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label>To <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
            <small>POs are listed from Business Central (POCSIN prefix, max 500), then checked against Cisco.</small>
          </div>
        )}

        <div className="btn-row">
          <button className="primary" disabled={busy || !canRun} onClick={run}>
            {busy ? "Working…" : dateLabel}
          </button>
          <button
            className="sync-btn"
            disabled={busy || job?.status !== "done" || rows.length === 0}
            title={rows.length ? "Write the fetched data into Business Central purchase lines" : "Run Check status first"}
            onClick={() => setShowSync(true)}
          >
            Sync into Business Central
          </button>
          <button className="sync-btn" onClick={() => setShowT1(true)} title="Download the T1 Process Report (Report 80000) as Excel">
            T1 Process Report
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </section>

      {job && (
        <section className="card">
          <div className="progress-head">
            <strong>{job.status === "done" ? "Complete" : "Fetching from Cisco…"}</strong>
            <span>{job.done}/{job.total} POs · {job.row_count ?? rows.length} lines</span>
          </div>
          <div className="bar"><div style={{ width: `${pct}%` }} /></div>

          {job.filter && (
            <div className="info">
              Status Code filter is on ({job.filter.length} values) — {job.filtered_out ?? 0} line(s) with other Status Codes were hidden.
              Change this in Settings.
            </div>
          )}
          {job.not_found.length > 0 && (
            <div className="warn">No data returned for: {job.not_found.join(", ")}</div>
          )}
          {job.errors.length > 0 && (
            <details className="error">
              <summary>{job.errors.length} PO(s) failed</summary>
              <ul>{job.errors.map((e) => <li key={e.po}><b>{e.po}</b>: {e.error}</li>)}</ul>
            </details>
          )}

          {rows.length > 0 && (
            <>
              <div className="toolbar">
                <input placeholder="Search table…" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(0); }} />
                <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}>
                  {statuses.map((s) => <option key={s}>{s}</option>)}
                </select>
                <span className="count">{visible.length} rows · {COLUMNS.length} fields</span>
                <button onClick={() => downloadExcel(visible).catch((e) => setError(e.message))}>
                  Download Excel
                </button>
                <button
                  title="Every line Cisco returned for these POs, ignoring the Status Code filter"
                  onClick={() => downloadComplete(job.id).catch((e) => setError(e.message))}
                >
                  Download complete data{job.all_count > rows.length ? ` (${job.all_count} lines)` : ""}
                </button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr>{COLUMNS.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>
                    {shown.map((r, i) => (
                      <tr key={i}>
                        {COLUMNS.map((c) => (
                          <td key={c}>
                            {c === "Delivery Status"
                              ? <span className={`pill ${String(r[c]).replace(/\s+/g, "-").toLowerCase()}`}>{r[c]}</span>
                              : typeof r[c] === "object" && r[c] !== null ? JSON.stringify(r[c]) : r[c]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pager">
                <button disabled={cur === 0} onClick={() => setPage(cur - 1)}>‹ Prev</button>
                <span>Page {cur + 1} of {pages} (showing {shown.length} of {visible.length})</span>
                <button disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)}>Next ›</button>
              </div>
            </>
          )}
        </section>
      )}
      </>
      )}
    </div>
    </>
  );
}
