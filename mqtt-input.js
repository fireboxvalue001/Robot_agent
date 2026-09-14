"use strict";

(() => {
  const sendButton = document.getElementById("mqtt-send");
  const statusElement = document.getElementById("mqtt-status");
  const resultContainer = document.getElementById("mqtt-result");
  const resultOutput = document.getElementById("mqtt-result-json");
  const historyButton = document.getElementById("mqtt-history-load");
  const historyContainer = document.getElementById("mqtt-history-result");
  const historyOutput = document.getElementById("mqtt-history-json");
  const intentInput = document.getElementById("intent-input");
  if (!sendButton || !statusElement || !resultContainer || !resultOutput ||
      !historyButton || !historyContainer || !historyOutput || !intentInput) return;

  const POLL_INTERVAL_MS = 1000;
  const RESPONSE_TIMEOUT_MS = 90000;
  let activeWorkflowId = null;
  let requestGeneration = 0;
  let pendingAsrInput = null;

  sendButton.addEventListener("click", publishIntent);
  historyButton.addEventListener("click", loadHistory);
  intentInput.addEventListener("input", clearStaleAsrTiming);
  window.addEventListener("autolab:asr-recording-started", clearAsrTiming);
  window.addEventListener("autolab:asr-transcription", rememberAsrTiming);
  checkMqttStatus();
  window.setInterval(checkMqttStatus, 5000);

  async function checkMqttStatus() {
    if (activeWorkflowId) return;
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const mqtt = data.mqtt || {};
      if (!mqtt.enabled) {
        setStatus("MQTT已禁用", "warning");
        sendButton.disabled = true;
      } else if (mqtt.connected) {
        setStatus("MQTT已连接，可发送语义处理", "ready");
        sendButton.disabled = false;
      } else {
        setStatus("MQTT正在连接Broker...", "working");
        sendButton.disabled = true;
      }
    } catch (error) {
      setStatus("无法读取MQTT服务状态", "error");
      sendButton.disabled = true;
    }
  }

  async function publishIntent() {
    const text = intentInput.value.trim();
    if (!text) {
      setStatus("请先输入或转写操作意图", "error");
      return;
    }

    const generation = ++requestGeneration;
    activeWorkflowId = null;
    sendButton.disabled = true;
    resultContainer.hidden = true;
    setStatus("正在发布到 autolab/ui/input...", "working");

    try {
      const asrTiming = pendingAsrInput?.text === text
        ? pendingAsrInput.asrTiming
        : null;
      const response = await fetch("/api/mqtt/ui-input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(asrTiming ? { text, asrTiming } : { text })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

      activeWorkflowId = data.workflowId;
      pendingAsrInput = null;
      showPayload({
        stage: "ui_input_published",
        topic: data.topic,
        message: data.message
      });
      setStatus(`已发送，等待语义处理：${activeWorkflowId}`, "working");
      await waitForWorkflowResults(activeWorkflowId, generation);
    } catch (error) {
      if (generation !== requestGeneration) return;
      activeWorkflowId = null;
      setStatus(`MQTT发送失败：${error.message || error}`, "error");
      sendButton.disabled = false;
    }
  }

  function rememberAsrTiming(event) {
    const text = String(event.detail?.text || "").trim();
    const asrTiming = event.detail?.asrTiming;
    pendingAsrInput = text && asrTiming ? { text, asrTiming } : null;
  }

  function clearStaleAsrTiming() {
    if (pendingAsrInput && intentInput.value.trim() !== pendingAsrInput.text) {
      pendingAsrInput = null;
    }
  }

  function clearAsrTiming() {
    pendingAsrInput = null;
  }

  async function waitForWorkflowResults(workflowId, generation) {
    const deadline = Date.now() + RESPONSE_TIMEOUT_MS;
    const delivered = new Set();
    while (Date.now() < deadline && generation === requestGeneration) {
      await delay(POLL_INTERVAL_MS);
      const response = await fetch(`/api/mqtt/workflows/${encodeURIComponent(workflowId)}`, {
        cache: "no-store"
      });
      if (!response.ok) {
        if (response.status === 404) continue;
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
      const record = await response.json();
      if (record.semantic_params && !delivered.has(record.semantic_params.msgId)) {
        delivered.add(record.semantic_params.msgId);
        showPayload({ stage: record.state, topic: "autolab/semantic/params", message: record.semantic_params });
        window.dispatchEvent(new CustomEvent("autolab:semantic-params", { detail: record.semantic_params }));
        sendButton.disabled = false;
        if (record.semantic_params.status === "failed") {
          activeWorkflowId = null;
          setStatus("同事A返回预处理失败，请查看JSON", "error");
          return;
        }
        setStatus("已收到同事A预处理结果，等待同事B编排", "working");
      }
      if (record.planner_result && !delivered.has(record.planner_result.msgId)) {
        delivered.add(record.planner_result.msgId);
        showPayload({ stage: record.state, topic: "autolab/planner/result", message: record.planner_result });
        window.dispatchEvent(new CustomEvent("autolab:planner-result", { detail: record.planner_result }));
        if (record.planner_result.status === "failed") {
          activeWorkflowId = null;
          setStatus("同事B返回任务编排失败，请查看JSON", "error");
          return;
        }
        setStatus("已收到同事B操作链，等待物理可执行确认", "working");
      }
      if (record.physical_validation && !delivered.has(record.physical_validation.msgId)) {
        delivered.add(record.physical_validation.msgId);
        showPayload({ stage: record.state, topic: "autolab/physical/validation", message: record.physical_validation });
        window.dispatchEvent(new CustomEvent("autolab:physical-validation", { detail: record.physical_validation }));
        activeWorkflowId = null;
        sendButton.disabled = false;
        setStatus("已收到物理可执行确认", record.physical_validation.result === "executable" ? "success" : "warning");
        return;
      }
    }

    if (generation !== requestGeneration) return;
    activeWorkflowId = null;
    setStatus(delivered.size ? "后续模块等待超时，已收到的结果仍然保留" : "等待同事A预处理超时，原任务不会自动重发", "warning");
    sendButton.disabled = false;
  }

  async function loadHistory() {
    historyButton.disabled = true;
    historyOutput.innerHTML = '<div class="history-empty">正在读取历史记录...</div>';
    historyContainer.hidden = false;
    historyContainer.open = true;
    try {
      const response = await fetch("/api/mqtt/history?limit=100", { cache: "no-store" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      renderHistoryRecords(data.records || []);
    } catch (error) {
      historyOutput.innerHTML = `<div class="history-empty history-error">历史记录读取失败：${escapeHtml(error.message || error)}</div>`;
    } finally {
      historyButton.disabled = false;
    }
  }

  function renderHistoryRecords(records) {
    const semanticRecords = records.filter((record) => {
      return record?.topic === "autolab/semantic/params" ||
        record?.payload?.type === "semantic_params";
    });
    if (!semanticRecords.length) {
      historyOutput.innerHTML = '<div class="history-empty">当前没有可显示的语义处理历史。</div>';
      return;
    }

    historyOutput.innerHTML = semanticRecords.map((record, index) => {
      const payload = record.payload || {};
      const valid = isLoadableSemanticRecord(payload);
      const needsClarification = Boolean(payload.clarification?.needed);
      const fieldCount = Object.keys(payload.parameters || {}).length;
      const recordedAt = record.recorded_at ||
        (payload.timestamp ? new Date(payload.timestamp).toLocaleString("zh-CN", { hour12: false }) : "--");
      const buttonText = needsClarification ? "载入查看（需补充）" : "载入并生成流程";
      return `
        <article class="mqtt-history-card ${valid ? "" : "invalid"}">
          <div class="mqtt-history-head">
            <strong>${escapeHtml(payload.originalText || "无原始文字")}</strong>
            <span>${escapeHtml(recordedAt)}</span>
          </div>
          <div class="mqtt-history-meta">
            <span>workflowId：${escapeHtml(record.workflowId || payload.workflowId || "--")}</span>
            <span>预处理字段：${fieldCount} 项</span>
            <span>${needsClarification ? "需要补充信息" : (payload.status === "success" ? "预处理成功" : `状态：${escapeHtml(payload.status || "未知")}`)}</span>
          </div>
          <details><summary>查看原始语义 JSON</summary><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre></details>
          <button class="button compact history-use" type="button" data-history-index="${index}" ${valid ? "" : "disabled"}>${valid ? buttonText : "记录不可载入"}</button>
        </article>`;
    }).join("");

    historyOutput.querySelectorAll(".history-use").forEach((button) => {
      button.addEventListener("click", () => {
        const record = semanticRecords[Number(button.dataset.historyIndex)];
        loadHistoryRecord(record);
      });
    });
  }

  function isLoadableSemanticRecord(payload) {
    return payload && payload.type === "semantic_params" && payload.status === "success" &&
      typeof payload.originalText === "string" && payload.originalText.trim() &&
      payload.parameters && typeof payload.parameters === "object" && !Array.isArray(payload.parameters);
  }

  function loadHistoryRecord(record) {
    const payload = record?.payload;
    if (!isLoadableSemanticRecord(payload)) {
      setStatus("该历史记录不满足流程生成条件", "error");
      return;
    }
    window.dispatchEvent(new CustomEvent("autolab:semantic-history-selected", {
      detail: {
        message: payload,
        history: {
          workflowId: record.workflowId || payload.workflowId,
          msgId: record.msgId || payload.msgId,
          recorded_at: record.recorded_at || null
        }
      }
    }));
    setStatus(payload.clarification?.needed
      ? "历史预处理已载入，但仍需补充信息"
      : "历史预处理已载入，并已重新生成流程", payload.clarification?.needed ? "warning" : "success");
    historyContainer.open = false;
  }

  function showPayload(payload) {
    resultOutput.textContent = JSON.stringify(payload, null, 2);
    resultContainer.hidden = false;
    resultContainer.open = true;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setStatus(message, state) {
    statusElement.textContent = message;
    statusElement.dataset.state = state;
  }

  function delay(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }
})();
