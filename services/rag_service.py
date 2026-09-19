import logging
import os
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import get_settings

logger = logging.getLogger("orion_light.rag")

_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50


def _split_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if c.strip()]


class RAGService:
    def __init__(self):
        self._settings = get_settings()
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None

    def _ensure_init(self):
        if self._client is not None:
            return
        chroma_path = self._settings.CHROMA_PATH
        try:
            os.makedirs(chroma_path, exist_ok=True)
        except OSError:
            chroma_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma")
            os.makedirs(chroma_path, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="knowledge",
            metadata={"hnsw:space": "cosine"},
        )

    def ingest_text(self, doc_id: str, text: str, metadata: dict) -> None:
        self._ensure_init()
        chunks = _split_text(text)
        if not chunks:
            return

        ids = [f"{doc_id}__chunk_{i}" for i in range(len(chunks))]
        metas = [{**metadata, "doc_id": doc_id, "chunk_index": i} for i in range(len(chunks))]

        # ChromaDB upserts — safe to re-ingest the same doc_id.
        self._collection.upsert(documents=chunks, ids=ids, metadatas=metas)
        logger.info("Ingested doc_id=%s in %d chunks", doc_id, len(chunks))

    def ingest_file(self, file_path: str, doc_id: str, metadata: dict) -> None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            text = self._read_pdf(file_path)
        else:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        self.ingest_text(doc_id, text, metadata)

    def _read_pdf(self, path: str) -> str:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                pages.append(extracted)
        return "\n".join(pages)

    def query(self, text: str, n_results: int = 5) -> list[dict]:
        self._ensure_init()
        count = self._collection.count()
        if count == 0:
            return []
        actual_n = min(n_results, count)
        results = self._collection.query(query_texts=[text], n_results=actual_n)
        output = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            output.append({"text": doc, "metadata": meta, "score": 1.0 - dist})
        return output

    def delete_document(self, doc_id: str) -> None:
        self._ensure_init()
        results = self._collection.get(where={"doc_id": doc_id})
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
            logger.info("Deleted %d chunks for doc_id=%s", len(ids), doc_id)


rag_service = RAGService()
