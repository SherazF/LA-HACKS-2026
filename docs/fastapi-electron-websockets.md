# FastAPI + WebSocket bridge (backend and Electron)

This document is the specification for the Python FastAPI server and the Electron renderer, including the WebSocket protocol, camera streaming choice, and how to run the stack.

## Architecture

- **FastAPI** serves HTTP (`GET /health`, `POST /analyze`) and a **WebSocket** at `/ws`.
- **Ollama** is only contacted from the Python `ModelManager` (HTTP to `OLLAMA_HOST` / `OLLAMA_PORT`); the browser never talks to Ollama directly.
- The **EventBus** (`EventBus` in `backend/bus.py`) is the same integration point as the previous CLI app: `chat_input` → `ModelManager`; `chat_response` / `vision_result` out to the UI.

## Product choice: camera (Option A)

We use **Option A**: the main video shown in the UI is the **stream from the backend** (OpenCV `CameraStream` → JPEG over WebSocket binary frames), not the browser `getUserMedia` path. The Electron `renderer` uses an `<img>` element updated from those frames. This avoids desync between analysis and display.

- If the backend camera is unavailable, the image area stays empty or shows a prior frame; **chat and Ollama** can still work when WS is up.

## WebSocket protocol (version 1)

All **control** messages use **text** WebSocket frames containing JSON. **Video** uses **binary** frames (raw JPEG bytes).

### Client → server (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `v` | int | Protocol version; must be `1` |
| `type` | string | Message type |

Message types:

- **`ping`**: keepalive. Server responds with a JSON `pong` (text).
- **`chat`**: `{"v":1,"type":"chat","text":"<user message>"}`. Emits `chat_input` on the bus (same as the old console `ChatManager`).

### Server → client (JSON)

| `type` | Description |
|--------|-------------|
| `pong` | Response to `ping` |
| `error` | `{"v":1,"type":"error","message":"..."}` |
| `status` | `{"v":1,"type":"status","ollama":true\|false,"message":"..."}` (e.g. after startup) |
| `chat_response` | `{"v":1,"type":"chat_response","text":"..."}` — assistant text from Ollama |
| `vision_result` | `{"v":1,"type":"vision_result","text":"..."}` — from snapshot/vision analysis |

### Server → client (binary)

- **Raw JPEG** bytes (repeated, ~10–12 FPS by default). The renderer sets these as a `Blob` URL on the `<img>` for the main feed.

**Note:** If no client is connected, the server does not need to keep sending frames; the implementation broadcasts only while at least one WebSocket is in the `ConnectionManager` set, or always encodes in a task that no-ops when empty (this implementation only sends when there are active connections to reduce load).

## HTTP API

- **`GET /health`**: `{"ok": true}`
- **`POST /analyze`**: `Content-Type: application/json`, body `{ "image": "<data URL or base64 string>" }`.  
  - Response: `{ "boxes": [] }` (placeholder). Safe for the existing `renderer.js` `analyzeFrame` path until a real detector is added.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `localhost` | Ollama host |
| `OLLAMA_PORT` | `11434` | Ollama port |
| `OLLAMA_MODEL` | (see `main.py`) | Model name |
| `CAMERA_INDEX` | `0` | OpenCV index |
| `SNAPSHOT_INTERVAL` | `15.0` | Seconds between automatic snapshots to the model |
| `ENABLE_CONSOLE_CHAT` | `0` | If `1`, stdin chat runs (legacy). Default off for API mode. |
| `ENABLE_OPENCV_UI` | `0` | If `1`, OpenCV window UI runs. Default off. |
| `API_HOST` | `0.0.0.0` | Bind host for Uvicorn |
| `API_PORT` | `8000` | Bind port for Uvicorn |
| `CAMERA_STREAM_FPS` | `12` | Max backend→client stream rate |

## Runbook

1. **Ollama** (local or remote): e.g. `ollama serve` on the same machine, or use `OLLAMA_HOST` / `OLLAMA_PORT` for a LAN address.
2. **Backend** (from `backend/` with venv activated):
   - `uvicorn api:app --host 0.0.0.0 --port 8000`  
   - Or: `python main.py` (starts the same app via Uvicorn).
3. **Electron** (from `frontend/`):
   - `npm start` (or your `package.json` start script).
4. **Verify**  
   - Open DevTools in Electron: WebSocket to `ws://127.0.0.1:8000/ws` should be open.  
   - Send a chat line; responses should appear as `chat_response` and in the panel.  
   - Confirm Ollama is only called from the backend (Python process).

## Risks and follow-ups

- **No camera / OpenCV fail**: The UI can still use chat; snapshots may be skipped until a frame is available.
- **Streaming Ollama tokens**: The current `ModelManager` uses `stream: false`. Token streaming can be added later and forwarded as a new `type` in JSON.

## File map

| File | Role |
|------|------|
| `backend/api.py` | FastAPI app, lifespan, routes |
| `backend/ws_bridge.py` | `ConnectionManager`, WebSocket handler, bus subscribers, stream task |
| `backend/main.py` | Optional CLI: launches Uvicorn |
| `backend/chat.py` | Console chat (only if `ENABLE_CONSOLE_CHAT=1`) |
| `frontend/renderer.js` | WS client, `img` for backend video, `POST /analyze` for boxes stub |
