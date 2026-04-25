# File-Based I/O Workflow

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    LA HACKS 2026 - File-Based I/O              │
└─────────────────────────────────────────────────────────────────┘

Step 1: User Creates Input
┌──────────────────┐
│  inputs/         │
│  └─ input.txt    │  <- User writes prompt here
│     (readable)   │
└────────┬─────────┘
         │
         │ curl -X POST /process-file \
         │   {"input_filename": "input.txt"}
         │
         ▼
┌──────────────────────────────────────────┐
│   FastAPI Server (/process-file)         │
│   ┌────────────────────────────────────┐ │
│   │ FileProcessRequest Validation      │ │
│   └────────────────┬───────────────────┘ │
│                    │                      │
│                    ▼                      │
│   ┌────────────────────────────────────┐ │
│   │ ModelManager.process_file_input()  │ │
│   └────────────────┬───────────────────┘ │
│                    │                      │
└────────┬───────────┼───────────┬──────────┘
         │           │           │
    ┌────▼───┐   ┌───▼──┐   ┌───▼─────┐
    │ Read   │   │Query │   │ Format  │
    │ File   │   │Model │   │ Output  │
    └────┬───┘   └───┬──┘   └───┬─────┘
         │           │           │
         ▼           ▼           ▼
    Read input  Call Ollama   Format as
    from .txt   Gemma model   Markdown
    with        (60s timeout) with headers
    UTF-8       with system   and metadata
               prompt         
                
         │           │           │
         └───────┬───┴───────┬───┘
                 │
                 ▼
         ┌──────────────────┐
         │ Write to File    │
         ├──────────────────┤
         │ outputs/         │
         │ output_DATETIME  │ <- Generated .md file
         │ .md              │
         └──────────────────┘
                 │
                 ▼
         ┌──────────────────┐
         │ Return JSON      │
         ├──────────────────┤
         │ {                │
         │   success: true, │
         │   output_file: ..│
         │   response: ...  │
         │ }                │
         └──────────────────┘
```

---

## Detailed Workflow

### Phase 1: Initialization
```
ModelManager.__init__()
├─ Create inputs/ directory
├─ Create outputs/ directory
└─ Set enhanced system prompt
   ├─ Markdown formatting instructions
   ├─ Heading structure requirements
   ├─ Step-by-step procedure format
   └─ Code block usage guidelines
```

### Phase 2: File Input
```
User Action:
├─ Create inputs/input.txt (or any .txt file)
└─ Write prompt with specific requirements

