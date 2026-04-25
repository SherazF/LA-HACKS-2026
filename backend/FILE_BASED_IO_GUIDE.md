# Gemma 4 File-Based Input/Output Guide

## Overview

The modified Gemma 4 model now supports file-based input and output, allowing you to:
- **Input:** Provide prompts via `.txt` files
- **Output:** Receive formatted, step-by-step responses in `.md` files

This is particularly useful for batch processing, complex queries, and generating well-structured documentation.

---

## Directory Structure

After running the application, two directories are automatically created:

```
backend/
├── inputs/          # Place your input .txt files here
└── outputs/         # Model responses are saved here as .md files
```

---

## How to Use

### Step 1: Create Your Input File

1. Navigate to the `inputs/` directory (created automatically on first run)
2. Create a new `.txt` file named `input.txt` with your prompt

**Example `inputs/input.txt`:**
```
Write a step-by-step guide for building a PC. Include:
- CPU selection tips
- GPU recommendations
- RAM requirements
- Motherboard considerations
- Power supply sizing
- Storage configuration
- Assembly process

Format this as a clear, beginner-friendly guide with numbered steps and practical examples.
```

### Step 2: Send Request to the API

Use one of these methods:

#### Option A: HTTP POST (curl)
```bash
curl -X POST "http://localhost:8000/process-file" \
  -H "Content-Type: application/json" \
  -d '{"input_filename": "input.txt"}'
```

#### Option B: HTTP POST (Python)
```python
import requests

response = requests.post(
    "http://localhost:8000/process-file",
    json={"input_filename": "input.txt"}
)

print(response.json())
```

#### Option C: Custom Output Filename
```bash
curl -X POST "http://localhost:8000/process-file" \
  -H "Content-Type: application/json" \
  -d '{"input_filename": "input.txt", "output_filename": "pc_build_guide.md"}'
```

### Step 3: Check the Output

The API returns a response like this:
```json
{
  "success": true,
  "input_file": "inputs/input.txt",
  "output_file": "outputs/output_20260425_143022.md",
  "prompt": "Your input text...",
  "response": "The model's response..."
}
```

Navigate to the `outputs/` directory to find your generated `.md` file.

---

## Output File Format

The generated `.md` files are automatically formatted with:

```markdown
# Generated Output

**Generated:** 2026-04-25 14:30:22  
**Model:** gemma4:e2b

---

## Input Prompt

[Your original prompt]

---

## Response

[Model's formatted response with proper Markdown structure]

---
```

The model is configured to provide responses with:
- ✅ Clear headings (`##`, `###`)
- ✅ Numbered steps for procedures
- ✅ Bullet points for lists
- ✅ Code blocks for commands/code
- ✅ Bold emphasis for key terms
- ✅ Proper spacing and organization

---

## Examples

### Example 1: PC Build Guide
**Input:** `How do I build a PC? Give me a step-by-step guide.`

**Output:** Generated as `output_[timestamp].md` with:
- Introduction
- Component selection guide
- Assembly steps
- Testing procedures
- Troubleshooting tips

### Example 2: Code Documentation
**Input:** `Write documentation for a Python async task queue implementation.`

**Output:** Formatted `.md` with:
- Overview
- Installation instructions
- Usage examples (in code blocks)
- API reference
- Best practices

### Example 3: Troubleshooting Guide
**Input:** `What are common PC issues and how do I fix them?`

**Output:** Comprehensive guide with:
- Common problems listed
- Diagnostic steps
- Solutions (numbered)
- Prevention tips

---

## Running the Application

### Prerequisites
- Python 3.8+
- Ollama running with Gemma 4 model (`gemma4:e2b`)
- Dependencies installed

### Start the Backend Server

```bash
cd backend
python main.py
```

The server starts on `http://localhost:8000` by default.

### Environment Variables

You can customize directories and settings:

```bash
# Custom input/output directories
export INPUT_DIR="custom_inputs"
export OUTPUT_DIR="custom_outputs"

# Ollama connection
export OLLAMA_HOST="localhost"
export OLLAMA_PORT="11434"
export OLLAMA_MODEL="gemma4:e2b"
```

---

