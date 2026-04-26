const API_BASE = `http://10.42.0.1:8000`;
console.log(API_BASE);

const WS_PATH = "/ws";
const wsUrl = () => {
  const u = new URL(API_BASE);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.pathname = WS_PATH;
  u.search = "";
  u.hash = "";
  return u.toString();
};

const video = document.getElementById("webcam");
const overlay = document.getElementById("overlay");
const ctx = overlay.getContext("2d");
const modelViewCanvas = document.getElementById("model-view-canvas");
const modelViewCtx = modelViewCanvas.getContext("2d");

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const voiceBtn = document.getElementById("voice-btn");
const ttsBtn = document.getElementById("tts-btn");
const modelViewToggle = document.getElementById("model-view-toggle");
const pinnedInstructionEl = document.getElementById("pinned-instruction");
const pinnedInstructionText = pinnedInstructionEl.querySelector(
  ".pinned-instruction-text",
);
const statusEl = document.getElementById("status");
const chatPanel = document.getElementById("chat-panel");
const collapseToggle = document.getElementById("collapse-toggle");
const inputRow = document.getElementById("input-row");

let isProcessing = false;
let lastDetections = [];
let isListening = false;
let backendOnline = false;
let lastPulseFrame = 0;
let hasLoggedOfflineWarning = false;
let socket = null;
let lastObjectUrl = null;
let pingIntervalId = 0;
let reconnectTimer = 0;
let pendingUserAnalyses = 0;

let autoListenEnabled = false;
let waitingForReply = false;
let voiceArmTimer = 0;

let ttsEnabled = false;
let ttsSpeaking = false;

let modelViewEnabled = false;
const lastFrameImage = new Image();
let lastFrameLoaded = false;
const MODEL_VIEW_W = 1024;
const MODEL_VIEW_H = 576;

let chatCollapsed = false;
let latestAssistantText = "";

const ANALYSIS_TIMEOUT_MS = 45000;
const CHAT_INPUT_MAX_HEIGHT = 200;
const VOICE_REARM_DELAY_MS = 350;

const offlineBadge = document.createElement("div");
offlineBadge.id = "offline-badge";
offlineBadge.textContent = "System Offline";
chatPanel.appendChild(offlineBadge);

const listeningIndicatorEl = document.createElement("div");
listeningIndicatorEl.id = "listening-indicator";
listeningIndicatorEl.textContent = "Listening...";
inputRow.insertAdjacentElement("afterend", listeningIndicatorEl);

function feedWidth() {
  if (video.tagName === "IMG") {
    return video.naturalWidth || 0;
  }
  return video.videoWidth || 0;
}

function feedHeight() {
  if (video.tagName === "IMG") {
    return video.naturalHeight || 0;
  }
  return video.videoHeight || 0;
}

function setStatus(online) {
  statusEl.textContent = online ? "System: Standby" : "System: Offline";
  statusEl.classList.toggle("offline", !online);
}

function updateOfflineBadge() {
  offlineBadge.classList.toggle("visible", !backendOnline);
}

function setProcessingState(value) {
  isProcessing = value;
  chatPanel.classList.toggle("loading", value);
  voiceBtn.classList.toggle("thinking", value);
  if (value) {
    voiceBtn.classList.remove("pulse");
  }
}

function refreshVoiceButtonVisuals() {
  voiceBtn.classList.toggle("listening", isListening);
  voiceBtn.classList.toggle("show-wave", isListening);
  voiceBtn.classList.toggle("pulse", isListening);
  voiceBtn.setAttribute(
    "aria-pressed",
    String(autoListenEnabled || isListening),
  );
  if (isListening) {
    voiceBtn.textContent = "🔴";
    voiceBtn.title = "Listening — click to stop the loop";
  } else if (autoListenEnabled && waitingForReply) {
    voiceBtn.textContent = "💬";
    voiceBtn.title = "Waiting for the model — click to stop the loop";
  } else if (autoListenEnabled) {
    voiceBtn.textContent = "🟠";
    voiceBtn.title = "Hands-free voice on — click to stop";
  } else {
    voiceBtn.textContent = "🎤";
    voiceBtn.title = "Click to start hands-free voice";
  }
  listeningIndicatorEl.classList.toggle("visible", isListening);
  listeningIndicatorEl.textContent = isListening
    ? "Listening — speak now"
    : autoListenEnabled && waitingForReply
      ? "Thinking..."
      : "";
}

