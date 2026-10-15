"""Offline, provenance-preserving retrieval. No model or network clients."""
from .index import BM25Index

__all__ = ["BM25Index"]
