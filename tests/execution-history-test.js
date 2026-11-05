"use strict";
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
const path = require("path");
const elements = new Map();
const listeners = {};
const timers = [];
const writes = [];
const downloads = [];
let failSave = false;
let snapshot = { task_id: "task_1", source_text: "<script>bad</script>", execution_records: [] };
const el = (id) => {
  if (!elements.has(id)) elements.set(id, { textContent: "", innerHTML: "", listeners: {},
    addEventListener(name, fn) { this.listeners[name] = fn; } });
  return elements.get(id);
};
const context = {
  document: { getElementById: el, createElement: () => ({ click() { downloads.push(this.download); } }) },
  Blob,
  URL: { createObjectURL: () => "blob:archive", revokeObjectURL() {} },
  window: { addEventListener: (name, fn) => { listeners[name] = fn; }, getExecutionArchiveSnapshot: () => snapshot },
  setTimeout: (fn) => { timers.push(fn); return timers.length; }, clearTimeout: () => {},
  fetch: async (url, options) => {
    if (options?.method === "POST") {
      writes.push(JSON.parse(options.body));
      return { ok: !failSave, status: 503, json: async () => failSave ? { detail: "offline" } : { created_at: "2026-11-04T10:00:00Z" } };
    }
    if (url.includes("archives/archive_1")) return { ok: true, json: async () => ({ archive_id: "archive_1", snapshot: {
      task_id: "task_1", record_source: "plan_draft", execution_records: [{ name: "<img src=x>", status: "pending" }]
    } }) };
    return { ok: true, json: async () => ({ total: 1, items: [{ archive_id: "archive_1", created_at: "2026-11-04T10:00:00Z", source_text: "<script>bad</script>", record_source: "plan_draft" }] }) };
  }
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../execution-history.js"), "utf8"), context);
const settle = () => new Promise((resolve) => setImmediate(resolve));
(async () => {
  await settle();
  assert(el("archive-list").innerHTML.includes("&lt;script&gt;"));
  assert(el("archive-list").innerHTML.includes('data-action="export"'));
  await el("archive-list").listeners.click({ target: { closest: () => ({ dataset: { archiveId: "archive_1", action: "export" } }) } });
  assert.deepEqual(downloads, ["archive_1.json"]);
  assert.equal(el("archive-records").innerHTML, "", "direct export must not require opening details");
  timers.pop();
  await timers.shift()();
  await settle();
  assert.equal(writes.length, 1);
  assert(el("archive-status").textContent.includes("已归档"));
  await el("archive-save").listeners.click();
  await settle();
  assert.equal(writes.length, 1, "unchanged snapshots must not be resent");
  snapshot = { ...snapshot, task_id: "task_2" };
  failSave = true;
  await el("archive-save").listeners.click();
  await settle();
  assert(el("archive-status").textContent.includes("尚未归档"));
  failSave = false;
  await el("archive-save").listeners.click();
  await settle();
  assert.equal(writes.length, 3, "failed writes must be retryable");
  await el("archive-list").listeners.click({ target: { closest: () => ({ dataset: { archiveId: "archive_1" } }) } });
  assert(el("archive-records").innerHTML.includes("&lt;img"));
  assert.equal(el("archive-detail").hidden, false);
  const clickView = () => el("archive-list").listeners.click({ target: { closest: () => ({ dataset: { archiveId: "archive_1", action: "view" } }) } });
  await clickView();
  assert.equal(el("archive-detail").hidden, true, "second click must collapse details");
  await clickView();
  assert.equal(el("archive-detail").hidden, false, "third click must reopen details");
  await el("archive-list").listeners.click({ target: { closest: () => ({ dataset: { archiveId: "archive_1", action: "export" } }) } });
  assert.equal(el("archive-detail").hidden, false, "export must not collapse details");
  await clickView();
  const pendingView = clickView();
  await clickView();
  await pendingView;
  assert.equal(el("archive-detail").hidden, true, "late responses must not reopen collapsed details");
  assert.equal(snapshot.task_id, "task_2", "history browsing must not overwrite live task");
  snapshot = null;
  el("archive-save").listeners.click();
  assert(el("archive-status").textContent.includes("请先生成"));
  console.log("Execution archive UI tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
