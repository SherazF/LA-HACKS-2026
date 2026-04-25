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

const offlineBadge = document.createElement("div");
offlineBadge.id = "offline-badge";
offlineBadge.textContent = "System Offline";
chatPanel.appendChild(offlineBadge);

function setStatus(online) {
  statusEl.textContent = online ? "Online" : "Offline";
  statusEl.classList.toggle("offline", !online);
}

function updateOfflineBadge() {
  offlineBadge.classList.toggle("visible", !backendOnline);
}

function setProcessingState(value) {
  isProcessing = value;
  voiceBtn.classList.toggle("thinking", value);
}

function setListeningState(value) {
  isListening = value;
  voiceBtn.classList.toggle("listening", value);
  voiceBtn.classList.toggle("show-wave", value);
}

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  messagesEl.appendChild(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function resizeOverlay() {
  overlay.width = window.innerWidth;
  overlay.height = window.innerHeight;
  drawBoxes(lastDetections);
}

function getRenderedVideoRect() {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
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
      audio: true
    });
    video.srcObject = stream;
    await video.play();
    setStatus(true);
    appendMessage("assistant", "Webcam connected. Ready to analyze your build.");
  } catch (error) {
    setStatus(false);
    appendMessage("assistant", "Offline");
  }
}

function buildFrameDataUrl() {
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

  return bufferCanvas.toDataURL("image/jpeg", 0.82);
}

async function analyzeFrame() {
  if (isProcessing || !video.videoWidth || !video.videoHeight) {
    return;
  }

  const frame = buildFrameDataUrl();
  if (!frame) {
    return;
  }

  setProcessingState(true);
  try {
    const response = await fetch("http://localhost:8000/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: frame })
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

    lastDetections = detections;
    backendOnline = true;
    updateOfflineBadge();
    setStatus(true);
  } catch (error) {
    lastDetections = [];
    const wasOnline = backendOnline;
    backendOnline = false;
    updateOfflineBadge();
    setStatus(false);
    if (wasOnline) {
      appendMessage("assistant", "Offline");
    }
  } finally {
    setProcessingState(false);
  }
}

function setupChat() {
  const send = () => {
    const text = inputEl.value.trim();
    if (!text) {
      return;
    }
    appendMessage("user", text);
    inputEl.value = "";
  };

  sendBtn.addEventListener("click", send);
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      send();
    }
  });
}

function setupVoiceInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    voiceBtn.disabled = true;
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.continuous = false;

  recognition.addEventListener("result", (event) => {
    const transcript = event.results[0][0].transcript.trim();
    if (transcript) {
      inputEl.value = transcript;
      appendMessage("user", transcript);
      inputEl.value = "";
    }
  });

  recognition.addEventListener("error", () => {
    setListeningState(false);
    appendMessage("assistant", "Offline");
    setStatus(false);
  });

  recognition.addEventListener("end", () => {
    setListeningState(false);
  });

  voiceBtn.addEventListener("click", () => {
    setListeningState(true);
    recognition.start();
  });
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
initWebcam();
updateOfflineBadge();
requestAnimationFrame(animateOverlay);
setInterval(analyzeFrame, 3000);