function setListeningState(value) {
  isListening = Boolean(value);
  refreshVoiceButtonVisuals();
}

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  messagesEl.appendChild(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function autosizeChatInput() {
  inputEl.style.height = "auto";
  const nextHeight = Math.min(inputEl.scrollHeight, CHAT_INPUT_MAX_HEIGHT);
  inputEl.style.height = `${nextHeight}px`;
  inputEl.style.overflowY =
    inputEl.scrollHeight > CHAT_INPUT_MAX_HEIGHT ? "auto" : "hidden";
  inputEl.scrollTop = inputEl.scrollHeight;
}

function resetChatInputHeight() {
  inputEl.style.height = "auto";
  inputEl.style.overflowY = "hidden";
}

function hasOpenSocket() {
  return socket && socket.readyState === WebSocket.OPEN;
}

function updatePinnedInstruction() {
  const shouldShow = chatCollapsed && Boolean(latestAssistantText);
  pinnedInstructionText.textContent = latestAssistantText || "";
  pinnedInstructionEl.classList.toggle("visible", shouldShow);
  pinnedInstructionEl.setAttribute("aria-hidden", String(!shouldShow));
}

function recordAssistantMessage(text) {
  if (!text) {
    return;
  }
  latestAssistantText = text;
  updatePinnedInstruction();
}

function updateCollapseToggle(isCollapsed) {
  chatCollapsed = isCollapsed;
  collapseToggle.setAttribute("aria-expanded", String(!isCollapsed));
  collapseToggle.setAttribute(
    "aria-label",
    isCollapsed ? "Expand chat panel" : "Collapse chat panel",
  );
  collapseToggle.title = isCollapsed
    ? "Expand chat panel"
    : "Collapse chat panel";
  updatePinnedInstruction();
}

function speakResponse(text) {
  if (!ttsEnabled || !text) {
    return;
  }
  if (!("speechSynthesis" in window)) {
    return;
  }
  try {
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1.05;
    utter.pitch = 1.0;
    utter.volume = 1.0;
    ttsSpeaking = true;
    ttsBtn.classList.add("speaking");
    utter.onend = () => {
      ttsSpeaking = false;
      ttsBtn.classList.remove("speaking");
      maybeRearmVoiceAfterReply();
    };
    utter.onerror = () => {
      ttsSpeaking = false;
      ttsBtn.classList.remove("speaking");
      maybeRearmVoiceAfterReply();
    };
    window.speechSynthesis.speak(utter);
  } catch (e) {
    console.warn("TTS failed", e);
    ttsSpeaking = false;
    ttsBtn.classList.remove("speaking");
  }
}

function handleAssistantText(text) {
  appendMessage("assistant", text);
  recordAssistantMessage(text);
  if (ttsEnabled) {
    speakResponse(text);
  } else {
    maybeRearmVoiceAfterReply();
  }
}

function maybeRearmVoiceAfterReply() {
  if (!autoListenEnabled) {
    waitingForReply = false;
    refreshVoiceButtonVisuals();
    return;
  }
  if (ttsSpeaking) {
    return;
  }
  waitingForReply = false;
  if (voiceArmTimer) {
    clearTimeout(voiceArmTimer);
  }
  voiceArmTimer = window.setTimeout(() => {
    voiceArmTimer = 0;
    if (autoListenEnabled && !isListening && !waitingForReply) {
      startAutoListenTurn();
    }
  }, VOICE_REARM_DELAY_MS);
  refreshVoiceButtonVisuals();
}

function startAutoListenTurn() {
  if (!hasOpenSocket()) {
    appendMessage(
      "assistant",
      "Lost connection to the backend voice service.",
    );
    autoListenEnabled = false;
    refreshVoiceButtonVisuals();
    return;
  }
  if (isListening) {
    return;
  }
  socket.send(
    JSON.stringify({ v: 1, type: "voice_start", mode: "auto" }),
  );
}

function stopAutoListen({ silent = false } = {}) {
  autoListenEnabled = false;
  waitingForReply = false;
  if (voiceArmTimer) {
    clearTimeout(voiceArmTimer);
    voiceArmTimer = 0;
  }
  if (hasOpenSocket() && isListening) {
    socket.send(JSON.stringify({ v: 1, type: "voice_stop" }));
  }
  if ("speechSynthesis" in window && ttsSpeaking) {
    window.speechSynthesis.cancel();
    ttsSpeaking = false;
    ttsBtn.classList.remove("speaking");
  }
  if (!silent) {
    setListeningState(false);
  }
  refreshVoiceButtonVisuals();
}

function handleWsText(raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    return;
  }
  const t = msg.type;
  if (t === "pong" || t === "status") {
    if (t === "status" && msg.message && msg.message !== "ready") {
      appendMessage("assistant", msg.message);
    }
    return;
  }
  if (t === "error" && msg.message) {
    appendMessage("assistant", `Error: ${msg.message}`);
    return;
  }
  if (t === "chat_response" && typeof msg.text === "string") {
    handleAssistantText(msg.text);
    return;
  }
  if (t === "vision_result" && typeof msg.text === "string") {
    handleAssistantText(msg.text);
    return;
  }
  if (t === "voice_state") {
    setListeningState(Boolean(msg.listening));
    return;
  }
  if (t === "voice_error" && msg.message) {
    setListeningState(false);
    if (msg.message) {
      appendMessage("assistant", msg.message);
    }
    if (autoListenEnabled) {
      // Common case: brief "no speech" timeout. Re-arm so the user can
      // just keep going without clicking again.
      maybeRearmVoiceAfterReply();
    } else {
      refreshVoiceButtonVisuals();
    }
    return;
  }
  if (t === "voice_transcript" && typeof msg.text === "string") {
    setListeningState(false);
    const transcript = msg.text.trim();
    if (!transcript) {
      if (autoListenEnabled) {
        maybeRearmVoiceAfterReply();
      }
      return;
    }
    if (autoListenEnabled) {
      // Hands-free path: skip the input box, send straight to chat and
      // wait for the model's reply before re-arming the mic.
      waitingForReply = true;
      appendMessage("user", transcript);
      socket.send(
        JSON.stringify({ v: 1, type: "chat", text: transcript }),
      );
      refreshVoiceButtonVisuals();
    } else {
      const currentText = inputEl.value;
      inputEl.value = currentText
        ? `${currentText} ${transcript}`
        : transcript;
      autosizeChatInput();
      sendMessage();
    }
  }
}

