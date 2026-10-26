from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from triagedesk.config import settings


@lru_cache
def engine():
    db = create_engine(settings().database_url, pool_pre_ping=True)
    if db.dialect.name == "sqlite":  # Unit tests only; PostgreSQL is the supported application store.

        @event.listens_for(db, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return db


@contextmanager
def session_scope():
    with Session(engine(), expire_on_commit=False) as session:
        with session.begin():
            yield session


def get_session():
    with Session(engine(), expire_on_commit=False) as session:
        yield session
