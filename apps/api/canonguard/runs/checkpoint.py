from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from canonguard.core.logging import get_logger

logger = get_logger(__name__)


def libpq_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_checkpointer(database_url: str) -> Any:
    if not database_url.startswith("postgresql"):
        return MemorySaver()
    try:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row

        connection = psycopg.connect(
            libpq_url(database_url),
            autocommit=True,
            row_factory=dict_row,
        )
        saver = PostgresSaver(connection)
        saver.setup()
        return saver
    except Exception:
        logger.exception("postgres_checkpointer_init_failed")
        return MemorySaver()