function setFeedFromBlob(blob) {
  if (lastObjectUrl) {
    URL.revokeObjectURL(lastObjectUrl);
  }
  lastObjectUrl = URL.createObjectURL(blob);
  video.src = lastObjectUrl;
  lastFrameImage.onload = () => {
    lastFrameLoaded = true;
    if (modelViewEnabled) {
      drawModelView();
    }
  };
  lastFrameImage.src = lastObjectUrl;
}

function resizeModelViewCanvas() {
  modelViewCanvas.width = window.innerWidth;
  modelViewCanvas.height = window.innerHeight;
  if (modelViewEnabled) {
    drawModelView();
  }
}

function drawModelView() {
  const cw = modelViewCanvas.width;
  const ch = modelViewCanvas.height;
  modelViewCtx.fillStyle = "#06080f";
  modelViewCtx.fillRect(0, 0, cw, ch);
  if (!lastFrameLoaded) {
    return;
  }
  const ratio = MODEL_VIEW_W / MODEL_VIEW_H;
  let drawW = cw;
  let drawH = Math.round(cw / ratio);
  if (drawH > ch) {
    drawH = ch;
    drawW = Math.round(ch * ratio);
  }
  const offX = Math.floor((cw - drawW) / 2);
  const offY = Math.floor((ch - drawH) / 2);
  modelViewCtx.imageSmoothingEnabled = true;
  modelViewCtx.imageSmoothingQuality = "low";
  modelViewCtx.drawImage(lastFrameImage, offX, offY, drawW, drawH);
  modelViewCtx.fillStyle = "rgba(0,0,0,0.55)";
  modelViewCtx.fillRect(offX + 12, offY + 12, 220, 26);
  modelViewCtx.fillStyle = "rgba(255,255,255,0.92)";
  modelViewCtx.font =
    "12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  modelViewCtx.fillText(
    `Model view · ${MODEL_VIEW_W}×${MODEL_VIEW_H} JPEG q=88`,
    offX + 22,
    offY + 30,
  );
}

