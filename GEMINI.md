# Gemini Project Context: PC Build Guidance AI Assistant

This project is a standalone AI-powered assistant designed to help users assemble PCs. It combines a Python/FastAPI backend for computer vision and AI integration with an Electron-based desktop frontend.

## Project Overview

- **Purpose**: Provides real-time guidance for PC building using vision (OpenCV) and AI (Ollama/Gemma).
- **Architecture**:
    - **Backend (Python/FastAPI)**: Manages camera streams, handles computer vision tasks, communicates with the Ollama API, and serves a WebSocket bridge.
    - **Frontend (Electron/Node.js)**: A desktop application providing a chat interface and a live video feed streamed from the backend.
    - **Communication**: Real-time interaction via WebSockets (JSON for control/chat, Binary for JPEG video frames).
- **Key Technologies**:
    - **Backend**: FastAPI, OpenCV, Uvicorn, Ollama (Gemma model), `httpx`.
    - **Frontend**: Electron, Vanilla JavaScript, CSS.

## Getting Started

### Prerequisites
- **Python 3.10+**
- **Node.js & npm**
- **Ollama**: Must be running locally or accessible via network (defaults to `localhost:11434`).

### Installation
Use the provided `Makefile` to set up both environments:
```bash
make install
```

### Running the Project
You can run the components separately or together:
- **Run Both**: `make run`
- **Backend Only**: `make run-backend` (Starts on `0.0.0.0:8000` by default)
- **Frontend Only**: `make run-frontend`

## Development Context

### Backend Architecture (`/backend`)
- **`api.py`**: The FastAPI application entry point and lifespan management.
- **`bus.py`**: A central `EventBus` for decoupled communication between components (Chat, Model, Snapshot).
- **`ws_bridge.py`**: Manages WebSocket connections and streams JPEG frames to the frontend.
- **`camera.py`**: Wraps OpenCV for thread-safe camera access.
- **`model/gemma.py`**: Handles interaction with the Ollama API.
- **`snapshot.py`**: Periodically captures frames for AI analysis.

### Frontend Architecture (`/frontend`)
- **`main.js`**: Electron main process.
- **`renderer.js`**: Handles WebSocket communication, rendering the video stream, and chat UI logic.
- **`style.css`**: Provides a modern, dark-themed UI for the assistant.

### WebSocket Protocol (v1)
- **Text Frames (JSON)**: Used for `chat`, `chat_response`, `vision_result`, and `status`.
- **Binary Frames**: Raw JPEG bytes for the live camera feed.

### Environment Variables
Key configurations are managed via `.env` in the `backend/` directory:
- `OLLAMA_HOST` / `OLLAMA_PORT`: Ollama connection details.
- `OLLAMA_MODEL`: The model name to use (e.g., `gemma4:e2b`).
- `SNAPSHOT_INTERVAL`: Seconds between automatic vision snapshots.
- `API_PORT`: Port for the FastAPI server (default 8000).

## Testing
- Backend tests are located in `backend/test_*.py`.
- Run backend tests using `pytest` (ensure venv is active).
