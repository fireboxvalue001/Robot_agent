"use strict";

(() => {
  const fileInput = document.getElementById("document-intent-file");
  const uploadButton = document.getElementById("document-intent-upload");
  const status = document.getElementById("document-intent-status");
  const resultPanel = document.getElementById("document-intent-result");
  const resultJson = document.getElementById("document-intent-json");
  if (!fileInput || !uploadButton || !status || !resultPanel || !resultJson) return;

  function setStatus(message, state = "") {
    status.textContent = message;
    status.className = `document-intent-status ${state}`.trim();
  }

  uploadButton.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    uploadButton.disabled = true;
    setStatus(`正在识别 ${file.name}...`, "working");
    const form = new FormData();
    form.append("document", file, file.name);
    try {
      const response = await fetch("/api/intent/document", { method: "POST", body: form });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      resultJson.textContent = JSON.stringify(payload, null, 2);
      resultPanel.hidden = false;
      const clarification = payload.semanticParams?.clarification;
      setStatus(
        clarification?.needed ? "识别完成，存在待确认项" : "委托单识别完成",
        clarification?.needed ? "working" : "success"
      );
      window.dispatchEvent(new CustomEvent("autolab:document-intent", { detail: payload }));
    } catch (error) {
      setStatus(`委托单识别失败：${error.message || error}`, "error");
    } finally {
      uploadButton.disabled = false;
      fileInput.value = "";
    }
  });
})();