function setModelViewEnabled(enabled) {
  modelViewEnabled = Boolean(enabled);
  document.body.classList.toggle("model-view", modelViewEnabled);
  modelViewToggle.setAttribute("aria-pressed", String(modelViewEnabled));
  modelViewToggle.title = modelViewEnabled
    ? "Hide model view"
    : "Show model view";
  if (modelViewEnabled) {
    drawModelView();
  }
}

function connectWebSocket() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = 0;
  }
  if (pingIntervalId) {
    clearInterval(pingIntervalId);
    pingIntervalId = 0;
  }
  if (socket) {
    try {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      socket.close();
    } catch {
      // ignore
    }
    socket = null;
  }

  try {
    socket = new WebSocket(wsUrl());
  } catch (e) {
    console.error("WebSocket create failed", e);
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    backendOnline = true;
    setStatus(true);
    updateOfflineBadge();
    hasLoggedOfflineWarning = false;
    pingIntervalId = window.setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ v: 1, type: "ping" }));
      }
    }, 25_000);
  };

  socket.onmessage = (event) => {
    if (typeof event.data === "string") {
      handleWsText(event.data);
      return;
    }
    if (event.data instanceof Blob) {
      setFeedFromBlob(event.data);
      backendOnline = true;
      setStatus(true);
      updateOfflineBadge();
      return;
    }
    if (event.data instanceof ArrayBuffer) {
      setFeedFromBlob(new Blob([event.data], { type: "image/jpeg" }));
      backendOnline = true;
      setStatus(true);
      updateOfflineBadge();
    }
  };

  socket.onerror = () => {
    if (!hasLoggedOfflineWarning) {
      console.warn("WebSocket error");
    }
  };

  socket.onclose = () => {
    if (pingIntervalId) {
      clearInterval(pingIntervalId);
      pingIntervalId = 0;
    }
    socket = null;
    backendOnline = false;
    setStatus(false);
    updateOfflineBadge();
    setListeningState(false);
    if (autoListenEnabled) {
      // The loop can't continue without the socket; pause and re-arm on
      // reconnect.
      autoListenEnabled = false;
      refreshVoiceButtonVisuals();
    }
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = 0;
    connectWebSocket();
  }, 2000);
}

function resizeOverlay() {
  overlay.width = window.innerWidth;
  overlay.height = window.innerHeight;
  drawBoxes(lastDetections);
}

function getRenderedVideoRect() {
  const vw = feedWidth();
  const vh = feedHeight();
  const cw = overlay.width;
  const ch = overlay.height;

  if (!vw || !vh || !cw || !ch) {
    return null;
  }

  const scale = Math.max(cw / vw, ch / vh);
  const renderWidth = vw * scale;
  const renderHeight = vh * scale;
  const offsetX = (cw - renderWidth) / 2;
  const offsetY = (ch - renderHeight) / 2;

  return { offsetX, offsetY, renderWidth, renderHeight };
}

