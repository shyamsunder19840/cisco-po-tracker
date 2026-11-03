async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}

export const submitPOs = (po_numbers) => post("/api/submit", { po_numbers });
export const submitByDate = (from_date, to_date) =>
  post("/api/submit_by_date", { from_date, to_date });

export const submitByT1 = (customer_pos) => post("/api/submit_by_t1", { customer_pos });

export async function getProgress(jobId, withRows = true) {
  const r = await fetch(`/api/progress/${jobId}${withRows ? "" : "?rows=0"}`);
  if (!r.ok) throw new Error("Job not found");
  return r.json();
}

export async function downloadExcel(rows) {
  const r = await fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows }),
  });
  if (!r.ok) throw new Error("Download failed");
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `Cisco_PO_Status_${new Date().toISOString().slice(0, 10)}.xlsx`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function getHistory() {
  const r = await fetch("/api/history");
  if (!r.ok) throw new Error("Could not load the daily history");
  return r.json();
}

export async function getSettings() {
  const r = await fetch("/api/settings");
  if (!r.ok) throw new Error("Could not load settings");
  return r.json();
}

export async function saveSettings(values) {
  const r = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(data.error || "Save failed");
    err.fields = data.fields || {};
    throw err;
  }
  return data;
}

export async function testSettings() {
  const r = await fetch("/api/settings/test", { method: "POST" });
  if (!r.ok) throw new Error("Test failed");
  return r.json();
}

export async function startSync(job_id, dry_run) {
  const r = await fetch("/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id, dry_run }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Could not start the sync");
  return data;
}

export async function getSync(id, withDetails = true) {
  const r = await fetch(`/api/sync/${id}${withDetails ? "" : "?details=0"}`);
  if (!r.ok) throw new Error("Sync not found");
  return r.json();
}

export async function downloadT1Report(filters) {
  const r = await fetch("/api/t1report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.error || `Report failed (${r.status})`);
  }
  const rows = Number(r.headers.get("X-Row-Count") || 0);
  const name = (r.headers.get("Content-Disposition") || "").match(/filename="?([^";]+)"?/)?.[1] || "T1_Process_Report.xlsx";
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
  return { rows, name };
}

// Every line Cisco returned for the fetched POs, ignoring the Status Code filter.
export async function downloadComplete(job_id) {
  const r = await fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id, full: true }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Download failed");
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `Cisco_PO_Status_complete_${new Date().toISOString().slice(0, 10)}.xlsx`;
  a.click();
  URL.revokeObjectURL(url);
}
