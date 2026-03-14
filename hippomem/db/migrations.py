"""
Lightweight schema migrations for hippomem.

No Alembic — migrations are idempotent ALTER TABLE statements guarded by
a PRAGMA table_info check. Called automatically from MemoryService._setup_sync
after create_all, so new installs and existing databases both end up current.
"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result.fetchall())


def run_migrations(engine) -> None:
    """Apply all pending schema migrations. Safe to call on every startup."""
    with engine.connect() as conn:
        _migrate_engrams(conn)
        conn.commit()


def _migrate_engrams(conn) -> None:
    if not _column_exists(conn, "engrams", "pending_facts"):
        conn.execute(text("ALTER TABLE engrams ADD COLUMN pending_facts TEXT"))
        logger.info("migration: added engrams.pending_facts")

    if not _column_exists(conn, "engrams", "needs_consolidation"):
        conn.execute(
            text("ALTER TABLE engrams ADD COLUMN needs_consolidation BOOLEAN NOT NULL DEFAULT 0")
        )
        logger.info("migration: added engrams.needs_consolidation")