function drawBoxes(detections = []) {
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  if (!detections.length) {
    return;
  }

  const rect = getRenderedVideoRect();
  if (!rect) {
    return;
  }

  const w = feedWidth();
  const h = feedHeight();
  const { offsetX, offsetY, renderWidth, renderHeight } = rect;
  const scaleX = renderWidth / w;
  const scaleY = renderHeight / h;

  const t = performance.now() / 1000;
  const pulse = 0.6 + ((Math.sin(t * 3.8) + 1) / 2) * 0.4;
  const alpha = 0.55 + pulse * 0.4;
  const lineWidth = 2 + pulse * 2.4;

  ctx.lineWidth = lineWidth;
  ctx.strokeStyle = `rgba(0, 255, 224, ${alpha})`;
  ctx.shadowBlur = 8 + pulse * 10;
  ctx.shadowColor = `rgba(0, 255, 224, ${Math.min(1, alpha + 0.12)})`;

  for (const item of detections) {
    const x = Number(item.x ?? item.left ?? 0);
    const y = Number(item.y ?? item.top ?? 0);
    const width = Number(item.width ?? item.w ?? 0);
    const height = Number(item.height ?? item.h ?? 0);

    const screenX = offsetX + x * scaleX;
    const screenY = offsetY + y * scaleY;
    const screenW = width * scaleX;
    const screenH = height * scaleY;

    if (screenW > 0 && screenH > 0) {
      ctx.strokeRect(screenX, screenY, screenW, screenH);
    }
  }
}

function buildFrameData() {
  const vw = feedWidth();
  const vh = feedHeight();
  if (!vw || !vh) {
    return null;
  }

  const maxWidth = 1024;
  const targetWidth = Math.min(vw, maxWidth);
  const targetHeight = Math.round((vh / vw) * targetWidth);

  const bufferCanvas = document.createElement("canvas");
  bufferCanvas.width = targetWidth;
  bufferCanvas.height = targetHeight;

  const bufferCtx = bufferCanvas.getContext("2d");
  bufferCtx.drawImage(video, 0, 0, targetWidth, targetHeight);

  return {
    dataUrl: bufferCanvas.toDataURL("image/jpeg", 0.82),
    width: targetWidth,
    height: targetHeight,
  };
}

function normalizeDetections(detections, sourceWidth, sourceHeight) {
  const vw = feedWidth();
  const vh = feedHeight();
  if (!vw || !vh || !sourceWidth || !sourceHeight) {
    return detections;
  }

  const scaleX = vw / sourceWidth;
  const scaleY = vh / sourceHeight;

  return detections.map((item) => {
    const x = Number(item.x ?? item.left ?? 0);
    const y = Number(item.y ?? item.top ?? 0);
    const width = Number(item.width ?? item.w ?? 0);
    const height = Number(item.height ?? item.h ?? 0);

    return {
      ...item,
      x: x * scaleX,
      y: y * scaleY,
      width: width * scaleX,
      height: height * scaleY,
    };
  });
}

function flushPendingUserAnalysis() {
  if (isProcessing || pendingUserAnalyses < 1) {
    return;
  }
  pendingUserAnalyses -= 1;
  queueMicrotask(() => analyzeFrame({ userInitiated: true }));
}

async function analyzeFrame(options = {}) {
  const { userInitiated = false } = options;

  if (isProcessing) {
    if (userInitiated) {
      pendingUserAnalyses += 1;
    }
    return;
  }

  if (!feedWidth() || !feedHeight()) {
    if (userInitiated) {
      pendingUserAnalyses += 1;
    }
    return;
  }

  const frame = buildFrameData();
  if (!frame) {
    return;
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    ANALYSIS_TIMEOUT_MS,
  );

  setProcessingState(true);
  try {
    const response = await fetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: frame.dataUrl }),
      signal: controller.signal,
    });
    hasLoggedOfflineWarning = false;

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const payload = await response.json();
    const detections = Array.isArray(payload.boxes)
      ? payload.boxes
      : Array.isArray(payload.detections)
        ? payload.detections
        : [];

    lastDetections = normalizeDetections(detections, frame.width, frame.height);
    drawBoxes(lastDetections);
  } catch (error) {
    if (error && error.name === "AbortError") {
      lastDetections = [];
    } else {
      if (!hasLoggedOfflineWarning) {
        console.warn("Analyze request failed (HTTP)", error);
        hasLoggedOfflineWarning = true;
      }
      lastDetections = [];
      if (userInitiated) {
        appendMessage("assistant", "System: Offline");
      }
    }
    drawBoxes(lastDetections);
  } finally {
    window.clearTimeout(timeoutId);
    setProcessingState(false);
    flushPendingUserAnalysis();
  }
}

