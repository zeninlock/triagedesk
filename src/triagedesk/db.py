from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from triagedesk.config import settings


@lru_cache
def engine():
    db = create_engine(
        settings().database_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_recycle=300,
        connect_args={"connect_timeout": 15, "prepare_threshold": None}
        if settings().database_url.startswith("postgresql")
        else {},
    )
    if db.dialect.name == "sqlite":  # Unit tests only; PostgreSQL is the supported application store.

        @event.listens_for(db, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return db


def get_session():
    with Session(engine(), expire_on_commit=False) as session:
        yield session
