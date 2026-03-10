from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator


def create_db_engine(db_url: str):
    """Create a SQLAlchemy engine for the given URL."""
    connect_args = {}
    if "sqlite" in db_url:
        # check_same_thread=False: allow use across threads (needed in async contexts)
        # timeout=30: wait up to 30s for locks instead of failing immediately
        connect_args = {"check_same_thread": False, "timeout": 30}

    engine = create_engine(db_url, connect_args=connect_args)

    if "sqlite" in db_url:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            """Enable WAL mode for better concurrent read/write performance."""
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def create_session_factory(engine):
    """Create a session factory bound to the given engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db_session(session_factory) -> Generator[Session, None, None]:
    """Context manager / dependency for obtaining a DB session."""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
