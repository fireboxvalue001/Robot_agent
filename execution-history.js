"use strict";

// Archives are read-only snapshots, never executable device commands.
(() => {
  let timer;
  let savedKey = "";
  let selected = null;
  let viewingId = null;
  let viewGeneration = 0;
  let busy = false;
  let queued = null;
  let offset = 0;
  const pageSize = 20;
  const el = (id) => document.getElementById(id);
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
  const api = async (path, options) => {
    const response = await fetch(`/api/execution/${path}`, options);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`);
    }
    return response.json();
  };
  const notify = (message) => { el("archive-status").textContent = message; };

  async function refresh() {
    try {
      const result = await api(`archives?limit=${pageSize}&offset=${offset}`);
      el("archive-list").innerHTML = result.items.length ? result.items.map((item) => `
        <div class="execution-record"><strong>
          ${escape(new Date(item.created_at).toLocaleString("zh-CN"))} · ${item.record_source === "simulation" ? "演示记录，非实机" : "流程草案，未执行"}
        </strong><p>${escape(item.source_text.slice(0, 100))}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="button compact" data-archive-id="${escape(item.archive_id)}" data-action="view">查看记录</button>
          <button type="button" class="button compact" data-archive-id="${escape(item.archive_id)}" data-action="export">导出 JSON</button>
        </div></div>`).join("") : '<p class="helper">暂无本地执行档案，请先生成流程并等待归档成功。</p>';
      el("archive-page").textContent = `${result.total ? offset + 1 : 0}–${Math.min(offset + pageSize, result.total)} / ${result.total}`;
      el("archive-prev").disabled = offset === 0;
      el("archive-next").disabled = offset + pageSize >= result.total;
    } catch (error) { notify(`历史读取失败：${error.message}`); }
  }

  async function save(snapshot) {
    if (!snapshot) return;
    const key = JSON.stringify(snapshot);
    if (key === savedKey) return;
    if (busy) { queued = snapshot; return; }
    busy = true;
    notify("正在保存到本机后端…");
    try {
      const result = await api("archives", { method: "POST", headers: { "Content-Type": "application/json" }, body: key });
      savedKey = key;
      notify(`已归档 ${new Date(result.created_at).toLocaleString("zh-CN")}；非实机执行记录`);
      offset = 0;
      await refresh();
    } catch (error) {
      notify(`保存失败，尚未归档：${error.message}。请点击“保存当前记录”重试。`);
    } finally {
      busy = false;
      if (queued) { const next = queued; queued = null; await save(next); }
    }
  }

  function schedule() {
    // Capture now so clearing or editing the live flow cannot overwrite this snapshot.
    const snapshot = window.getExecutionArchiveSnapshot?.();
    if (!snapshot) return;
    const captured = JSON.parse(JSON.stringify(snapshot));
    clearTimeout(timer);
    timer = setTimeout(() => save(captured), 500);
  }

  window.addEventListener("autolab:archive-changed", schedule);
  el("archive-save").addEventListener("click", () => {
    const snapshot = window.getExecutionArchiveSnapshot?.();
    if (!snapshot) { notify("请先生成流程；历史记录不会因清空当前流程而删除。"); return; }
    clearTimeout(timer);
    save(JSON.parse(JSON.stringify(snapshot)));
  });
  el("archive-refresh").addEventListener("click", refresh);
  el("archive-prev").addEventListener("click", () => { offset = Math.max(0, offset - pageSize); refresh(); });
  el("archive-next").addEventListener("click", () => { offset += pageSize; refresh(); });
  el("archive-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-archive-id]");
    if (!button) return;
    const exporting = button.dataset.action === "export";
    const archiveId = button.dataset.archiveId;
    const generation = exporting ? viewGeneration : ++viewGeneration;
    if (!exporting) {
      if (viewingId === archiveId) {
        viewingId = null;
        el("archive-detail").hidden = true;
        return;
      }
      viewingId = archiveId;
      el("archive-detail").hidden = true;
    }
    try {
      const archive = await api(`archives/${encodeURIComponent(archiveId)}`);
      if (exporting) {
        exportArchive(archive);
        return;
      }
      if (generation !== viewGeneration) return;
      selected = archive;
      const snap = selected.snapshot;
      el("archive-detail").hidden = false;
      el("archive-detail-title").textContent = `${snap.task_id} · ${snap.record_source === "simulation" ? "演示记录，非实机" : "流程草案，未执行"}`;
      el("archive-records").innerHTML = snap.execution_records.map((row, i) => `
        <article class="execution-record"><strong>${i + 1}. ${escape(row.name || row.step_id)}</strong>
        <p>${row.status === "simulated_success" ? "演示完成，非实机" : "待执行"}</p>
        <p>开始：${escape(row.started_at || "未开始")}<br>结束：${escape(row.finished_at || "未结束")}<br>耗时：${escape(row.duration_ms ?? "—")} ms</p>
        <pre style="white-space:pre-wrap;overflow-wrap:anywhere">${escape(typeof row.key_data === "string" ? row.key_data : JSON.stringify(row.key_data ?? {}, null, 2))}</pre></article>`).join("");
      el("archive-json").textContent = JSON.stringify(selected, null, 2);
    } catch (error) {
      if (!exporting && generation !== viewGeneration) return;
      if (!exporting) viewingId = null;
      notify(`档案读取失败：${error.message}`);
    }
  });
  function exportArchive(archive) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(archive, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${archive.archive_id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  el("archive-export").addEventListener("click", () => {
    if (selected) exportArchive(selected);
  });
  refresh();
  schedule();
})();
