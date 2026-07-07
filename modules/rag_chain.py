"""Traceable RAG pipeline backed by a persistent Chroma vector store."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

from modules.data_loader import IntelligenceRecord, load_project_records

INDEX_PATH = Path("data/processed/rag_index.json")
CHROMA_DIR = Path("chroma_db")
COLLECTION_NAME = "competitor_intelligence"
CHUNK_SIZE = 700
CHUNK_OVERLAP = 120
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"


@dataclass
class EvidenceChunk:
    chunk_id: str
    record_id: str
    title: str
    text: str
    source_url: str
    competitor: str
    dimension: str
    collected_at: str


class HuggingFaceEmbeddingFunction(EmbeddingFunction[Documents]):
    """Chroma adapter around LangChain HuggingFaceEmbeddings."""

    def __init__(
        self,
        model_name: str,
        device: str = "cpu",
        normalize_embeddings: bool = True,
    ):
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            raise RuntimeError(
                "Hugging Face RAG requires langchain-huggingface and sentence-transformers. "
                "Install project dependencies with `python -m pip install -r requirements.txt`."
            ) from exc

        self.embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": normalize_embeddings},
        )

    def __call__(self, input: Documents) -> Embeddings:
        return self.embeddings.embed_documents(list(input))

    @staticmethod
    def name() -> str:
        return "huggingface"

    def embed_query(self, input: Documents | str) -> Embeddings:
        texts = input if isinstance(input, list) else [input]
        return self.embeddings.embed_documents(list(texts))


def get_embedding_settings(env: dict[str, str] | None = None) -> dict[str, object]:
    env = env or os.environ
    endpoint = env.get("HF_ENDPOINT", DEFAULT_HF_ENDPOINT).strip()
    if endpoint:
        os.environ.setdefault("HF_ENDPOINT", endpoint)
    normalize = env.get("RAG_NORMALIZE_EMBEDDINGS", "true").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "provider": "huggingface",
        "model_name": env.get("RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL,
        "device": env.get("RAG_EMBEDDING_DEVICE", "cpu").strip() or "cpu",
        "normalize_embeddings": normalize,
        "hf_endpoint": endpoint,
    }


def collection_name_for(settings: dict[str, object]) -> str:
    model_slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(settings["model_name"])).strip("_").lower()
    return f"{COLLECTION_NAME}_{model_slug}"


def create_embedding_function() -> HuggingFaceEmbeddingFunction:
    settings = get_embedding_settings()
    return HuggingFaceEmbeddingFunction(
        model_name=str(settings["model_name"]),
        device=str(settings["device"]),
        normalize_embeddings=bool(settings["normalize_embeddings"]),
    )


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be larger than overlap")
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


def records_to_chunks(records: Sequence[IntelligenceRecord]) -> list[EvidenceChunk]:
    chunks: list[EvidenceChunk] = []
    for record in records:
        for idx, text in enumerate(split_text(record.content)):
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"{record.record_id}-{idx}",
                    record_id=record.record_id,
                    title=record.title,
                    text=text,
                    source_url=record.source_url,
                    competitor=record.competitor,
                    dimension=record.dimension,
                    collected_at=record.collected_at,
                )
            )
    return chunks


class ChromaRAGIndex:
    """Fixed chain: clean records -> chunks -> Chroma vectors -> evidence snippets."""

    def __init__(self, chunks: list[EvidenceChunk] | None = None):
        self.chunks = chunks or []
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.embedding_settings = get_embedding_settings()
        self.collection = self.client.get_or_create_collection(
            name=collection_name_for(self.embedding_settings),
            embedding_function=create_embedding_function(),
            metadata={
                "description": "Traceable competitor intelligence chunks",
                "embedding_provider": str(self.embedding_settings["provider"]),
                "embedding_model": str(self.embedding_settings["model_name"]),
            },
        )

    @classmethod
    def from_records(cls, records: list[IntelligenceRecord]) -> "ChromaRAGIndex":
        return cls(records_to_chunks(records))

    @classmethod
    def load(cls, path: str | Path = INDEX_PATH) -> "ChromaRAGIndex":
        index_path = Path(path)
        if index_path.exists():
            data = json.loads(index_path.read_text(encoding="utf-8"))
            return cls([EvidenceChunk(**item) for item in data])
        return cls.from_records(load_project_records())

    def persist(self, path: str | Path = INDEX_PATH) -> Path:
        index_path = Path(path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps([asdict(chunk) for chunk in self.chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        existing = self.collection.get(include=[])
        if existing.get("ids"):
            self.collection.delete(ids=existing["ids"])

        if self.chunks:
            self.collection.add(
                ids=[chunk.chunk_id for chunk in self.chunks],
                documents=[chunk.text for chunk in self.chunks],
                metadatas=[
                    {
                        "record_id": chunk.record_id,
                        "title": chunk.title,
                        "source_url": chunk.source_url,
                        "competitor": chunk.competitor,
                        "dimension": chunk.dimension,
                        "collected_at": chunk.collected_at,
                    }
                    for chunk in self.chunks
                ],
            )
        return index_path

    def search(
        self,
        query: str,
        top_k: int = 5,
        dimension: str | None = None,
        competitor: str | None = None,
    ) -> list[EvidenceChunk]:
        results = self.collection.query(query_texts=[query], n_results=max(top_k * 5, top_k))
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        chunks = []
        for chunk_id, text, metadata in zip(ids, documents, metadatas):
            if dimension and metadata.get("dimension") not in {dimension, "general", ""}:
                continue
            if competitor and metadata.get("competitor") != competitor:
                continue
            chunks.append(
                EvidenceChunk(
                    chunk_id=chunk_id,
                    record_id=metadata.get("record_id", ""),
                    title=metadata.get("title", ""),
                    text=text,
                    source_url=metadata.get("source_url", ""),
                    competitor=metadata.get("competitor", ""),
                    dimension=metadata.get("dimension", ""),
                    collected_at=metadata.get("collected_at", ""),
                )
            )
        fallback = self._keyword_fallback(query=query, top_k=top_k, dimension=dimension, competitor=competitor)
        by_id = {chunk.chunk_id: chunk for chunk in chunks + fallback}
        return list(by_id.values())[:top_k]

    def _keyword_fallback(
        self,
        query: str,
        top_k: int,
        dimension: str | None,
        competitor: str | None,
    ) -> list[EvidenceChunk]:
        query_tokens = tokenize(query)
        scored = []
        for chunk in self.chunks:
            if dimension and chunk.dimension not in {dimension, "general", ""}:
                continue
            if competitor and chunk.competitor != competitor:
                continue
            chunk_tokens = tokenize(" ".join([chunk.title, chunk.text, chunk.competitor, chunk.dimension]))
            overlap = len(query_tokens & chunk_tokens)
            if overlap:
                competitor_boost = 2.0 if competitor and chunk.competitor == competitor else 0.0
                scored.append((competitor_boost + overlap / math.sqrt(max(len(chunk_tokens), 1)), chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]


SimpleRAGIndex = ChromaRAGIndex


def build_project_index() -> ChromaRAGIndex:
    index = ChromaRAGIndex.from_records(load_project_records())
    index.persist()
    return index
