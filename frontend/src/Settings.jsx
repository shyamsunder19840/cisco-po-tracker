import { useEffect, useState } from "react";
import { getSettings, saveSettings, testSettings } from "./api.js";

const toForm = (f) =>
  Object.fromEntries(f.map((x) => [x.key, x.kind === "list" ? x.value.split(/,\s*/).filter(Boolean).join("\n") : x.value]));

export default function Settings({ onClose, onSaved }) {
  const [fields, setFields] = useState(null);
  const [values, setValues] = useState({});
  const [show, setShow] = useState({});
  const [fieldErrors, setFieldErrors] = useState({});
  const [msg, setMsg] = useState(null); // {type, text}
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getSettings()
      .then((f) => {
        setFields(f);
        setValues(toForm(f));
      })
      .catch((e) => setMsg({ type: "error", text: e.message }));
  }, []);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = (k, v) => setValues((s) => ({ ...s, [k]: v }));

  async function save() {
    setBusy(true);
    setMsg(null);
    setFieldErrors({});
    try {
      const res = await saveSettings(values);
      setFields(res.settings);
      setValues(toForm(res.settings));
      setMsg({ type: "ok", text: "Settings saved and applied." });
      onSaved?.();
    } catch (e) {
      setFieldErrors(e.fields || {});
      setMsg({ type: "error", text: e.message });
    }
    setBusy(false);
  }

  async function test() {
    setBusy(true);
    setMsg({ type: "info", text: "Testing connections…" });
    try {
      const r = await testSettings();
      const line = (n, x) => `${n}: ${x.ok ? "connected ✓" : "failed — " + x.error}`;
      const ok = r.cisco.ok && r.bc.ok;
      setMsg({ type: ok ? "ok" : "error", text: `${line("Cisco", r.cisco)}\n${line("Business Central", r.bc)}` });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    }
    setBusy(false);
  }

  const groups = fields ? [...new Set(fields.map((f) => f.group))] : [];

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-label="Settings">
        <div className="drawer-head">
          <h2>Settings</h2>
          <button className="icon" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="drawer-body">
          {!fields && !msg && <p>Loading…</p>}
          {groups.map((g) => (
            <fieldset key={g}>
              <legend>{g}</legend>
              {fields.filter((f) => f.group === g).map((f) => (
                f.kind === "choice" ? (
                  <label key={f.key} className={fieldErrors[f.key] ? "bad" : ""}>
                    <span>{f.label}</span>
                    <select value={values[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}>
                      {!values[f.key] && <option value="">(not set)</option>}
                      {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                    {fieldErrors[f.key] && <small className="err">{fieldErrors[f.key]}</small>}
                  </label>
                ) : f.kind === "bool" ? (
                  <label key={f.key} className="toggle">
                    <input
                      type="checkbox"
                      checked={values[f.key] === "true"}
                      onChange={(e) => set(f.key, e.target.checked ? "true" : "false")}
                    />
                    <span>{f.label} <b>{values[f.key] === "true" ? "(on)" : "(off)"}</b></span>
                  </label>
                ) : f.kind === "list" ? (
                  <label key={f.key} className={fieldErrors[f.key] ? "bad" : ""}>
                    <span>{f.label}</span>
                    <textarea
                      rows={5}
                      value={values[f.key] ?? ""}
                      disabled={values.STATUS_FILTER_ENABLED !== "true"}
                      onChange={(e) => set(f.key, e.target.value)}
                    />
                    <small>Matching ignores upper/lower case. Lines whose Status Code is blank are also excluded while the filter is on.</small>
                    {fieldErrors[f.key] && <small className="err">{fieldErrors[f.key]}</small>}
                  </label>
                ) : (
                <label key={f.key} className={fieldErrors[f.key] ? "bad" : ""}>
                  <span>{f.label}</span>
                  <div className="field">
                    <input
                      type={f.secret && !show[f.key] ? "password" : f.kind === "int" ? "number" : "text"}
                      value={values[f.key] ?? ""}
                      placeholder={f.secret ? (f.set ? "•••••• saved — leave blank to keep" : "not set") : ""}
                      autoComplete="off"
                      onChange={(e) => set(f.key, e.target.value)}
                    />
                    {f.secret && (
                      <button type="button" className="icon" onClick={() => setShow((s) => ({ ...s, [f.key]: !s[f.key] }))}>
                        {show[f.key] ? "Hide" : "Show"}
                      </button>
                    )}
                  </div>
                  {fieldErrors[f.key] && <small className="err">{fieldErrors[f.key]}</small>}
                </label>
                )
              ))}
            </fieldset>
          ))}
        </div>

        <div className="drawer-foot">
          {msg && <div className={`msg ${msg.type}`}>{msg.text}</div>}
          <div className="row">
            <button onClick={test} disabled={busy || !fields}>Test connections</button>
            <span className="spacer" />
            <button onClick={onClose}>Close</button>
            <button className="primary" onClick={save} disabled={busy || !fields}>Save</button>
          </div>
        </div>
      </aside>
    </div>
  );
}
