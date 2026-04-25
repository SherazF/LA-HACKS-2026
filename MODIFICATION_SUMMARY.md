# Project Modification Summary: File-Based Input/Output for Gemma 4

## Overview
The LA HACKS 2026 project has been successfully modified to support file-based input and output for the Gemma 4 model. Users can now:
- **Provide prompts** via `.txt` files in the `inputs/` directory
- **Receive responses** as professionally formatted `.md` files in the `outputs/` directory
- **Ensure consistent, high-quality formatting** with an improved system prompt

---

## Files Modified

### 1. **backend/gemma.py** ✏️ (MAIN CHANGES)

**Added Imports:**
- `os` - for file path operations
- `datetime` - for timestamped filenames

**Constructor Changes:**
- Added `input_dir` parameter (default: `"inputs"`)
- Added `output_dir` parameter (default: `"outputs"`)
- Auto-creates both directories on initialization
- **Enhanced system prompt** for better Markdown formatting:
  - Instructs model to use headings, numbered steps, bullet points
  - Requests code blocks for technical content
  - Emphasizes clean, professional formatting

**New Methods Added:**

1. **`read_input_file(filename: str)`**
   - Reads prompt text from `.txt` file in `inputs/` directory
   - Returns content as string or None if error
   - Handles file not found and empty file cases gracefully

2. **`write_output_file(content: str, filename: Optional[str])`**
   - Writes formatted response to `.md` file in `outputs/` directory
   - Auto-generates timestamped filename if not provided
   - Format: `output_YYYYMMDD_HHMMSS.md`
   - Returns filepath on success, None on failure

3. **`process_file_input(input_filename: str, output_filename: Optional[str])`** ⭐
   - Main orchestration method for file-based processing
   - Reads input → Queries model → Formats output → Writes file
   - Returns JSON with success status and file paths

4. **`_format_markdown_output(prompt: str, response: str)`**
   - Wraps response with metadata (timestamp, model name)
   - Includes input prompt for reference
   - Creates clean, professional `.md` document

5. **`_query_model_for_file(prompt: str)`**
   - Queries model without chat history
   - Clean, isolated inference for file-based requests
   - 60-second timeout for complex queries

**Existing Methods:**
- All existing methods (`_process_chat`, `_process_snapshot`, `_query_model`, etc.) remain unchanged
- Backward compatible with WebSocket and camera-based workflows

---

### 2. **backend/api.py** ✏️ (API ENDPOINT)

**Import Changes:**
- Added `Optional` to typing imports for type hints

**New Model Class:**
```python
class FileProcessRequest(BaseModel):
    input_filename: str = Field(default="input.txt")
    output_filename: Optional[str] = Field(default=None)
```

**New API Endpoint:**

```
POST /process-file
```

**Request Body:**
```json
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
  "prompt": "Your input text...",
  "response": "The model's formatted response..."
}
```

---

## New Directories Created

```
backend/
├── inputs/                 # NEW: Place input .txt files here
│   └── input.txt          # Sample input file (provided)
├── outputs/               # NEW: Generated .md files saved here
```

---

## New Documentation Files

### 1. **backend/FILE_BASED_IO_GUIDE.md** 📖
Comprehensive guide covering:
- Overview and use cases
- Directory structure
- Step-by-step usage instructions
- Multiple examples (PC builds, code documentation, troubleshooting)
- API endpoint documentation
- Tips for best results
- Troubleshooting section
- Advanced usage patterns

### 2. **backend/QUICK_START.md** ⚡
Quick reference guide with:
- Setup verification
- Testing with curl and Python
- Expected response format
- How to create custom input files

### 3. **backend/MODIFICATION_SUMMARY.md** (This file)
Complete documentation of all changes

---

## How to Use

### Quick Start (3 Steps)

**Step 1: Start the Backend**
```bash
cd backend
python main.py
```

**Step 2: Create Input (Optional)**
An example `inputs/input.txt` is provided. Or create your own prompt:
```
backend/inputs/your_prompt.txt
```

**Step 3: Process the File**
```bash
curl -X POST "http://localhost:8000/process-file" \
  -H "Content-Type: application/json" \
  -d '{"input_filename": "input.txt"}'
```

**Step 4: Check Output**
Your formatted response is in `backend/outputs/output_YYYYMMDD_HHMMSS.md`

---

## Response Quality Improvements

### Enhanced System Prompt
The Gemma 4 model now receives explicit formatting instructions:

**Key Instructions:**
- Use `##` for main section headings
- Use `###` for subsections
- Use numbered steps (1., 2., 3.) for procedures
- Use bullet points for lists
- Use code blocks (```language ... ```) for code/commands
- Use bold (**text**) for important terms
- Maintain proper spacing between sections

**Result:** Consistently well-formatted, professional Markdown output

---

## File-Based vs. WebSocket Processing

| Aspect | File-Based | WebSocket |
|--------|-----------|-----------|
| **Purpose** | Batch processing, complex queries | Real-time chat, vision feedback |
| **Input** | `.txt` files | Chat messages, camera frames |
| **Output** | `.md` files | WebSocket events |
| **History** | No chat history | Full chat history maintained |
| **Use Case** | Guides, documentation | Interactive assistance |
| **Performance** | 60-second timeout | Real-time |

**Both modes coexist** - WebSocket functionality is unchanged!

---

