"""
LLM service for hippomem (infra layer).
Works with any OpenAI-compatible API endpoint (OpenAI, Azure, OpenRouter, Ollama, etc.).
"""
import json
import time
import logging
from typing import List, Dict, Optional, Any, Type, TypeVar

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when an LLM API call fails."""
    pass


class LLMService:
    """
    Thin wrapper around any OpenAI-compatible chat completions endpoint.
    Supports plain chat, tool calls, and structured JSON output.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
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

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        op: str = "chat",
    ) -> Dict[str, Any]:
        model = model or self.model
        url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format

        last_exc = None
        delay = self.retry_delay

        for attempt in range(1, self.max_retries + 1):
            try:
                t0 = time.perf_counter()
                response = requests.post(
                    url=url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                if "error" in data:
                    raise LLMError(data["error"].get("message", "Unknown API error"))
                ms = int((time.perf_counter() - t0) * 1000)
                logger.debug("call: op=%s model=%s ms=%d", op, model, ms)

                # Capture for inspector (no-op if no collector is active)
                from hippomem.infra.call_collector import (
                    _current_collector,
                    LLMCallRecord,
                    UsageMetadata,
                )

                collector = _current_collector.get()
                if collector is not None:
                    usage_dict = data.get("usage", {})
                    usage = UsageMetadata.from_api_response(usage_dict)
                    choices = data.get("choices", [])
                    raw = (
                        choices[0].get("message", {}).get("content", "")
                        if choices
                        else ""
                    )
                    collector.add(
                        LLMCallRecord(
                            op=op,
                            model=model,
                            messages=messages,
                            raw_response=raw or "",
                            input_tokens=usage.input_token_count,
                            output_tokens=usage.output_token_count,
                            cost=usage.cost,
                            latency_ms=ms,
                        )
                    )

                return data

            except requests.exceptions.HTTPError as e:
                last_exc = e
                status = e.response.status_code if e.response else None
                if status and 400 <= status < 500 and status != 429:
                    raise LLMError(f"LLM API client error ({status}): {e}") from e
                logger.warning(
                    "retry %d/%d: %s op=%s",
                    attempt, self.max_retries, str(e), op,
                )

            except requests.exceptions.RequestException as e:
                last_exc = e
                logger.warning(
                    "retry %d/%d: %s op=%s",
                    attempt, self.max_retries, str(e), op,
                )

            if attempt < self.max_retries:
                time.sleep(delay)
                delay *= 2

        logger.error("exhausted retries op=%s: %s", op, last_exc)
        raise LLMError(
            f"LLM request failed after {self.max_retries} attempts: {last_exc}"
        ) from last_exc

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        op: str = "chat",
    ) -> Optional[str]:
        """
        Send a chat completion. Returns the assistant's text content.
        Returns None if the model responded with tool calls only.
        """
        data = self._make_request(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            op=op,
        )
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("No choices in LLM response")
        content = choices[0].get("message", {}).get("content")
        return content if content else None

    def chat_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        op: str = "chat_structured",
    ) -> T:
        """
        Send a chat completion with structured JSON output.
        Returns a validated Pydantic model instance.
        """
        schema = response_model.model_json_schema()
        if "additionalProperties" not in schema:
            schema = {**schema, "additionalProperties": False}
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.get("title", response_model.__name__),
                "strict": True,
                "schema": schema,
            },
        }
        data = self._make_request(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            op=op,
        )
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("No choices in LLM response")
        content = choices[0].get("message", {}).get("content", "")
        if not content or not content.strip():
            raise LLMError("Empty content in structured response")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Structured response is not valid JSON: {e}") from e
        return response_model.model_validate(parsed)
