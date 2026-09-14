"use strict";

(() => {
  const startButton = document.getElementById("voice-start");
  const stopButton = document.getElementById("voice-stop");
  const statusElement = document.getElementById("voice-status");
  const intentInput = document.getElementById("intent-input");
  if (!startButton || !stopButton || !statusElement || !intentInput) return;

  const MAX_RECORDING_MS = 30000;
  const TARGET_SAMPLE_RATE = 16000;
  let audioContext = null;
  let mediaStream = null;
  let sourceNode = null;
  let processorNode = null;
  let silentGain = null;
  let audioChunks = [];
  let recordingStartedAt = 0;
  let recordingTimer = null;
  let recordingTimeout = null;
  let transcribing = false;

  startButton.addEventListener("click", startRecording);
  stopButton.addEventListener("click", stopRecording);
  checkService();

  async function checkService() {
    if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext)) {
      setStatus("当前浏览器不支持麦克风录音", "error");
      startButton.disabled = true;
      return;
    }
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.asr?.configured) {
        setStatus("语音服务已连接，但尚未配置腾讯云密钥", "warning");
        startButton.disabled = true;
        return;
      }
      setStatus("语音服务就绪，最长录音30秒", "ready");
      startButton.disabled = false;
    } catch (error) {
      setStatus("语音后端未连接，请使用 start-demo.bat 启动", "error");
      startButton.disabled = true;
    }
  }

  async function startRecording() {
    if (transcribing || mediaStream) return;
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      audioContext = new AudioContextClass();
      sourceNode = audioContext.createMediaStreamSource(mediaStream);
      processorNode = audioContext.createScriptProcessor(4096, 1, 1);
      silentGain = audioContext.createGain();
      silentGain.gain.value = 0;
      audioChunks = [];
      processorNode.onaudioprocess = (event) => {
        audioChunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      sourceNode.connect(processorNode);
      processorNode.connect(silentGain);
      silentGain.connect(audioContext.destination);
      window.dispatchEvent(new CustomEvent("autolab:asr-recording-started"));
      recordingStartedAt = Date.now();
      setRecordingControls(true);
      updateRecordingStatus();
      recordingTimer = window.setInterval(updateRecordingStatus, 250);
      recordingTimeout = window.setTimeout(stopRecording, MAX_RECORDING_MS);
    } catch (error) {
      cleanupAudioGraph();
      setStatus(
        error?.name === "NotAllowedError"
          ? "未获得麦克风权限，请在浏览器中允许访问"
          : `录音启动失败：${error.message || error}`,
        "error"
      );
    }
  }

  async function stopRecording() {
    if (!mediaStream || transcribing) return;
    const utteranceEndedAt = Date.now();
    const utteranceStartedAt = recordingStartedAt;
    const inputSampleRate = audioContext.sampleRate;
    clearRecordingTimers();
    const chunks = audioChunks;
    cleanupAudioGraph();
    setRecordingControls(false);
    if (!chunks.length) {
      setStatus("没有采集到有效音频，请重试", "error");
      return;
    }

    transcribing = true;
    startButton.disabled = true;
    setStatus("正在转写，请稍候...", "working");
    try {
      const merged = mergeAudioChunks(chunks);
      const pcm16k = downsampleAudio(merged, inputSampleRate, TARGET_SAMPLE_RATE);
      const wavBlob = encodeWav(pcm16k, TARGET_SAMPLE_RATE);
      const formData = new FormData();
      formData.append("audio", wavBlob, "vd10-intent.wav");
      const response = await fetch("/api/asr/transcribe", {
        method: "POST",
        body: formData
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      const text = String(data.text || "").trim();
      if (!text) throw new Error("转写结果为空");
      const recognitionCompletedAt = Date.now();
      const asrTiming = {
        utteranceStartedAt,
        utteranceEndedAt,
        recognitionCompletedAt,
        audioDurationMs: Math.max(0, utteranceEndedAt - utteranceStartedAt),
        timeUnit: "unix_ms"
      };
      intentInput.value = text;
      intentInput.dispatchEvent(new Event("input", { bubbles: true }));
      window.dispatchEvent(new CustomEvent("autolab:asr-transcription", {
        detail: { text, asrTiming }
      }));
      intentInput.focus();
      setStatus(`转写完成（${data.timing?.total_elapsed_ms ?? "--"} ms），请确认文字后发送语义处理`, "success");
    } catch (error) {
      setStatus(`转写失败：${error.message || error}`, "error");
    } finally {
      transcribing = false;
      startButton.disabled = false;
    }
  }

  function updateRecordingStatus() {
    const elapsed = Math.min(MAX_RECORDING_MS, Date.now() - recordingStartedAt);
    setStatus(`正在录音 ${(elapsed / 1000).toFixed(1)} 秒，最长30秒`, "recording");
  }

  function setRecordingControls(recording) {
    startButton.hidden = recording;
    stopButton.hidden = !recording;
    stopButton.disabled = false;
  }

  function clearRecordingTimers() {
    window.clearInterval(recordingTimer);
    window.clearTimeout(recordingTimeout);
    recordingTimer = null;
    recordingTimeout = null;
  }

  function cleanupAudioGraph() {
    clearRecordingTimers();
    if (processorNode) {
      processorNode.onaudioprocess = null;
      processorNode.disconnect();
    }
    sourceNode?.disconnect();
    silentGain?.disconnect();
    mediaStream?.getTracks().forEach((track) => track.stop());
    audioContext?.close().catch(() => {});
    processorNode = null;
    sourceNode = null;
    silentGain = null;
    mediaStream = null;
    audioContext = null;
  }

  function mergeAudioChunks(chunks) {
    const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const merged = new Float32Array(length);
    let offset = 0;
    chunks.forEach((chunk) => {
      merged.set(chunk, offset);
      offset += chunk.length;
    });
    return merged;
  }

  function downsampleAudio(input, inputRate, outputRate) {
    if (inputRate === outputRate) return input;
    if (outputRate > inputRate) throw new Error("目标采样率不能高于输入采样率");
    const ratio = inputRate / outputRate;
    const outputLength = Math.floor(input.length / ratio);
    const output = new Float32Array(outputLength);
    for (let index = 0; index < outputLength; index += 1) {
      const start = Math.floor(index * ratio);
      const end = Math.min(input.length, Math.floor((index + 1) * ratio));
      let sum = 0;
      for (let sourceIndex = start; sourceIndex < end; sourceIndex += 1) {
        sum += input[sourceIndex];
      }
      output[index] = sum / Math.max(1, end - start);
    }
    return output;
  }

  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeAscii(view, 8, "WAVE");
    writeAscii(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (const sample of samples) {
      const clamped = Math.max(-1, Math.min(1, sample));
      view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
      offset += 2;
    }
    return new Blob([view], { type: "audio/wav" });
  }

  function writeAscii(view, offset, text) {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  }

  function setStatus(message, state) {
    statusElement.textContent = message;
    statusElement.dataset.state = state;
  }
})();
