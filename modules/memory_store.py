"""Analysis cache and agent reasoning trace persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MEMORY_DIR = Path("memory")
CACHE_PATH = MEMORY_DIR / "analysis_cache.json"
TRACE_PATH = MEMORY_DIR / "agent_traces.jsonl"
CONVERSATION_PATH = MEMORY_DIR / "conversation_memory.json"


class ConversationMemory:
    """Manual chat history store compatible with agent message lists."""

    def __init__(self, messages: list[dict[str, str]] | None = None, max_messages: int = 20):
        self.messages = list(messages or [])
        self.max_messages = max_messages

    def add_user_message(self, content: str) -> None:
        self.add_message("user", content)

    def add_ai_message(self, content: str) -> None:
        self.add_message("assistant", content)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        if self.max_messages > 0:
            self.messages = self.messages[-self.max_messages :]

    def get_all_messages(self) -> list[dict[str, str]]:
        return list(self.messages)


def make_cache_key(agent: str, competitor: str, question: str, top_k: int) -> str:
    raw = json.dumps(
        {"agent": agent, "competitor": competitor, "question": question, "top_k": top_k},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def get_cached_result(key: str) -> dict[str, Any] | None:
    return load_cache().get(key)


def set_cached_result(key: str, value: dict[str, Any]) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    cache[key] = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "value": value,
    }
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def append_trace(entry: dict[str, Any]) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    trace = {"created_at": datetime.now(timezone.utc).isoformat(), **entry}
    with TRACE_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(trace, ensure_ascii=False) + "\n")


def read_traces(limit: int = 50) -> list[dict[str, Any]]:
    if not TRACE_PATH.exists():
        return []
    lines = TRACE_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:]]


def clear_cache() -> dict[str, int]:
    count = len(load_cache())
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
    return {"cleared": count}


def load_conversations() -> dict[str, list[dict[str, str]]]:
    if not CONVERSATION_PATH.exists():
        return {}
    return json.loads(CONVERSATION_PATH.read_text(encoding="utf-8"))


def read_conversation_messages(session_id: str) -> list[dict[str, str]]:
    return load_conversations().get(session_id, [])


def append_conversation_message(session_id: str, role: str, content: str) -> dict[str, Any]:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    conversations = load_conversations()
    memory = ConversationMemory(conversations.get(session_id, []))
    memory.add_message(role, content)
    conversations[session_id] = memory.get_all_messages()
    CONVERSATION_PATH.write_text(json.dumps(conversations, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"session_id": session_id, "messages": conversations[session_id]}


def clear_conversation(session_id: str) -> dict[str, Any]:
    conversations = load_conversations()
    existed = session_id in conversations
    conversations.pop(session_id, None)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATION_PATH.write_text(json.dumps(conversations, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"session_id": session_id, "cleared": existed}
