"""Quick evaluation harness for the vision model.

Runs a scripted multi-turn session against the configured Ollama model, so we
can iterate on prompts and generation options without booting the full
Electron + websocket loop.

Usage on the dev box:
    cd ~/LA-HACKS-2026/backend
    OLLAMA_HOST=localhost OLLAMA_PORT=11434 OLLAMA_MODEL=gemma4:e4b \
        venv/bin/python eval_model.py

You can pass image paths as positional arguments to use real frames (a JPEG
captured from the camera works great). Omitting them falls back to a small
synthetic gray image — useful for sanity checking the conversation loop but
NOT representative of vision quality.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import cv2
import httpx
import numpy as np

# Make sure we resolve sibling modules when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from model.context import ContextManager  # noqa: E402
from model.gemma import GENERATION_OPTIONS, IMAGE_RESOLUTION, JPEG_QUALITY  # noqa: E402


def encode_image(path: Optional[Path]) -> str:
    if path is None:
        frame = np.full((480, 640, 3), 90, dtype=np.uint8)
        cv2.putText(
            frame, "synthetic placeholder", (20, 240),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2,
        )
    else:
        frame = cv2.imread(str(path))
        if frame is None:
            raise SystemExit(f"Could not read image: {path}")
    target_w, target_h = IMAGE_RESOLUTION
    h, w = frame.shape[:2]
    scale = min(target_w / max(w, 1), target_h / max(h, 1))
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    if (new_w, new_h) != (w, h):
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    if not ok:
        raise SystemExit("JPEG encoding failed")
    return base64.b64encode(buf).decode("utf-8")


def load_prompts(prompt_dir: Path) -> tuple[str, str, str, str]:
    return (
        (prompt_dir / "system_prompt.txt").read_text(),
        (prompt_dir / "snapshot_prompt.txt").read_text(),
        (prompt_dir / "initial_request.txt").read_text(),
        (prompt_dir / "known_parts.txt").read_text(),
    )


async def run_turn(
    client: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    messages: list[dict],
    options: dict,
    label: str,
) -> dict:
    print(f"\n=== {label} ===")
    t0 = time.perf_counter()
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": options,
        "think": False,
    }
    resp = await client.post(f"{ollama_url}/api/chat", json=payload, timeout=180.0)
    elapsed = time.perf_counter() - t0
    resp.raise_for_status()
    body = resp.json()
    content = (body.get("message") or {}).get("content", "")
    print(f"[{elapsed:.1f}s] eval_count={body.get('eval_count')} prompt_eval_count={body.get('prompt_eval_count')}")
    print(f"raw content: {content[:500]}")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        print("!!! JSON decode failed; content above")
        return {}
    print("parsed:")
    print(json.dumps(parsed, indent=2))
    return parsed


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="*", type=Path, help="image files to feed in turn order")
    parser.add_argument("--user", default="Hey, I'm starting a new build. I have a Ryzen 7 and a B650 motherboard out on the desk.")
    parser.add_argument(
        "--chat-after",
        action="append",
        default=[],
        metavar="INDEX:TEXT",
        help="Inject a chat message after snapshot turn INDEX. Repeatable. e.g. 2:'where do I plug this in?'",
    )
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "gemma4:e4b"))
    parser.add_argument("--ollama-url", default=f"http://{os.environ.get('OLLAMA_HOST','localhost')}:{os.environ.get('OLLAMA_PORT','11434')}")
    parser.add_argument("--temp", type=float, default=GENERATION_OPTIONS["temperature"])
    parser.add_argument("--top-p", type=float, default=GENERATION_OPTIONS["top_p"])
    parser.add_argument("--num-ctx", type=int, default=GENERATION_OPTIONS["num_ctx"])
    parser.add_argument("--num-predict", type=int, default=GENERATION_OPTIONS["num_predict"])
    parser.add_argument("--baseline", action="store_true", help="Use Ollama defaults (temp 1.0, no options) as a baseline comparison.")
    args = parser.parse_args()

    prompt_dir = Path(__file__).resolve().parent / "model" / "prompts"
    system_tpl, snapshot_prompt, initial_tpl, known_parts = load_prompts(prompt_dir)
    ctx = ContextManager()
    images = [encode_image(p) for p in (args.images or [None])]

    options = {} if args.baseline else {
        **GENERATION_OPTIONS,
        "temperature": args.temp,
        "top_p": args.top_p,
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
    }
    print(f"Model: {args.model}  url: {args.ollama_url}")
    print(f"Options: {options}")
    print(f"Images: {len(images)} (first: {args.images[0] if args.images else 'synthetic'})")

    async with httpx.AsyncClient() as client:
        # Turn 1: initial chat with first image.
        ctx.add_image(images[0])
        ctx.add_message("user", initial_tpl.format(user_input=args.user))
        ctx.is_initialized = True

        formatted = ctx.get_formatted_state()
        system = system_tpl.format(
            known_parts=known_parts,
            milestones=formatted["milestones"],
            parts=formatted["parts"],
            current_objectives=formatted["current_objectives"],
        )
        msgs = ctx.get_messages_payload(system)
        parsed = await run_turn(client, args.ollama_url, args.model, msgs, options, "TURN 1 — initial chat")
        if parsed:
            ctx.update_state(parsed)
            response = (parsed.get("response") or "").strip()
            if response and response.lower() != "empty":
                ctx.add_message("assistant", response)

        chat_after: dict[int, str] = {}
        for entry in args.chat_after:
            idx_s, _, text = entry.partition(":")
            chat_after[int(idx_s)] = text

        for idx, img in enumerate(images[1:], start=2):
            ctx.add_image(img)
            formatted = ctx.get_formatted_state()
            system = system_tpl.format(
                known_parts=known_parts,
                milestones=formatted["milestones"],
                parts=formatted["parts"],
                current_objectives=formatted["current_objectives"],
            )
            msgs = ctx.get_messages_payload(system, transient_user_message=snapshot_prompt)
            parsed = await run_turn(client, args.ollama_url, args.model, msgs, options, f"TURN {idx} — snapshot")
            if parsed:
                ctx.update_state(parsed)
                response = (parsed.get("response") or "").strip()
                if response and response.lower() != "empty":
                    ctx.add_message("assistant", response)

            chat_text = chat_after.get(idx)
            if chat_text:
                ctx.add_message("user", chat_text)
                formatted = ctx.get_formatted_state()
                system = system_tpl.format(
                    known_parts=known_parts,
                    milestones=formatted["milestones"],
                    parts=formatted["parts"],
                    current_objectives=formatted["current_objectives"],
                )
                msgs = ctx.get_messages_payload(system)
                parsed = await run_turn(client, args.ollama_url, args.model, msgs, options, f"TURN {idx}.5 — user chat: {chat_text!r}")
                if parsed:
                    ctx.update_state(parsed)
                    response = (parsed.get("response") or "").strip()
                    if response and response.lower() != "empty":
                        ctx.add_message("assistant", response)


if __name__ == "__main__":
    asyncio.run(main())