function setupChat() {
  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("input", autosizeChatInput);
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  resetChatInputHeight();
}

function setupCollapseToggle() {
  updateCollapseToggle(false);
  collapseToggle.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const isCollapsed = chatPanel.classList.toggle("collapsed");
    updateCollapseToggle(isCollapsed);
  });
}

function setupVoiceInput() {
  voiceBtn.title = "Click to start hands-free voice";
  voiceBtn.addEventListener("click", (event) => {
    event.preventDefault();
    if (autoListenEnabled || isListening) {
      stopAutoListen();
      return;
    }
    if (!hasOpenSocket()) {
      appendMessage("assistant", "Not connected to backend voice service.");
      return;
    }
    autoListenEnabled = true;
    waitingForReply = false;
    refreshVoiceButtonVisuals();
    startAutoListenTurn();
  });

  voiceBtn.addEventListener("keydown", (event) => {
    if (event.key !== " " && event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    voiceBtn.click();
  });

  window.addEventListener("beforeunload", () => {
    if (hasOpenSocket() && (autoListenEnabled || isListening)) {
      socket.send(JSON.stringify({ v: 1, type: "voice_stop" }));
    }
  });
}

function setupTtsToggle() {
  ttsBtn.addEventListener("click", (event) => {
    event.preventDefault();
    ttsEnabled = !ttsEnabled;
    ttsBtn.setAttribute("aria-pressed", String(ttsEnabled));
    ttsBtn.title = ttsEnabled
      ? "Voice replies on — click to mute"
      : "Toggle text-to-speech for replies";
    if (!ttsEnabled && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      ttsSpeaking = false;
      ttsBtn.classList.remove("speaking");
      // Spoken-reply listener was the gate for re-arm; if user just turned
      // off TTS while a reply was waiting, re-arm now.
      maybeRearmVoiceAfterReply();
    }
  });
}

function setupModelViewToggle() {
  resizeModelViewCanvas();
  modelViewToggle.addEventListener("click", (event) => {
    event.preventDefault();
    setModelViewEnabled(!modelViewEnabled);
  });
}

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) {
    return;
  }
  if (!hasOpenSocket()) {
    appendMessage(
      "assistant",
      "Not connected to the backend. Is the API running on port 8000?",
    );
    return;
  }
  inputEl.value = "";
  resetChatInputHeight();
  appendMessage("user", text);
  socket.send(JSON.stringify({ v: 1, type: "chat", text }));
}

function animateOverlay(now) {
  if (now - lastPulseFrame > 16) {
    drawBoxes(lastDetections);
    lastPulseFrame = now;
  }
  requestAnimationFrame(animateOverlay);
}

window.addEventListener("resize", () => {
  resizeOverlay();
  resizeModelViewCanvas();
});
video.addEventListener("load", resizeOverlay);
video.addEventListener("error", () => {
  setStatus(!!(socket && socket.readyState === WebSocket.OPEN));
});

setupChat();
setupCollapseToggle();
setupVoiceInput();
setupTtsToggle();
setupModelViewToggle();
setStatus(false);
setListeningState(false);
updateOfflineBadge();
connectWebSocket();

const welcome =
  "System initialized. Please describe your current build status or what you're working on to begin.";
appendMessage("assistant", welcome);
recordAssistantMessage(welcome);

requestAnimationFrame(animateOverlay);
setInterval(() => analyzeFrame({ userInitiated: false }), 3000);
