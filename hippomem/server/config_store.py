"""
Config persistence for hippomem server.

Loads hippomem_config.json from the same directory as the SQLite DB.
The LLM API key is never written to that file — it lives in env or
``secrets.json`` (mode 0600).
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "hippomem_config.json"
SECRETS_FILENAME = "secrets.json"
_SECRET_FIELDS = frozenset({"llm_api_key"})


def _db_dir_from_url(db_url: str) -> Path:
    """Resolve the directory containing the SQLite DB file from db_url."""
    if "sqlite" not in db_url:
        return Path.cwd()
    # sqlite:///path (relative) or sqlite:////absolute/path
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        path_part = db_url[len(prefix) :]
        if not path_part:
            return Path.cwd()
        p = Path(path_part)
        if p.is_absolute():
            return p.parent
        try:
            return p.resolve().parent
        except OSError:
            return Path.home() / ".hippomem"
    return Path.cwd()


def config_path(db_url: str) -> Path:
    """Path to hippomem_config.json in the same directory as the DB."""
    return _db_dir_from_url(db_url) / CONFIG_FILENAME


def secrets_path(db_url: str) -> Path:
    return _db_dir_from_url(db_url) / SECRETS_FILENAME


def load_config_overlay(db_url: str) -> dict[str, Any]:
    """
    Load hippomem_config.json if it exists.
    Merges llm_api_key from secrets.json when present.
    """
    path = config_path(db_url)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
            else:
                logger.warning("Invalid config: %s is not a JSON object", path)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load config from %s: %s", path, e)
    data.pop("llm_api_key", None)
    sec = secrets_path(db_url)
    if sec.exists():
        try:
            with open(sec, encoding="utf-8") as f:
                secrets = json.load(f)
            if isinstance(secrets, dict) and secrets.get("llm_api_key"):
                data["llm_api_key"] = secrets["llm_api_key"]
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load secrets from %s: %s", sec, e)
    return data


def save_config(db_url: str, config: dict[str, Any]) -> None:
    """Persist non-secret config. LLM key goes to secrets.json (0600) only."""
    path = config_path(db_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    public = {k: v for k, v in config.items() if k not in _SECRET_FIELDS}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(public, f, indent=2)
    key = config.get("llm_api_key")
    if key and key != "sk-****":
        sec = secrets_path(db_url)
        fd = os.open(str(sec), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"llm_api_key": key}, f)
        os.chmod(sec, 0o600)
    logger.info("Config saved to %s", path)
