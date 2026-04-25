const video = document.getElementById("webcam");
const overlay = document.getElementById("overlay");
const ctx = overlay.getContext("2d");

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const voiceBtn = document.getElementById("voice-btn");
const statusEl = document.getElementById("status");
const chatPanel = document.getElementById("chat-panel");

let isProcessing = false;
let lastDetections = [];
let isListening = false;
let backendOnline = true;
let lastPulseFrame = 0;
let pendingUserAnalyses = 0;
let cameraUnavailable = false;

const ANALYSIS_TIMEOUT_MS = 45000;

const offlineBadge = document.createElement("div");
offlineBadge.id = "offline-badge";
offlineBadge.textContent = "System Offline";
chatPanel.appendChild(offlineBadge);

function setSystemStatus(online) {
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
}

function setListeningState(value) {
  isListening = value;
  voiceBtn.classList.toggle("listening", value);
  voiceBtn.classList.toggle("show-wave", value);
  voiceBtn.classList.toggle("pulse", value);
  voiceBtn.setAttribute("aria-pressed", String(value));
}

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  messagesEl.appendChild(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function flushPendingUserAnalysis() {
  if (isProcessing || !video.videoWidth || !video.videoHeight || pendingUserAnalyses < 1) {
    return;
  }

  pendingUserAnalyses -= 1;
  analyzeFrame({ userInitiated: true });
}

function getOverlaySize() {
  return {
    width: Math.max(1, Math.round(overlay.offsetWidth || window.innerWidth)),
    height: Math.max(1, Math.round(overlay.offsetHeight || window.innerHeight))
  };
}

function syncOverlayCanvas() {
  const { width, height } = getOverlaySize();
  const pixelRatio = window.devicePixelRatio || 1;
  const targetWidth = Math.round(width * pixelRatio);
  const targetHeight = Math.round(height * pixelRatio);

  if (overlay.width !== targetWidth || overlay.height !== targetHeight) {
    overlay.width = targetWidth;
    overlay.height = targetHeight;
  }

  ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  return { width, height };
}

function resizeOverlay() {
  syncOverlayCanvas();
  drawBoxes(lastDetections);
  flushPendingUserAnalysis();
}

function getRenderedVideoRect(overlayWidth, overlayHeight) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;

  if (!vw || !vh || !overlayWidth || !overlayHeight) {
    return null;
  }

  const scale = Math.max(overlayWidth / vw, overlayHeight / vh);
  const renderWidth = vw * scale;
  const renderHeight = vh * scale;
  const offsetX = (overlayWidth - renderWidth) / 2;
  const offsetY = (overlayHeight - renderHeight) / 2;

  return { offsetX, offsetY, renderWidth, renderHeight };
}

function drawBoxes(detections = []) {
  const { width: overlayWidth, height: overlayHeight } = syncOverlayCanvas();
  ctx.clearRect(0, 0, overlayWidth, overlayHeight);
  if (!detections.length) {
    return;
  }

  const rect = getRenderedVideoRect(overlayWidth, overlayHeight);
  if (!rect) {
    return;
  }

  const { offsetX, offsetY, renderWidth, renderHeight } = rect;
  const scaleX = renderWidth / video.videoWidth;
  const scaleY = renderHeight / video.videoHeight;

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

async function initWebcam() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: false
    });
    video.srcObject = stream;
    await video.play();
    cameraUnavailable = false;
    setSystemStatus(true);
    appendMessage("assistant", "Webcam connected. Ready to analyze your build.");
    flushPendingUserAnalysis();
  } catch (error) {
    cameraUnavailable = true;
    pendingUserAnalyses = 0;
    setSystemStatus(false);
    appendMessage("assistant", "Camera unavailable.");
  }
}

function buildFrameData() {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
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
    height: targetHeight
  };
}

function normalizeDetections(detections, sourceWidth, sourceHeight) {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
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
      height: height * scaleY
    };
  });
}

async function analyzeFrame(options = {}) {
  const { userInitiated = false } = options;

  if (isProcessing) {
    if (userInitiated) {
      pendingUserAnalyses += 1;
    }
    return;
  }

  if (!video.videoWidth || !video.videoHeight) {
    if (userInitiated) {
      if (cameraUnavailable) {
        setSystemStatus(false);
        appendMessage("assistant", "Camera unavailable.");
      } else {
        pendingUserAnalyses += 1;
      }
    }
    return;
  }

  const frame = buildFrameData();
  if (!frame) {
    return;
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), ANALYSIS_TIMEOUT_MS);

  setProcessingState(true);
  try {
    const response = await fetch("http://localhost:8000/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: frame.dataUrl }),
      signal: controller.signal
    });

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
    backendOnline = true;
    updateOfflineBadge();
    setSystemStatus(true);
    drawBoxes(lastDetections);
  } catch (error) {
    lastDetections = [];
    backendOnline = false;
    updateOfflineBadge();
    setSystemStatus(false);
    drawBoxes(lastDetections);
    if (userInitiated) {
      appendMessage("assistant", "System: Offline");
    }
  } finally {
    window.clearTimeout(timeoutId);
    setProcessingState(false);
    flushPendingUserAnalysis();
  }
}

function setupChat() {
  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      sendMessage();
    }
  });
}

function setupVoiceInput() {
  const SpeechRecognitionCtor = window.webkitSpeechRecognition || window.SpeechRecognition;
  if (!SpeechRecognitionCtor) {
    voiceBtn.disabled = true;
    return;
  }

  const recognition = new SpeechRecognitionCtor();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.continuous = false;

  recognition.addEventListener("result", (event) => {
    const transcript = event.results?.[0]?.[0]?.transcript?.trim() || "";
    if (transcript) {
      inputEl.value = transcript;
      sendMessage();
    }
  });

  recognition.addEventListener("error", () => {
    setListeningState(false);
  });

  recognition.addEventListener("end", () => {
    setListeningState(false);
  });

  voiceBtn.addEventListener("click", () => {
    if (isProcessing || isListening) {
      return;
    }
    setListeningState(true);
    try {
      recognition.start();
    } catch (error) {
      setListeningState(false);
    }
  });
}

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) {
    return;
  }
  appendMessage("user", text);
  inputEl.value = "";
  analyzeFrame({ userInitiated: true });
}

function animateOverlay(now) {
  if (now - lastPulseFrame > 16) {
    drawBoxes(lastDetections);
    lastPulseFrame = now;
  }
  requestAnimationFrame(animateOverlay);
}

window.addEventListener("resize", resizeOverlay);
video.addEventListener("loadedmetadata", resizeOverlay);
video.addEventListener("play", resizeOverlay);

setupChat();
setupVoiceInput();
setSystemStatus(true);
setListeningState(false);
initWebcam();
updateOfflineBadge();
requestAnimationFrame(animateOverlay);
setInterval(analyzeFrame, 3000);