## Directory Structure (Updated)

```
LA-HACKS-2026/
├── backend/
│   ├── api.py                           # ✏️ Updated with /process-file endpoint
│   ├── gemma.py                         # ✏️ Updated with file I/O methods
│   ├── main.py                          # Unchanged
│   ├── requirements.txt                 # Unchanged
│   ├── bus.py                           # Unchanged
│   ├── camera.py                        # Unchanged
│   ├── chat.py                          # Unchanged
│   ├── snapshot.py                      # Unchanged
│   ├── ui.py                            # Unchanged
│   ├── ws_bridge.py                     # Unchanged
│   ├── test_bus.py                      # Unchanged
│   ├── test_priority.py                 # Unchanged
│   │
│   ├── inputs/                          # 📁 NEW
│   │   └── input.txt                    # Sample prompt (provided)
│   │
│   ├── outputs/                         # 📁 NEW
│   │   └── (generated .md files here)
│   │
│   ├── QUICK_START.md                   # 📖 NEW: Quick reference
│   ├── FILE_BASED_IO_GUIDE.md           # 📖 NEW: Complete guide
│   └── MODIFICATION_SUMMARY.md          # 📖 NEW: This file
│
├── frontend/
│   ├── index.html
│   ├── main.js
│   ├── renderer.js
│   ├── style.css
│   └── package.json
│
└── docs/
    └── fastapi-electron-websockets.md
```

---

## Examples

### Example 1: PC Build Guide
**Input:** `inputs/input.txt` (provided sample)
```
Write a comprehensive step-by-step guide for building a PC for gaming...
```

**Output:** `outputs/output_20260425_143022.md`
```markdown
# Generated Output

**Generated:** 2026-04-25 14:30:22  
**Model:** gemma4:e2b

---

## Input Prompt

Write a comprehensive step-by-step guide...

---

## Response

## PC Build Guide

### 1. CPU Selection
- Determine your budget...
- Consider core count...

### 2. GPU Recommendations
- Budget option: RTX 4060...
- Mid-range: RTX 4070...

### 3. Assembly Process

**Step 1:** Prepare your workspace
- Static-free mat
- Ground yourself
...

**Step 2:** Install power supply
```bash
# Secure PSU in case
```

...
```

### Example 2: Custom Query
**Create:** `inputs/database_question.txt`
```
Explain database indexing strategies. Include:
- B-tree indexes
- Hash indexes
- Full-text search
Format as a technical guide for developers.
```

**Call:**
```bash
curl -X POST "http://localhost:8000/process-file" \
  -H "Content-Type: application/json" \
  -d '{"input_filename": "database_question.txt", "output_filename": "database_guide.md"}'
```

**Result:** `outputs/database_guide.md` with formatted technical guide

---

## Environment Variables (Optional)

Customize directories without code changes:

```bash
# Use different directory names
export INPUT_DIR="my_inputs"
export OUTPUT_DIR="my_outputs"
```

Modify `api.py` ModelManager initialization to use these variables:
```python
model_manager = ModelManager(
    bus,
    ollama_url=ollama_url,
    model_name=OLLAMA_MODEL,
    input_dir=os.getenv("INPUT_DIR", "inputs"),
    output_dir=os.getenv("OUTPUT_DIR", "outputs")
)
```

---

## Backward Compatibility

✅ **All existing features are preserved:**
- WebSocket connectivity unchanged
- Camera snapshot processing works as before
- Chat management unaffected
- Console chat still functional
- OpenCV UI integration intact
- Event bus architecture maintained

**No breaking changes** - the project works exactly as before, with new file-based capabilities added.

---

## Testing Checklist

- [ ] Backend starts: `python main.py`
- [ ] Health endpoint works: `curl http://localhost:8000/health`
- [ ] Ollama connection successful (check logs)
- [ ] `inputs/` directory exists
- [ ] `outputs/` directory exists
- [ ] Sample `input.txt` file is readable
- [ ] `/process-file` endpoint returns success
- [ ] Output `.md` file is created
- [ ] Output file has proper Markdown formatting
- [ ] Model response includes headings, bullets, code blocks

---

## Troubleshooting

**"Input file not found"**
- Check exact filename (case-sensitive)
- Ensure file is in `backend/inputs/` directory
- Default is `input.txt`

**"Model returned empty response"**
- Verify Ollama is running
- Check model is available: `ollama list`
- Increase timeout in `gemma.py` if needed

**"Could not write output file"**
- Ensure `backend/outputs/` directory exists and is writable
- Check disk space
- Verify file permissions

**Output not well-formatted**
- Review system prompt in `gemma.py` `__init__()` method
- Enhance your input prompt with formatting requests
- Add examples in your query

---

## Next Steps

1. ✅ Read `QUICK_START.md` for immediate usage
2. ✅ Review `FILE_BASED_IO_GUIDE.md` for detailed documentation
3. ✅ Test with the provided `input.txt` sample
4. ✅ Create custom prompts for your use cases
5. ✅ Integrate into your workflow

---

## Support Resources

- **Quick Start:** `backend/QUICK_START.md`
- **Full Guide:** `backend/FILE_BASED_IO_GUIDE.md`
- **API Docs:** In this file
- **Code:** `backend/gemma.py` and `backend/api.py`

---

**Happy coding!** 🚀

For questions, refer to the documentation files or review the source code comments.
