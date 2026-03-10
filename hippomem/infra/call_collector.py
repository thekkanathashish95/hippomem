"""
LLM call collection for Inspector — ContextVar-based capture without method-signature pollution.

MemoryService sets a fresh LLMCallCollector before each top-level operation (decode/encode/consolidate).
LLMService._make_request() appends records to the collector after each successful call.
"""
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel


class UsageMetadata(BaseModel):
    """Lightweight schema for aggregating token usage and cost."""

    input_token_count: int = 0
    output_token_count: int = 0
    cost: float = 0.0

    @property
    def total_token_count(self) -> int:
        return self.input_token_count + self.output_token_count

    def __add__(self, other: "UsageMetadata") -> "UsageMetadata":
        return UsageMetadata(
            input_token_count=self.input_token_count + other.input_token_count,
            output_token_count=self.output_token_count + other.output_token_count,
            cost=self.cost + other.cost,
        )

    @classmethod
    def from_api_response(cls, usage_dict: dict) -> "UsageMetadata":
        """
        OpenAI/OpenRouter: usage.prompt_tokens, usage.completion_tokens, usage.cost (OpenRouter only).
        """
        return cls(
            input_token_count=usage_dict.get("prompt_tokens", 0),
            output_token_count=usage_dict.get("completion_tokens", 0),
            cost=usage_dict.get("cost", 0.0),
        )


@dataclass
class LLMCallRecord:
    """Single LLM call record for persistence."""

    op: str
    model: str
    messages: list
    raw_response: str
    input_tokens: int
    output_tokens: int
    cost: float
    latency_ms: int
    step_order: int = 0


@dataclass
class LLMCallCollector:
    """Collects LLM call records during a top-level operation."""

    records: List[LLMCallRecord] = field(default_factory=list)
    _counter: int = 0

    def add(self, record: LLMCallRecord) -> None:
        record.step_order = self._counter
        self._counter += 1
        self.records.append(record)

    @property
    def usage(self) -> UsageMetadata:
        total = UsageMetadata()
        for r in self.records:
            total = total + UsageMetadata(
                input_token_count=r.input_tokens,
                output_token_count=r.output_tokens,
                cost=r.cost,
            )
        return total

    @property
    def total_latency_ms(self) -> int:
        return sum(r.latency_ms for r in self.records)


_current_collector: ContextVar[Optional[LLMCallCollector]] = ContextVar(
    "_llm_call_collector", default=None
)
