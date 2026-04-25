# Quick Start: File-Based Input/Output

## 1. Verify Setup ✅

After running the app (`python main.py`), check that these directories exist:
- `backend/inputs/` - for your input .txt files
- `backend/outputs/` - for generated .md files

A sample `input.txt` is already provided.

---

## 2. Test the API

### Option A: Use curl
```bash
cd backend
python main.py
```

In another terminal:
```bash
curl -X POST "http://localhost:8000/process-file" \
  -H "Content-Type: application/json" \
  -d '{"input_filename": "input.txt"}'
```

### Option B: Use Python
```python
import requests

# Make sure the backend is running
response = requests.post(
    "http://localhost:8000/process-file",
    json={"input_filename": "input.txt"}
)

print(response.json())
```

---

## 3. Expected Response

```json
{
  "success": true,
  "input_file": "inputs/input.txt",
  "output_file": "outputs/output_20260425_143022.md",
  "prompt": "Write a comprehensive...",
  "response": "# PC Build Guide\n\n## CPU Selection..."
}
```

---

## 4. Check Your Output

Open the file listed in `output_file` to see your formatted `.md` document.

**Location:** `backend/outputs/output_YYYYMMDD_HHMMSS.md`

---

## 5. Create Your Own Input

Edit or create new `.txt` files in `backend/inputs/`:

```
Example: backend/inputs/my_prompt.txt

Then call:
curl -X POST "http://localhost:8000/process-file" \
  -H "Content-Type: application/json" \
  -d '{"input_filename": "my_prompt.txt"}'
```

---

**That's it!** For detailed documentation, see `FILE_BASED_IO_GUIDE.md`.
