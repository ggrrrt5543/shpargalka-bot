"""
Генерация эмбеддингов для RAG.

Приоритет:
1. Qwen API (OpenAI-совместимый endpoint) — если поддерживает embeddings
2. sentence-transformers (локально) — fallback
3. ChromaDB default (all-MiniLM-L6-v2) — если ничего не установлено
"""
import os
from typing import Callable

from src.config import QWEN_API_KEY, QWEN_API_URL, logger

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")


def get_embedding_function() -> Callable | None:
    """Возвращает функцию эмбеддингов для ChromaDB или None (default)."""

    # Попытка 1: sentence-transformers (локально, надёжно)
    try:
        from chromadb.utils import embedding_functions

        # Используем встроенную в ChromaDB функцию (скачает модель при первом запуске)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        logger.info("RAG: используем SentenceTransformer embeddings (all-MiniLM-L6-v2)")
        return ef
    except Exception as e:
        logger.warning(f"RAG: SentenceTransformer недоступен: {e}")

    # Попытка 2: OpenAI-совместимый API (Qwen)
    if QWEN_API_KEY and QWEN_API_URL:
        try:
            from chromadb.utils import embedding_functions

            ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=QWEN_API_KEY,
                api_base=QWEN_API_URL,
                model_name=EMBEDDING_MODEL,
            )
            logger.info(f"RAG: используем Qwen API embeddings ({EMBEDDING_MODEL})")
            return ef
        except Exception as e:
            logger.warning(f"RAG: Qwen embeddings недоступны: {e}")

    # Fallback: ChromaDB default
    logger.info("RAG: используем ChromaDB default embeddings")
    return None
