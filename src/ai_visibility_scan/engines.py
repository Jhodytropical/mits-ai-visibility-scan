"""Ask AI assistants a buyer's question the way a customer would, with live web search on.

Each engine returns {"engine", "model", "prompt", "answer", "sources": [{"title", "url"}], "error"}.
API keys come from environment variables (ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY) or, if unset, from
files in the folder named by AIVS_SECRETS_DIR (anthropic_key, gemini_api_key, openai_key). They are read inside this
process and never touch argv, logs or output.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic
import requests

KEYS = {  # key file name -> environment variable
    "anthropic_key": "ANTHROPIC_API_KEY", "gemini_api_key": "GEMINI_API_KEY", "openai_key": "OPENAI_API_KEY"}
ENGINE_KEYS = {"claude": "anthropic_key", "gemini": "gemini_api_key", "chatgpt": "openai_key"}
CLAUDE_MODEL = "claude-opus-5-5"
GEMINI_MODEL = "gemini-flash-latest"   # the alias the consumer-grade Flash tier tracks

# A neutral assistant persona: we want what the model recommends on its own, not what we steer it to.
ASSISTANT_SYSTEM = (
    "You are a helpful assistant. Answer the user's question directly. When the user is looking for a "
    "local business, recommend specific businesses by name if you can find good options."
)


def _key(name: str) -> str:
    value = os.environ.get(KEYS[name], "").strip()
    folder = os.environ.get("AIVS_SECRETS_DIR")
    if not value and folder and (Path(folder).expanduser() / name).is_file():
        value = (Path(folder).expanduser() / name).read_text().strip()
    if not value:
        raise RuntimeError(f"No API key: set {KEYS[name]} (or put a '{name}' file in AIVS_SECRETS_DIR)")
    return value


def available(engine: str) -> bool:
    try:
        _key(ENGINE_KEYS[engine])
        return True
    except RuntimeError:
        return False


def _claude_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=_key("anthropic_key"), max_retries=3)


def ask_claude(prompt: str, city: str, region: str) -> dict:
    out = {"engine": "Claude", "model": CLAUDE_MODEL, "prompt": prompt, "answer": "", "sources": [], "error": None,
           "usage": {"input_tokens": 0, "output_tokens": 0, "web_searches": 0}}
    client = _claude_client()
    messages = [{"role": "user", "content": prompt}]
    tools = [{
        "type": "web_search_20260209", "name": "web_search", "max_uses": 3,
        "user_location": {"type": "approximate", "city": city, "region": region, "country": "US"},
    }]
    try:
        for _ in range(3):                                    # pause_turn: resume the server-side loop
            resp = client.beta.messages.create(
                model=CLAUDE_MODEL, max_tokens=8000, system=ASSISTANT_SYSTEM,
                output_config={"effort": "low"}, tools=tools, messages=messages,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            u = resp.usage
            out["usage"]["input_tokens"] += (u.input_tokens or 0) + (u.cache_read_input_tokens or 0)
            out["usage"]["output_tokens"] += u.output_tokens or 0
            out["usage"]["web_searches"] += getattr(u.server_tool_use, "web_search_requests", 0) or 0
            for block in resp.content:
                if block.type == "text":
                    out["answer"] += block.text
                elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                    out["sources"] += [{"title": r.title, "url": r.url} for r in block.content]
            if resp.stop_reason == "refusal":
                out["error"] = "refused"
                break
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
    except anthropic.APIStatusError as e:
        out["error"] = f"API {e.status_code}"
    except anthropic.APIConnectionError:
        out["error"] = "connection error"
    return out


def ask_gemini(prompt: str, city: str, region: str) -> dict:
    out = {"engine": "Gemini", "model": GEMINI_MODEL, "prompt": prompt, "answer": "", "sources": [], "error": None}
    body = {
        "systemInstruction": {"parts": [{"text": ASSISTANT_SYSTEM + f" The user is in {city}, {region}."}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": _key("gemini_api_key"), "Content-Type": "application/json"},
            data=json.dumps(body), timeout=120,
        )
        if r.status_code != 200:
            out["error"] = f"API {r.status_code}"
            return out
        cand = (r.json().get("candidates") or [{}])[0]
        out["answer"] = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        for chunk in cand.get("groundingMetadata", {}).get("groundingChunks", []):
            web = chunk.get("web") or {}
            out["sources"].append({"title": web.get("title", ""), "url": web.get("uri", "")})
    except requests.RequestException:
        out["error"] = "connection error"
    return out


CHATGPT_MODELS = ("gpt-5.3-chat-latest", "gpt-5.5")   # closest to the ChatGPT app first; fallback if it refuses web search


def ask_chatgpt(prompt: str, city: str, region: str) -> dict:
    """OpenAI Responses API with the hosted web_search tool — the nearest API equivalent of ChatGPT search."""
    out = {"engine": "ChatGPT", "model": CHATGPT_MODELS[0], "prompt": prompt, "answer": "", "sources": [], "error": None,
           "usage": {"input_tokens": 0, "output_tokens": 0, "web_searches": 0}}
    headers = {"Authorization": f"Bearer {_key('openai_key')}", "Content-Type": "application/json"}
    try:
        for model in CHATGPT_MODELS:
            body = {"model": model, "instructions": ASSISTANT_SYSTEM, "input": prompt, "tools": [{
                "type": "web_search",
                "user_location": {"type": "approximate", "city": city, "region": region, "country": "US"}}]}
            r = requests.post("https://api.openai.com/v1/responses", headers=headers, data=json.dumps(body), timeout=180)
            if r.status_code in (400, 404) and model != CHATGPT_MODELS[-1]:
                continue                                       # model refuses the tool or is not on this account: fallback
            if r.status_code != 200:
                out["error"] = f"API {r.status_code}"
                return out
            out["model"] = model
            d = r.json()
            for item in d.get("output", []):
                if item.get("type") == "web_search_call":
                    out["usage"]["web_searches"] += 1
                for c in item.get("content", []) if item.get("type") == "message" else []:
                    if c.get("type") == "output_text":
                        out["answer"] += c.get("text", "")
                        out["sources"] += [{"title": a.get("title", ""), "url": a.get("url", "")}
                                           for a in c.get("annotations", []) if a.get("type") == "url_citation"]
            u = d.get("usage") or {}
            out["usage"]["input_tokens"] += u.get("input_tokens", 0)
            out["usage"]["output_tokens"] += u.get("output_tokens", 0)
            return out
    except requests.RequestException:
        out["error"] = "connection error"
    return out


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "businesses": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["index", "businesses"], "additionalProperties": False,
    }}},
    "required": ["answers"], "additionalProperties": False,
}


def extract_businesses(answers: list[str]) -> list[list[str]]:
    """One call for the whole scan: which businesses does each answer recommend, by name?"""
    numbered = "\n\n".join(f"### Answer {i}\n{a[:6000]}" for i, a in enumerate(answers))
    resp = _claude_client().messages.create(
        model=CLAUDE_MODEL, max_tokens=8000, output_config={
            "effort": "low", "format": {"type": "json_schema", "schema": EXTRACT_SCHEMA}},
        messages=[{"role": "user", "content": (
            "For each answer below, list the specific named businesses it recommends or suggests to the reader, "
            "in the order they appear. Use the business name as written. Exclude directories and platforms "
            "(Yelp, Google, Angi, Thumbtack, BBB, Nextdoor, HomeAdvisor) and generic advice.\n\n" + numbered)}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    by_index = {a["index"]: a["businesses"] for a in json.loads(text).get("answers", [])}
    return [by_index.get(i, []) for i in range(len(answers))]
