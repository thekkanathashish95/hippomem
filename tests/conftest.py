import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from hippomem.db.base import Base
from hippomem.models import Engram, EngramLink, Trace, WorkingState  # noqa: F401
from hippomem.infra.vector.faiss_service import FAISSService

# --- Database ---

@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    Base.metadata.drop_all(e)

@pytest.fixture
def db(engine):
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    yield session
    session.close()

# --- FAISS ---

@pytest.fixture
def vector_dir(tmp_path):
    d = tmp_path / "vectors"
    d.mkdir()
    return str(d)

@pytest.fixture
def faiss_svc(vector_dir):
    return FAISSService(base_dir=vector_dir)

# --- LLM Mock ---

@pytest.fixture
def mock_llm():
    mock = MagicMock()
    mock.chat.return_value = "mocked response"
    # Override per-test: mock.chat_structured.return_value = SomePydanticModel(...)
    return mock

# --- Embedding Mock ---

@pytest.fixture
def mock_embeddings():
    mock = MagicMock()
    mock.embed.return_value = [0.1] * 1536   # 1536-dim to match FAISSService default
    mock.embed_batch.return_value = [[0.1] * 1536]
    return mock

# --- MemoryConfig ---

@pytest.fixture
def config():
    from hippomem.config import MemoryConfig
    return MemoryConfig(
        db_url="sqlite:///:memory:",
        vector_dir="/tmp/test_vectors",
        max_active_events=3,     # small for easier testing
        max_dormant_events=3,
    )
