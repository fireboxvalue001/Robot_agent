"use strict";

(() => {
  const startButton = document.getElementById("voice-start");
  const stopButton = document.getElementById("voice-stop");
  const statusElement = document.getElementById("voice-status");
  const intentInput = document.getElementById("intent-input");
  if (!startButton || !stopButton || !statusElement || !intentInput) return;

  const LEGACY_MAX_RECORDING_MS = 30000;
  const TARGET_SAMPLE_RATE = 16000;
  let realtimeAvailable = false;
  let audioContext = null;
  let mediaStream = null;
  let sourceNode = null;
  let processorNode = null;
  let silentGain = null;
  let socket = null;
  let serviceStartedAt = 0;
  let streamStartedAt = 0;
  let legacyChunks = [];
  let legacyTimer = null;
  let legacyTimeout = null;
  let stopRequested = false;
  let transcribing = false;
  let sentenceResults = new Map();
  let partialSentence = null;
  let pcmRemainder = new Float32Array(0);

  startButton.addEventListener("click", startRecordingService);
  stopButton.addEventListener("click", stopRecordingService);
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
      realtimeAvailable = Boolean(data.asr.realtimeConfigured);
      setStatus(
        realtimeAvailable
          ? "实时语音服务就绪，点击后等待说话"
          : "缺少腾讯云AppId，将使用30秒兼容录音模式",
        realtimeAvailable ? "ready" : "warning"
      );
      startButton.disabled = false;
    } catch (error) {
      setStatus("语音后端未连接，请使用 start-demo.bat 启动", "error");
      startButton.disabled = true;
    }
  }

  async function startRecordingService() {
    if (transcribing || mediaStream || socket) return;
    serviceStartedAt = Date.now();
    stopRequested = false;
    sentenceResults = new Map();
    partialSentence = null;
    pcmRemainder = new Float32Array(0);
    legacyChunks = [];
    setRecordingControls(true);
    setStatus("正在启动麦克风服务...", "working");
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      if (realtimeAvailable) await startRealtimeStream();
      else startLegacyRecording();
      window.dispatchEvent(new CustomEvent("autolab:asr-recording-started", {
        detail: { serviceStartedAt, mode: realtimeAvailable ? "realtime" : "legacy" }
      }));
    } catch (error) {
      cleanupAudioGraph();
      closeSocket();
      setRecordingControls(false);
      setStatus(
        error?.name === "NotAllowedError"
          ? "未获得麦克风权限，请在浏览器中允许访问"
          : `录音启动失败：${error.message || error}`,
        "error"
      );
    }
  }

  async function startRealtimeStream() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${window.location.host}/api/asr/realtime`);
    socket.binaryType = "arraybuffer";

    await new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error("实时ASR连接超时")), 15000);
      socket.onmessage = (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch (error) {
          reject(new Error("实时ASR返回了无效数据"));
          return;
        }
        if (message.type === "service_ready") {
          window.clearTimeout(timeout);
          resolve();
        } else if (message.type === "error") {
          window.clearTimeout(timeout);
          reject(new Error(message.message || "实时ASR连接失败"));
        }
      };
      socket.onerror = () => {
        window.clearTimeout(timeout);
        reject(new Error("无法连接实时ASR服务"));
      };
    });

    socket.onmessage = handleRealtimeMessage;
    socket.onerror = () => failRealtimeSession("实时ASR连接异常");
    socket.onclose = () => {
      if (!stopRequested && mediaStream) failRealtimeSession("实时ASR连接已中断");
    };
    streamStartedAt = Date.now();
    socket.send(JSON.stringify({ type: "start", streamStartedAt }));
    setupAudioGraph((samples, sampleRate) => {
      if (socket?.readyState !== WebSocket.OPEN || stopRequested) return;
      sendRealtimeSamples(downsampleAudio(samples, sampleRate, TARGET_SAMPLE_RATE));
    });
    setStatus("语音服务已开启，正在等待说话...", "recording");
  }

  function handleRealtimeMessage(event) {
    const message = JSON.parse(event.data);
    if (message.type === "error") {
      failRealtimeSession(message.message || "实时语音识别失败");
      return;
    }
    if (message.type === "sentence") {
      const sentence = normalizeSentence(message);
      if (message.final) {
        sentenceResults.set(sentence.index, sentence);
        partialSentence = null;
        setStatus(`已识别第 ${sentenceResults.size} 句话，继续等待说话...`, "success");
      } else {
        partialSentence = sentence;
        setStatus("检测到说话，正在实时识别...", "recording");
      }
      updateLiveTranscript();
    } else if (message.type === "session_ended") {
      finalizeRealtimeSession();
    }
  }

  function normalizeSentence(message) {
    return {
      sentenceId: `utt_${String(Number(message.index) + 1).padStart(3, "0")}`,
      index: Number(message.index),
      text: String(message.text || "").trim(),
      startedAt: Number(message.startedAt),
      endedAt: Number(message.endedAt),
      startOffsetMs: Number(message.startOffsetMs),
      endOffsetMs: Number(message.endOffsetMs),
      recognitionCompletedAt: Number(message.recognitionCompletedAt || Date.now()),
      words: Array.isArray(message.words) ? message.words : []
    };
  }

  function updateLiveTranscript() {
    const textParts = sortedSentences().map((item) => item.text).filter(Boolean);
    if (partialSentence?.text) textParts.push(partialSentence.text);
    intentInput.value = textParts.join("");
  }

  function stopRecordingService() {
    if (!mediaStream || transcribing || stopRequested) return;
    stopRequested = true;
    stopButton.disabled = true;
    if (realtimeAvailable && socket) {
      cleanupAudioGraph();
      setStatus("正在结束识别并整理时间戳...", "working");
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "end" }));
      else failRealtimeSession("实时ASR连接已关闭");
    } else {
      stopLegacyRecording();
    }
  }

  function finalizeRealtimeSession() {
    const sentences = sortedSentences().filter((item) => item.text);
    cleanupAudioGraph();
    closeSocket();
    setRecordingControls(false);
    if (!sentences.length) {
      setStatus("本次没有检测到有效语音，请重新开始", "warning");
      return;
    }
    const first = sentences[0];
    const last = sentences[sentences.length - 1];
    const recognitionCompletedAt = Math.max(
      Date.now(), ...sentences.map((item) => item.recognitionCompletedAt)
    );
    const text = sentences.map((item) => item.text).join("");
    publishTranscription(text, {
      utteranceStartedAt: first.startedAt,
      utteranceEndedAt: last.endedAt,
      recognitionCompletedAt,
      audioDurationMs: Math.max(0, last.endedAt - first.startedAt),
      timeUnit: "unix_ms",
      serviceStartedAt,
      streamStartedAt,
      sentences
    });
    setStatus(`实时转写完成，共 ${sentences.length} 句话，请确认文字后发送语义处理`, "success");
  }

  function sortedSentences() {
    return [...sentenceResults.values()].sort((left, right) => left.index - right.index);
  }

  function failRealtimeSession(message) {
    cleanupAudioGraph();
    closeSocket();
    setRecordingControls(false);
    setStatus(`转写失败：${message}`, "error");
  }

  function startLegacyRecording() {
    streamStartedAt = Date.now();
    setupAudioGraph((samples) => legacyChunks.push(new Float32Array(samples)));
    setStatus("正在兼容录音 0.0 秒，最长30秒", "recording");
    legacyTimer = window.setInterval(updateLegacyStatus, 250);
    legacyTimeout = window.setTimeout(() => {
      if (mediaStream && !stopRequested) stopRecordingService();
    }, LEGACY_MAX_RECORDING_MS);
  }

  async function stopLegacyRecording() {
    const recordingEndedAt = Date.now();
    const inputSampleRate = audioContext.sampleRate;
    const chunks = legacyChunks;
    cleanupAudioGraph();
    setRecordingControls(false);
    if (!chunks.length) {
      setStatus("没有采集到有效音频，请重试", "error");
      return;
    }
    transcribing = true;
    startButton.disabled = true;
    setStatus("正在兼容转写，请稍候...", "working");
    try {
      const merged = mergeAudioChunks(chunks);
      const pcm16k = downsampleAudio(merged, inputSampleRate, TARGET_SAMPLE_RATE);
      const formData = new FormData();
      formData.append("audio", encodeWav(pcm16k, TARGET_SAMPLE_RATE), "vd10-intent.wav");
      const response = await fetch("/api/asr/transcribe", { method: "POST", body: formData });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      const text = String(data.text || "").trim();
      if (!text) throw new Error("转写结果为空");
      const words = (data.words || []).map((word) => ({
        ...word,
        startedAt: streamStartedAt + Number(word.startOffsetMs || 0),
        endedAt: streamStartedAt + Number(word.endOffsetMs || 0)
      }));
      const utteranceStartedAt = words[0]?.startedAt ?? streamStartedAt;
      const utteranceEndedAt = words.at(-1)?.endedAt ?? recordingEndedAt;
      const recognitionCompletedAt = Date.now();
      publishTranscription(text, {
        utteranceStartedAt,
        utteranceEndedAt,
        recognitionCompletedAt,
        audioDurationMs: Math.max(0, utteranceEndedAt - utteranceStartedAt),
        timeUnit: "unix_ms",
        serviceStartedAt,
        streamStartedAt,
        sentences: [{
          sentenceId: "utt_001", index: 0, text,
          startedAt: utteranceStartedAt, endedAt: utteranceEndedAt, words
        }]
      });
      setStatus(`兼容转写完成（${data.timing?.total_elapsed_ms ?? "--"} ms）`, "success");
    } catch (error) {
      setStatus(`转写失败：${error.message || error}`, "error");
    } finally {
      transcribing = false;
      startButton.disabled = false;
    }
  }

  function publishTranscription(text, asrTiming) {
    intentInput.value = text;
    intentInput.dispatchEvent(new Event("input", { bubbles: true }));
    window.dispatchEvent(new CustomEvent("autolab:asr-transcription", {
      detail: { text, asrTiming }
    }));
    intentInput.focus();
  }

  function setupAudioGraph(onAudio) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextClass();
    sourceNode = audioContext.createMediaStreamSource(mediaStream);
    processorNode = audioContext.createScriptProcessor(2048, 1, 1);
    silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    processorNode.onaudioprocess = (event) => {
      onAudio(new Float32Array(event.inputBuffer.getChannelData(0)), audioContext.sampleRate);
    };
    sourceNode.connect(processorNode);
    processorNode.connect(silentGain);
    silentGain.connect(audioContext.destination);
  }

  function updateLegacyStatus() {
    const elapsed = Math.min(LEGACY_MAX_RECORDING_MS, Date.now() - streamStartedAt);
    setStatus(`正在兼容录音 ${(elapsed / 1000).toFixed(1)} 秒，最长30秒`, "recording");
  }

  function setRecordingControls(recording) {
    startButton.hidden = recording;
    stopButton.hidden = !recording;
    stopButton.disabled = false;
  }

  function cleanupAudioGraph() {
    window.clearInterval(legacyTimer);
    window.clearTimeout(legacyTimeout);
    legacyTimer = null;
    legacyTimeout = null;
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

  function closeSocket() {
    if (socket) {
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      if (socket.readyState === WebSocket.OPEN) socket.close();
    }
    socket = null;
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
      for (let sourceIndex = start; sourceIndex < end; sourceIndex += 1) sum += input[sourceIndex];
      output[index] = sum / Math.max(1, end - start);
    }
    return output;
  }

  function encodePcm16(samples) {
    const buffer = new ArrayBuffer(samples.length * 2);
    const view = new DataView(buffer);
    for (let index = 0; index < samples.length; index += 1) {
      const clamped = Math.max(-1, Math.min(1, samples[index]));
      view.setInt16(index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    }
    return buffer;
  }

  function sendRealtimeSamples(samples) {
    const frameSamples = 640; // 40 ms at 16 kHz.
    const merged = new Float32Array(pcmRemainder.length + samples.length);
    merged.set(pcmRemainder, 0);
    merged.set(samples, pcmRemainder.length);
    let offset = 0;
    while (merged.length - offset >= frameSamples) {
      socket.send(encodePcm16(merged.subarray(offset, offset + frameSamples)));
      offset += frameSamples;
    }
    pcmRemainder = merged.slice(offset);
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
    new Uint8Array(buffer, 44).set(new Uint8Array(encodePcm16(samples)));
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
