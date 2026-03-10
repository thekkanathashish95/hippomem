"""Prompt templates for LLM memory operations."""
import functools
from pathlib import Path

import yaml


def _decoder_prompts_path() -> Path:
    return Path(__file__).parent / "decoder.yaml"


def _encoder_prompts_path() -> Path:
    return Path(__file__).parent / "encoder.yaml"


def _consolidator_prompts_path() -> Path:
    return Path(__file__).parent / "consolidator.yaml"


def _entity_prompts_path() -> Path:
    return Path(__file__).parent / "entity.yaml"


def _self_prompts_path() -> Path:
    return Path(__file__).parent / "self_encoder.yaml"


@functools.lru_cache(maxsize=1)
def _load_decoder_prompts() -> dict:
    """Load decoder prompts from YAML. Cached on first call."""
    with open(_decoder_prompts_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=1)
def _load_encoder_prompts() -> dict:
    """Load encoder prompts from YAML. Cached on first call."""
    with open(_encoder_prompts_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=1)
def _load_consolidator_prompts() -> dict:
    """Load consolidator prompts from YAML. Cached on first call."""
    with open(_consolidator_prompts_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=1)
def _load_entity_prompts() -> dict:
    """Load entity prompts from YAML. Cached on first call."""
    with open(_entity_prompts_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=1)
def _load_self_prompts() -> dict:
    """Load self encoder prompts from YAML. Cached on first call."""
    with open(_self_prompts_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_decoder_prompts(operation: str) -> dict:
    """Get system and user_template for a decoder operation."""
    prompts = _load_decoder_prompts()
    ops = prompts.get("operations", {})
    if operation not in ops:
        raise ValueError(f"Unknown decoder operation: {operation}")
    return ops[operation]


def get_encoder_prompts(operation: str) -> dict:
    """Get system and user_template for an encoder operation."""
    prompts = _load_encoder_prompts()
    ops = prompts.get("operations", {})
    if operation not in ops:
        raise ValueError(f"Unknown encoder operation: {operation}")
    return ops[operation]


def get_consolidator_prompts(operation: str) -> dict:
    """Get system and user_template for a consolidator operation."""
    prompts = _load_consolidator_prompts()
    ops = prompts.get("operations", {})
    if operation not in ops:
        raise ValueError(f"Unknown consolidator operation: {operation}")
    return ops[operation]


def get_entity_prompts(operation: str) -> dict:
    """Get system and user_template for an entity operation."""
    prompts = _load_entity_prompts()
    ops = prompts.get("operations", {})
    if operation not in ops:
        raise ValueError(f"Unknown entity operation: {operation}")
    return ops[operation]


def get_self_prompts(operation: str) -> dict:
    """Get system and user_template for a self encoder operation."""
    prompts = _load_self_prompts()
    ops = prompts.get("operations", {})
    if operation not in ops:
        raise ValueError(f"Unknown self operation: {operation}")
    return ops[operation]
