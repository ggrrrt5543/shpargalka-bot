"""
Индексация документов из базы знаний в ChromaDB.

Поддерживаемые форматы: .pdf, .md, .txt
Документы разбиваются на чанки с перекрытием.
"""
import os
from pathlib import Path

from src.config import logger

from .embeddings import get_embedding_function

CHROMA_PATH = os.path.join("data", "chromadb")
COLLECTION_NAME = "knowledge_base"


class KnowledgeIndexer:
    """Парсит документы и индексирует в ChromaDB."""

    def __init__(self, kb_path: str, chroma_path: str | None = None):
        self.kb_path = Path(kb_path)
        self.chroma_path = chroma_path or CHROMA_PATH
        self._client = None
        self._collection = None

    def _get_collection(self):
        """Ленивая инициализация ChromaDB."""
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError:
            logger.error("RAG: chromadb не установлен. pip install chromadb")
            return None

        os.makedirs(self.chroma_path, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self.chroma_path)

        ef = get_embedding_function()
        kwargs = {"name": COLLECTION_NAME, "metadata": {"hnsw:space": "cosine"}}
        if ef:
            kwargs["embedding_function"] = ef

        self._collection = self._client.get_or_create_collection(**kwargs)
        return self._collection

    def index_all(self) -> dict:
        """Полная переиндексация. Возвращает {files: N, chunks: N}."""
        collection = self._get_collection()
        if collection is None:
            return {"files": 0, "chunks": 0, "error": "ChromaDB недоступен"}

        # Очистка старой коллекции
        try:
            existing = collection.count()
            if existing > 0:
                # Удаляем все документы
                all_ids = collection.get()["ids"]
                if all_ids:
                    collection.delete(ids=all_ids)
        except Exception as e:
            logger.warning(f"RAG: ошибка очистки коллекции: {e}")

        stats = {"files": 0, "chunks": 0}

        if not self.kb_path.exists():
            logger.warning(f"RAG: папка базы знаний не найдена: {self.kb_path}")
            os.makedirs(self.kb_path, exist_ok=True)
            return stats

        for path in self._iter_files():
            try:
                text = self._parse_file(path)
                if not text or len(text.strip()) < 50:
                    continue
                chunks = self._split_chunks(text)
                subject = self._detect_subject_from_path(path)

                ids = []
                documents = []
                metadatas = []

                for i, chunk in enumerate(chunks):
                    ids.append(f"{path.stem}_{i}_{hash(chunk) % 10000}")
                    documents.append(chunk)
                    metadatas.append({
                        "source": path.name,
                        "subject": subject,
                        "path": str(path.relative_to(self.kb_path)),
                    })

                if documents:
                    # ChromaDB batch limit
                    batch_size = 100
                    for j in range(0, len(documents), batch_size):
                        collection.add(
                            ids=ids[j:j + batch_size],
                            documents=documents[j:j + batch_size],
                            metadatas=metadatas[j:j + batch_size],
                        )

                stats["files"] += 1
                stats["chunks"] += len(chunks)
                logger.info(
                    f"RAG: проиндексирован {path.name} "
                    f"({len(chunks)} чанков, предмет: {subject})"
                )
            except Exception as e:
                logger.error(f"RAG: ошибка индексации {path}: {e}")

        logger.info(
            f"RAG: индексация завершена. "
            f"Файлов: {stats['files']}, чанков: {stats['chunks']}"
        )
        return stats

    def _iter_files(self):
        """Итерирует по поддерживаемым файлам в базе знаний."""
        extensions = {".pdf", ".md", ".txt"}
        for path in self.kb_path.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions:
                yield path

    def _parse_file(self, path: Path) -> str:
        """Парсит файл в текст."""
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._parse_pdf(path)
        # .md и .txt — просто читаем
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="cp1251")
            except Exception:
                return ""

    def _parse_pdf(self, path: Path) -> str:
        """Парсит PDF через PyMuPDF."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("RAG: pymupdf не установлен, PDF пропущен")
            return ""
        try:
            doc = fitz.open(str(path))
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except Exception as e:
            logger.error(f"RAG: ошибка парсинга PDF {path}: {e}")
            return ""

    def _split_chunks(
        self, text: str, chunk_size: int = 800, overlap: int = 100
    ) -> list[str]:
        """Разбивает текст на чанки по словам с перекрытием."""
        words = text.split()
        if not words:
            return []
        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i: i + chunk_size])
            if len(chunk.strip()) > 50:
                chunks.append(chunk)
            i += chunk_size - overlap
        return chunks

    def _detect_subject_from_path(self, path: Path) -> str:
        """Определяет предмет по папке: knowledge_base/math/ → 'math'."""
        try:
            parts = path.relative_to(self.kb_path).parts
            if len(parts) > 1:
                return parts[0]  # первая подпапка = предмет
        except ValueError:
            pass
        return "general"
