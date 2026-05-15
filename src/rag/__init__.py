"""
RAG (Retrieval-Augmented Generation) — поиск по базе знаний.
"""
from .indexer import KnowledgeIndexer
from .retriever import KnowledgeRetriever

__all__ = ["KnowledgeIndexer", "KnowledgeRetriever"]