read_input_file(filename)
├─ Open file in inputs/ directory
├─ Read UTF-8 encoded text
├─ Strip whitespace
└─ Return content or None
```

### Phase 3: Model Query
```
_query_model_for_file(prompt)
├─ Build API payload
│  ├─ Model: "gemma4:e2b"
│  ├─ System message: Enhanced prompt
│  └─ User message: Your prompt (NO HISTORY)
├─ POST to Ollama /api/chat
├─ 60-second timeout
└─ Extract response text
```

### Phase 4: Output Formatting
```
_format_markdown_output(prompt, response)
├─ Get current timestamp
├─ Create Markdown structure:
│  ├─ # Generated Output (header)
│  ├─ Metadata (Generated time, Model name)
│  ├─ ---
│  ├─ ## Input Prompt
│  ├─ [Your original prompt]
│  ├─ ---
│  ├─ ## Response
│  ├─ [Model's formatted response]
│  └─ Footer with attribution
└─ Return formatted string
```

### Phase 5: File Output
```
write_output_file(content, filename)
├─ If filename is None:
│  └─ Generate: output_YYYYMMDD_HHMMSS.md
├─ Open file in outputs/ directory
├─ Write formatted Markdown
├─ Close file
└─ Return filepath
```

---

## Data Flow Diagram

```
INPUT PIPELINE:
┌────────────┐
│ input.txt  │
│            │
│ "Write a   │
│  guide..." │
└────┬───────┘
     │
     ▼
┌──────────────────┐     ┌─────────────────┐
│ read_input_file()├────▶│ UTF-8 String    │
└──────────────────┘     │ (prompt text)   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────────────────┐
                         │ _query_model_for_file()    │
                         ├─────────────────────────────┤
                         │ System Prompt (formatting)  │
                         │ + Your Prompt               │
                         │ ▼                           │
                         │ Ollama API Call (60s)       │
                         │ ▼                           │
                         │ Model Response (Markdown)   │
                         └────────┬────────────────────┘
                                  │
                                  ▼
                         ┌──────────────────────────────┐
                         │ _format_markdown_output()   │
                         ├──────────────────────────────┤
                         │ + Metadata                   │
                         │ + Input Prompt               │
                         │ + Model Response             │
                         │ + Footer                     │
                         └────────┬─────────────────────┘
                                  │
                                  ▼
                         ┌──────────────────────────────┐
OUTPUT PIPELINE:        │ write_output_file()          │
                        ├──────────────────────────────┤
                        │ Generate timestamp filename  │
                        │ Write to outputs/            │
                        │ Return filepath              │
                        └────────┬─────────────────────┘
                                 │
                                 ▼
                        ┌──────────────────────┐
                        │ output_DATETIME.md   │
                        │                      │
                        │ # Generated Output   │
                        │                      │
                        │ **Generated:** ...   │
                        │ **Model:** gemma4... │
                        │                      │
                        │ ## Input Prompt      │
                        │ [Prompt]             │
                        │                      │
                        │ ## Response          │
                        │ [Formatted Response] │
                        └──────────────────────┘
```

---

## Timeline Example

```
Time    Event
────────────────────────────────────────────────────
00:00   User creates inputs/my_query.txt
00:05   POST /process-file with my_query.txt
        ├─ Read file (instant)
        ├─ Send to Ollama (network latency ~100ms)
        ├─ Model inference (5-30 seconds depending on response length)
        ├─ Format output (instant)
        └─ Write file (instant)
00:35   API returns success + output_20260425_000535.md
00:36   User opens outputs/output_20260425_000535.md
        ✓ Beautifully formatted Markdown guide!
```

---

## System Prompt Flow

```
Your Input Prompt
        │
        ▼
┌─────────────────────────────────────────────────┐
│         ENHANCED SYSTEM PROMPT                   │
│                                                  │
│  "You are a helpful assistant that provides    │
│   clear, step-by-step guidance.                │
│                                                  │
│   Format all responses as Markdown with:        │
│   - Headings (## ###)                           │
│   - Numbered steps (1. 2. 3.)                   │
│   - Bullet points                               │
│   - Code blocks (```language ... ```)           │
│   - Bold emphasis (**text**)                    │
│   - Proper spacing                              │
│   ..."                                          │
└─────────────────────────────────────────────────┘
        │
        ▼
   Your Prompt + System Prompt
        │
        ▼
   OLLAMA GEMMA MODEL
        │
        ▼
   Formatted Output
   ├─ Proper headings
   ├─ Numbered procedures
   ├─ Bullet points
   ├─ Code blocks
   └─ Professional formatting
```

---

## Comparison: WebSocket vs File-Based

```
┌──────────────────┬──────────────────┬──────────────────┐
│   Feature        │   WebSocket      │   File-Based     │
├──────────────────┼──────────────────┼──────────────────┤
│ Input Source     │ Chat messages    │ .txt files       │
│                  │ Camera frames    │                  │
├──────────────────┼──────────────────┼──────────────────┤
│ Output Format    │ WebSocket events │ .md files        │
│                  │ Stream responses │                  │
├──────────────────┼──────────────────┼──────────────────┤
│ Chat History     │ Maintained       │ Not used         │
│                  │ Contextual       │ Clean slate      │
├──────────────────┼──────────────────┼──────────────────┤
│ Processing       │ Real-time        │ Batch           │
│                  │ Interactive      │ Async            │
├──────────────────┼──────────────────┼──────────────────┤
│ Use Case         │ Live assistance  │ Guide generation │
│                  │ Q&A              │ Documentation    │
├──────────────────┼──────────────────┼──────────────────┤
│ Timeout          │ Shorter          │ 60 seconds       │
│                  │ Real-time        │ Complex queries  │
├──────────────────┼──────────────────┼──────────────────┤
│ Format Control   │ System prompt    │ Enhanced prompt  │
│                  │ Basic            │ + Markdown rules │
└──────────────────┴──────────────────┴──────────────────┘

BOTH COEXIST - No conflicts!
```

---

## Key Components

```
┌─────────────────────────────────────────────────┐
│                  ModelManager                    │
├─────────────────────────────────────────────────┤
│ Constructor                                     │
│ ├─ Initialize directories                      │
│ └─ Set enhanced system prompt                  │
│                                                 │
│ File I/O Methods                               │
│ ├─ read_input_file(filename)                   │
│ ├─ write_output_file(content, filename)        │
│ └─ process_file_input(input_fn, output_fn)     │
│                                                 │
│ Query Methods                                  │
│ ├─ _query_model_for_file(prompt)    [NEW]     │
│ ├─ _format_markdown_output(...)      [NEW]     │
│ └─ _query_model(prompt, images)     [EXISTING]│
│                                                 │
│ Existing Methods (Unchanged)                   │
│ ├─ on_snapshot_ready()                         │
│ ├─ on_chat_input()                             │
│ ├─ start()                                     │
│ ├─ _process_chat()                             │
│ ├─ _process_snapshot()                         │
│ ├─ _check_compression()                        │
│ └─ _check_connection()                         │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│                  FastAPI Server                  │
├─────────────────────────────────────────────────┤
│ New Endpoint                                    │
│ └─ POST /process-file                          │
│    ├─ Request: FileProcessRequest              │
│    └─ Response: JSON with success/output_file  │
│                                                 │
│ Existing Endpoints (Unchanged)                 │
│ ├─ GET /health                                 │
│ ├─ POST /analyze                               │
│ └─ WS /ws                                      │
└─────────────────────────────────────────────────┘
```

---

## Request/Response Cycle

```
1. CLIENT REQUEST
   ┌──────────────────────────────────────────┐
   │ POST /process-file                       │
   │ Content-Type: application/json           │
   │                                          │
   │ {                                        │
   │   "input_filename": "input.txt",         │
   │   "output_filename": null                │
   │ }                                        │
   └──────────────────────────────────────────┘
              │
              ▼
2. PROCESSING
   ┌──────────────────────────────────────────┐
   │ ModelManager.process_file_input()        │
   │ ├─ Read inputs/input.txt                 │
   │ ├─ Query Gemma model                     │
   │ ├─ Format as Markdown                    │
   │ └─ Write to outputs/output_[TS].md       │
   └──────────────────────────────────────────┘
              │
              ▼
3. SERVER RESPONSE
   ┌──────────────────────────────────────────┐
   │ 200 OK                                   │
   │ Content-Type: application/json           │
   │                                          │
   │ {                                        │
   │   "success": true,                       │
   │   "input_file": "inputs/input.txt",      │
   │   "output_file": "outputs/output_...md", │
   │   "prompt": "[original prompt text]",    │
   │   "response": "[formatted response]"     │
   │ }                                        │
   └──────────────────────────────────────────┘
              │
              ▼
4. CLIENT ACTION
   └─ Open output file in editor
      └─ Review beautifully formatted guide!
```

---

This workflow provides a clean, efficient, and scalable way to process complex prompts and generate professional-quality documentation using the Gemma 4 model.
