"""
Internet access for Ollama (incl. Gemma) via native tool calling.

Exposes a single tool, ``fetch_url``, that performs a bounded HTTP GET
to a public URL. The module runs a multi-round agent loop: model requests
tool(s) -> we execute -> results are sent back to Ollama until the model
returns a normal assistant message without pending tool calls.

Models must support Ollama tool calling; if the model never emits
``tool_calls``, behavior degrades to a single chat completion.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Appended to your app system prompt so the model knows it may call fetch_url
WEB_SYSTEM_SUFFIX = (
    " You may use the fetch_url tool to retrieve public web pages (docs, product pages) "
    "when up-to-date or external information helps; keep answers concise and mention when you used a page."
)

# Ollama /api/chat: max rounds of (model -> tools -> model)
MAX_TOOL_ROUNDS = 8
# Truncate fetched body so context stays reasonable
MAX_FETCH_CHARS = 48_000
HTTP_TIMEOUT = 20.0
MAX_REDIRECTS = 5

# Optional env-style defaults (read at call time in execute layer if you extend this)
_USER_AGENT = "PC-Build-Assistant/1.0 (fetch_url; Ollama tool)"

# JSON Schema tools payload for Ollama
INTERNET_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch and return the text of a public web page. "
                "Input must be a full http:// or https:// URL. "
                "Use for product specs, manuals, documentation, or up-to-date facts. "
                "HTML is reduced to plain text. Large pages are truncated."
            ),
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Absolute URL to retrieve (https preferred).",
                    }
                },
            },
        },
    }
]

_TOOL_NAMES = {t["function"]["name"] for t in INTERNET_TOOLS}


def _rough_html_to_text(html: str) -> str:
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved:
        return True
    if addr.is_private:
        return True
    if addr.version == 4:
        if addr in ipaddress.ip_network("0.0.0.0/8"):
            return True
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return True
    return False


def _is_safe_url(url: str) -> Tuple[bool, str]:
    u = url.strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        return False, f"URL scheme not allowed: {p.scheme!r} (use http or https)"
    if p.hostname is None or p.hostname == "":
        return False, "URL has no host"
    host = p.hostname
    if host.lower() in ("localhost",) or host.endswith(".local"):
        return False, "Local host names are not allowed"
    if host == "0.0.0.0":
        return False, "Refusing 0.0.0.0"
    return True, "ok"


async def _host_ips_safe(hostname: str) -> Tuple[bool, str]:
    def resolve() -> List[str]:
        out: List[str] = []
        for fam, _, _, _, sockaddr in socket.getaddrinfo(
            hostname, None, type=socket.SOCK_STREAM
        ):
            if fam == socket.AF_INET:
                out.append(sockaddr[0])
            elif fam == socket.AF_INET6:
                out.append(sockaddr[0])
        return out

    try:
        ips = await asyncio.get_event_loop().run_in_executor(None, resolve)
    except OSError as e:
        return False, f"DNS / resolve error: {e}"

    if not ips:
        return False, "Could not resolve host"

    for ip in ips:
        if _is_blocked_ip(ip):
            return False, f"Refusing destination IP: {ip}"
    return True, "ok"


async def execute_fetch_url(url: str) -> str:
    ok, reason = _is_safe_url(url)
    if not ok:
        return f"[fetch_url error] {reason}"

    p = urlparse(url)
    assert p.hostname
    safe, reason = await _host_ips_safe(p.hostname)
    if not safe:
        return f"[fetch_url error] {reason}"

    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/json,text/*;q=0.9,*/*;q=0.8"}
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
        ) as client:
            r = await client.get(url, headers=headers)
    except httpx.RequestError as e:
        return f"[fetch_url error] request failed: {e}"
    except Exception as e:  # noqa: BLE001
        return f"[fetch_url error] {e}"

    if r.status_code >= 400:
        return f"[fetch_url error] HTTP {r.status_code}"

    ct = (r.headers.get("content-type") or "").lower().split(";")[0].strip()
    raw = r.text
    if "json" in ct and ("application" in ct or "text" in ct):
        try:
            obj = r.json()
            text = json.dumps(obj, ensure_ascii=False, indent=0)
        except Exception:
            text = raw
    elif "html" in ct or ("text" in ct and "<" in raw[:2000]):
        text = _rough_html_to_text(raw)
    else:
        text = raw

    if len(text) > MAX_FETCH_CHARS:
        text = text[:MAX_FETCH_CHARS] + f"\n\n[truncated to {MAX_FETCH_CHARS} characters]"
    return text or "[empty page]"


def _parse_arguments(raw: Union[str, Dict[str, Any], None]) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        return json.loads(s)
    return {}


def _append_tool_result(
    messages: List[Dict[str, Any]], name: str, content: str, tool_id: Optional[str] = None
) -> None:
    msg: Dict[str, Any] = {
        "role": "tool",
        "content": content,
    }
    if tool_id is not None:
        msg["tool_call_id"] = tool_id
    # Ollama accepts function name for routing in some versions
    msg["name"] = name
    messages.append(msg)


async def _execute_tool_by_name(
    name: str, args: Dict[str, Any]
) -> str:
    if name == "fetch_url":
        u = (args or {}).get("url") or ""
        if not u:
            return "[fetch_url error] missing `url`"
        return await execute_fetch_url(str(u).strip())
    return f"[error] unknown tool: {name}"


def _message_tool_calls(msg: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not msg:
        return []
    tcs = msg.get("tool_calls")
    if not tcs or not isinstance(tcs, list):
        return []
    return tcs


async def chat_with_internet_tools(
    ollama_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    *,
    httpx_timeout: float = 120.0,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> Optional[str]:
    """
    Call Ollama ``/api/chat`` with ``INTERNET_TOOLS``, run tools in a
    loop, and return the final assistant *text* content, or None on failure.

    *messages* should include a ``system`` first message and the conversation
    so far. Do not include duplicate user lines at the end.
    """
    base = ollama_url.rstrip("/")
    ollama_messages: List[Dict[str, Any]] = [m.copy() for m in messages]

    for round_idx in range(max_rounds):
        payload: Dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "tools": INTERNET_TOOLS,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx_timeout) as client:
                response = await client.post(f"{base}/api/chat", json=payload)
        except Exception as e:  # noqa: BLE001
            logger.error("Ollama request failed: %s", e)
            return None

        if response.status_code == 404:
            logger.error("Ollama 404: model %r missing?", model)
            return None
        if not response.is_success:
            logger.error("Ollama error %s: %s", response.status_code, response.text[:500])
            return None

        data = response.json()
        m = data.get("message") or {}
        tcalls = _message_tool_calls(m)

        if not tcalls:
            out = m.get("content")
            if isinstance(out, str) and out.strip():
                return out
            if isinstance(out, str):
                return out
            return None

        ollama_messages.append(m)
        for tc in tcalls:
            fn = tc.get("function") or {}
            name = (fn.get("name") or "").strip()
            tool_id = tc.get("id")
            if name not in _TOOL_NAMES:
                res = f"[error] disallowed tool: {name!r}"
                _append_tool_result(ollama_messages, name or "unknown", res, tool_id)
                continue
            try:
                args = _parse_arguments(fn.get("arguments"))
            except json.JSONDecodeError as e:
                res = f"[error] bad tool arguments: {e}"
                _append_tool_result(ollama_messages, name, res, tool_id)
                continue

            logger.info("Tool call %s(%s) [round %s]", name, args, round_idx)
            res = await _execute_tool_by_name(name, args)
            if len(res) > MAX_FETCH_CHARS:
                res = res[:MAX_FETCH_CHARS] + "…[truncated]"
            _append_tool_result(ollama_messages, name, res, tool_id)

    logger.warning("Stopped after %s tool rounds (max)", max_rounds)
    return None


__all__ = [
    "INTERNET_TOOLS",
    "WEB_SYSTEM_SUFFIX",
    "chat_with_internet_tools",
    "execute_fetch_url",
]
