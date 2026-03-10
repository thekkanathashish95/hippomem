"""
Embedding service for hippomem (infra layer).
Works with any OpenAI-compatible embeddings endpoint.
"""
import time
import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when an embedding API call fails."""
    pass


class EmbeddingService:
    """
    Thin wrapper around any OpenAI-compatible embeddings endpoint.
    Supports single and batch embedding generation.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _make_request(self, input_data, model: Optional[str] = None) -> dict:
        model = model or self.model
        url = f"{self.base_url}/embeddings"
        payload = {"model": model, "input": input_data}

        last_exc = None
        delay = self.retry_delay

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    raise EmbeddingError(data["error"].get("message", "Unknown API error"))
                return data

            except requests.exceptions.HTTPError as e:
                last_exc = e
                status = e.response.status_code if e.response else None
                if status and 400 <= status < 500 and status != 429:
                    raise EmbeddingError(f"Embedding API client error ({status}): {e}") from e
                logger.warning("Embedding request error attempt %d/%d: %s", attempt, self.max_retries, e)

            except requests.exceptions.RequestException as e:
                last_exc = e
                logger.warning("Embedding request error attempt %d/%d: %s", attempt, self.max_retries, e)

            if attempt < self.max_retries:
                time.sleep(delay)
                delay *= 2

        raise EmbeddingError(
            f"Embedding request failed after {self.max_retries} attempts: {last_exc}"
        ) from last_exc

    def embed(self, text: str, model: Optional[str] = None) -> List[float]:
        """Embed a single text string. Returns a float vector."""
        if not text or not text.strip():
            raise EmbeddingError("Cannot embed empty text")
        data = self._make_request(text.strip(), model)
        items = data.get("data", [])
        if not items:
            raise EmbeddingError("No embedding in response")
        return items[0]["embedding"]

    def embed_batch(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """Embed a list of texts. Returns a list of float vectors in input order."""
        texts = [t.strip() if t else "" for t in texts]
        if not texts:
            return []
        data = self._make_request(texts, model)
        items = sorted(data.get("data", []), key=lambda x: x["index"])
        return [item["embedding"] for item in items]
