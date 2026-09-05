"""LLM keys stay out of hippomem_config.json and land in 0600 secrets.json."""
import json
import stat

from hippomem.server.config_store import load_config_overlay, save_config


def test_save_config_never_writes_key_to_public_file(tmp_path):
    db_url = f"sqlite:///{tmp_path}/x.db"
    save_config(db_url, {"llm_api_key": "sk-secret", "llm_model": "test-model"})

    public = json.loads((tmp_path / "hippomem_config.json").read_text())
    assert "llm_api_key" not in public
    assert public["llm_model"] == "test-model"

    secrets = tmp_path / "secrets.json"
    assert json.loads(secrets.read_text())["llm_api_key"] == "sk-secret"
    mode = secrets.stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_load_overlay_merges_secrets_without_leaving_key_in_public(tmp_path):
    db_url = f"sqlite:///{tmp_path}/x.db"
    (tmp_path / "hippomem_config.json").write_text(
        json.dumps({"llm_api_key": "should-be-ignored", "llm_model": "m"})
    )
    (tmp_path / "secrets.json").write_text(json.dumps({"llm_api_key": "from-secrets"}))
    overlay = load_config_overlay(db_url)
    assert overlay["llm_api_key"] == "from-secrets"
    assert overlay["llm_model"] == "m"
