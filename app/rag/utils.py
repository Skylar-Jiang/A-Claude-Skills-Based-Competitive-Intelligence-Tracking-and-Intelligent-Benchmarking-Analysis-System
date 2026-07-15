import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

CHUNK_CONFIG_VERSION = "rag-chunk-v1"


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    joined = "|".join(clean_text(part) for part in parts)
    return str(uuid5(NAMESPACE_URL, f"tradepilot:{prefix}:{joined}"))


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def scalar_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    normalized: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            normalized[key] = value
        elif isinstance(value, Path):
            normalized[key] = str(value)
        else:
            normalized[key] = compact_json(value)
    return normalized


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            yield line_number, json.loads(line)


def truncate_for_prompt(text: str, *, limit: int = 1200) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3]}..."
