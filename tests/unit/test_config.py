"""
Test: MemoryConfig() creates with expected defaults
Test: decay_rate_per_hour default is 0.98
Test: max_active_events default is 5
Test: enable_background_consolidation default is False
Test: override values are accepted
"""
from hippomem.config import MemoryConfig


def test_memory_config_defaults():
    config = MemoryConfig()
    assert config.decay_rate_per_hour == 0.98
    assert config.max_active_events == 5
    assert config.enable_background_consolidation is False


def test_memory_config_override():
    config = MemoryConfig(
        decay_rate_per_hour=0.95,
        max_active_events=10,
        enable_background_consolidation=True,
    )
    assert config.decay_rate_per_hour == 0.95
    assert config.max_active_events == 10
    assert config.enable_background_consolidation is True
