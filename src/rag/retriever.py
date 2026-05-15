"""
Поиск релевантных чанков по запросу пользователя.
"""
import os

from src.config import logger

from .embeddings import get_embedding_function
from .indexer import CHROMA_PATH, COLLECTION_NAME


class KnowledgeRetriever:
    """Ищет релевантные фрагменты в базе знаний."""

    def __init__(self, chroma_path: str | None = None):
        self.chroma_path = chroma_path or CHROMA_PATH
        self._client = None
        self._collection = None

    def _get_collection(self):
        """Ленивая инициализация."""
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError:
            return None

        if not os.path.exists(self.chroma_path):
            return None

        try:
            self._client = chromadb.PersistentClient(path=self.chroma_path)
            ef = get_embedding_function()
            kwargs = {"name": COLLECTION_NAME}
            if ef:
                kwargs["embedding_function"] = ef
            self._collection = self._client.get_or_create_collection(**kwargs)
            return self._collection
        except Exception as e:
            logger.error(f"RAG retriever init error: {e}")
            return None

    def search(
        self,
        query: str,
        subject: str | None = None,
        top_k: int = 5,
        threshold: float = 0.3,
    ) -> list[dict]:
        """Ищет top_k релевантных чанков.

        Возвращает [{text, source, subject, score}].
        Если score < threshold — чанк не включается.
        """
        collection = self._get_collection()
        if collection is None:
            return []

        try:
            count = collection.count()
            if count == 0:
                return []
        except Exception:
            return []

        try:
            # Фильтр по предмету (если указан и не 'auto')
            where_filter = None
            if subject and subject not in ("auto", "general"):
                where_filter = {"subject": subject}

            results = collection.query(
                query_texts=[query],
                n_results=min(top_k, count),
                where=where_filter,
            )

            if not results or not results.get("documents"):
                return []

            chunks = []
            documents = results["documents"][0]
            metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(documents)
            distances = results["distances"][0] if results.get("distances") else [1.0] * len(documents)

            for i, doc in enumerate(documents):
                # ChromaDB cosine distance: 0 = identical, 2 = opposite
                # Конвертируем в score: 1 - distance/2
                distance = distances[i]
                score = 1.0 - distance / 2.0

                if score >= threshold:
                    meta = metadatas[i] if i < len(metadatas) else {}
                    chunks.append({
                        "text": doc,
                        "source": meta.get("source", ""),
                        "subject": meta.get("subject", "general"),
                        "score": round(score, 3),
                    })

            return chunks

        except Exception as e:
            logger.error(f"RAG search error: {e}")
            return []

    def is_available(self) -> bool:
        """Проверяет, доступна ли база знаний."""
        collection = self._get_collection()
        if collection is None:
            return False
        try:
            return collection.count() > 0
        except Exception:
            return False