## API Endpoints

### 1. Health Check
```
GET /health
```
Returns: `{"ok": true}`

### 2. Process File (NEW)
```
POST /process-file
Content-Type: application/json

{
  "input_filename": "input.txt",
  "output_filename": "optional_custom_name.md"
}
```

**Response:**
```json
{
  "success": true,
  "input_file": "inputs/input.txt",
  "output_file": "outputs/output_20260425_143022.md",
  "prompt": "Your input...",
  "response": "Model's response..."
}
```

### 3. WebSocket (Existing)
```
WS /ws
```
For real-time chat and vision feedback (unchanged)

---

## Tips for Best Results

1. **Clear Prompts:** Be specific and detailed in your input prompts
2. **Request Format:** Ask for numbered steps, bullet points, or code blocks explicitly
3. **Context:** Provide relevant background information
4. **File Naming:** Use descriptive names for output files
5. **Batch Processing:** Create multiple input files with different queries

Example well-structured prompt:
```
Create a comprehensive guide for [topic].

Requirements:
- Use numbered steps (1., 2., 3., etc.)
- Include practical examples
- Add code blocks for technical content
- Use bullet points for important lists
- Format as professional Markdown

Target audience: [specific skill level]
```

---

## Troubleshooting

### "Input file not found"
- Ensure the file exists in the `inputs/` directory
- Check the exact filename (case-sensitive on Linux/Mac)
- Default filename is `input.txt`

### "Model returned empty response"
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check that `gemma4:e2b` is installed: `ollama list`
- Increase timeout if the model is slow: edit `timeout=60.0` in `gemma.py`

### "Could not write output file"
- Ensure the `outputs/` directory exists and is writable
- Check disk space
- Verify file permissions

### Outputs are not well-formatted
- Update the system prompt in `ModelManager.__init__()` if needed
- Add specific format requests to your input prompt
- Try rephrasing with explicit formatting instructions

---

## Advanced Usage

### Process Multiple Files
Create a batch processing script:

```python
import requests
import os

input_dir = "inputs"
for filename in os.listdir(input_dir):
    if filename.endswith(".txt"):
        response = requests.post(
            "http://localhost:8000/process-file",
            json={"input_filename": filename}
        )
        print(f"Processed {filename}: {response.json()['success']}")
```

### Custom Output Directory
Modify `gemma.py` initialization in `api.py`:

```python
model_manager = ModelManager(
    bus,
    ollama_url=ollama_url,
    model_name=OLLAMA_MODEL,
    input_dir="my_inputs",
    output_dir="my_outputs"
)
```

---

## System Prompt

The model uses an enhanced system prompt to ensure quality Markdown output:

```
You are a helpful assistant that provides clear, step-by-step guidance.

IMPORTANT: Format all responses as clean, professional Markdown with:
- Clear headings (## for main sections, ### for subsections)
- Numbered steps for procedures
- Bullet points for lists and details
- Code blocks (```language ... ```) for commands or code
- Bold for important terms (**bold**)
- Proper spacing between sections

Always structure your response to be easy to read and follow, with clear organization and proper Markdown formatting.
```

Customize this in `gemma.py` `__init__()` method to suit your needs.

---

## File Structure

```
LA-HACKS-2026/
├── backend/
│   ├── api.py                      # FastAPI server (updated)
│   ├── gemma.py                    # Model manager (updated with file I/O)
│   ├── main.py                     # Entry point
│   ├── requirements.txt
│   ├── bus.py
│   ├── camera.py
│   ├── chat.py
│   ├── snapshot.py
│   ├── ui.py
│   ├── ws_bridge.py
│   ├── inputs/                     # NEW: Your input .txt files
│   ├── outputs/                    # NEW: Generated .md files
│   └── FILE_BASED_IO_GUIDE.md      # This file
├── frontend/
└── docs/
```

---

## Next Steps

1. ✅ Create your first `input.txt` in the `inputs/` directory
2. ✅ Start the backend: `python main.py`
3. ✅ Call the `/process-file` endpoint
4. ✅ Check `outputs/` for your generated `.md` file
5. ✅ Review and refine your prompts for better results

Happy generating! 🎉
