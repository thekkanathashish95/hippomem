"""
BM25 keyword retriever for C3 long-term retrieval.

Indexes all episodic engrams per user (core_intent + updates text).
Index is built on demand and cached with a TTL (default 5 min).
Exclude filtering is left to the caller, consistent with how FAISS is used.
"""
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from hippomem.models.engram import Engram, EngramKind

logger = logging.getLogger(__name__)

_EPISODIC_KINDS = {EngramKind.EPISODE.value, EngramKind.SUMMARY.value}


class BM25Retriever:
    """
    BM25 keyword retrieval over all episodic engrams for a user.
    The BM25Okapi index is cached per user_id and rebuilt after TTL expiry.
    """

    # Lazy-loaded NLTK resources — class-level so one copy lives per process
    _stop_words: Optional[set] = None
    _stemmer: Optional[Any] = None

    def __init__(self) -> None:
        # user_id -> (BM25Okapi, corpus_ids: List[str], built_at: float)
        self._cache: Dict[str, Tuple[Any, List[str], float]] = {}

    # ── NLTK lazy loaders ────────────────────────────────────────────────────

    @classmethod
    def _get_stop_words(cls) -> set:
        if cls._stop_words is None:
            try:
                import nltk
                nltk.download("stopwords", quiet=True)
                from nltk.corpus import stopwords
                cls._stop_words = set(stopwords.words("english"))
            except Exception as e:
                logger.warning("NLTK stopwords unavailable: %s, using fallback", e)
                cls._stop_words = {
                    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
                    "for", "of", "with", "by", "is", "are", "was", "were", "be",
                    "been", "being", "have", "has", "had", "do", "does", "did",
                    "will", "would", "could", "should", "may", "might", "must",
                    "can", "this", "that", "these", "those", "i", "you", "he", "she",
                    "it", "we", "they", "my", "your", "his", "her", "its", "our",
                    "their",
                }
        return cls._stop_words

    @classmethod
    def _get_stemmer(cls) -> Any:
        if cls._stemmer is None:
            from nltk.stem import PorterStemmer
            cls._stemmer = PorterStemmer()
        return cls._stemmer

    # ── Tokenizer ────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> List[str]:
        """Lowercase → word tokens → stopword removal → Porter stemming."""
        text = text.lower()
        tokens = re.findall(r"\b[a-z0-9]+\b", text)
        stop_words = self._get_stop_words()
        stemmer = self._get_stemmer()
        result = []
        for token in tokens:
            if token not in stop_words and len(token) > 1:
                try:
                    stemmed = stemmer.stem(token)
                except Exception:
                    stemmed = token
                if stemmed and stemmed not in stop_words:
                    result.append(stemmed)
        return result

    # ── Index build ──────────────────────────────────────────────────────────

    def _build_index(
        self, user_id: str, db: Session
    ) -> Tuple[Optional[Any], List[str]]:
        """
        Build BM25Okapi over all episodic engrams for user_id.
        Text = core_intent + updates (concatenated).
        Returns (BM25Okapi, corpus_ids) or (None, []) on failure.
        """
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank_bm25 not installed; BM25 retrieval disabled")
            return None, []

        try:
            rows = (
                db.query(Engram)
                .filter(
                    Engram.user_id == user_id,
                    Engram.engram_kind.in_(list(_EPISODIC_KINDS)),
                    Engram.core_intent.isnot(None),
                )
                .all()
            )
        except Exception as e:
            logger.warning("BM25 index build query failed for user %s: %s", user_id, e)
            return None, []

        if not rows:
            return None, []

        documents: List[List[str]] = []
        corpus_ids: List[str] = []
        for row in rows:
            text = row.core_intent or ""
            all_facts = (row.updates or []) + (row.pending_facts or [])
            if all_facts:
                text += " " + " ".join(all_facts)
            tokens = self._tokenize(text)
            if tokens:
                documents.append(tokens)
                corpus_ids.append(row.engram_id)

        if not documents:
            return None, []

        bm25 = BM25Okapi(documents)
        logger.debug("BM25 index built: user=%s docs=%d", user_id, len(documents))
        return bm25, corpus_ids

    def _get_or_build(
        self, user_id: str, db: Session, ttl_seconds: int
    ) -> Tuple[Optional[Any], List[str]]:
        """Return cached BM25Okapi if still fresh, otherwise rebuild."""
        cached = self._cache.get(user_id)
        if cached:
            bm25, corpus_ids, built_at = cached
            if time.monotonic() - built_at < ttl_seconds:
                return bm25, corpus_ids
        bm25, corpus_ids = self._build_index(user_id, db)
        if bm25 is not None:
            self._cache[user_id] = (bm25, corpus_ids, time.monotonic())
        return bm25, corpus_ids

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        user_id: str,
        db: Session,
        top_k: int = 10,
        ttl_seconds: int = 300,
    ) -> List[Dict[str, Any]]:
        """
        BM25 keyword search over all episodic engrams.
        Returns [{"event_uuid": str, "bm25_score": float}] in rank order.
        Exclude filtering is done by the caller. Returns [] on any failure.
        """
        try:
            import numpy as np

            bm25, corpus_ids = self._get_or_build(user_id, db, ttl_seconds)
            if bm25 is None or not corpus_ids:
                return []

            query_tokens = self._tokenize(query)
            if not query_tokens:
                return []

            scores = bm25.get_scores(query_tokens)
            top_indices = np.argsort(scores)[::-1][:top_k]
            return [
                {"event_uuid": corpus_ids[idx], "bm25_score": float(scores[idx])}
                for idx in top_indices
                if scores[idx] > 0 and idx < len(corpus_ids)
            ]
        except Exception as e:
            logger.warning("BM25 retrieve failed for user %s: %s", user_id, e)
            return []

    def invalidate(self, user_id: str) -> None:
        """Force cache invalidation for a user (call after encode to keep index fresh)."""
        self._cache.pop(user_id, None)
