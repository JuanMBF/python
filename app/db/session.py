"""Engine and session factory."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _unicode_lower(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def build_engine(database_url: str, **kwargs: Any) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True, **kwargs)

    if is_sqlite:
        # Per-connection SQLite settings.
        @event.listens_for(engine, "connect")
        def _configure_connection(dbapi_connection: Any, _record: Any) -> None:
            # SQLite ignores foreign keys unless explicitly enabled per connection.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            # SQLite's LOWER() only knows ASCII, so the case-insensitive search missed "Á" or "Ñ".
            dbapi_connection.create_function("lower", 1, _unicode_lower, deterministic=True)

    return engine


engine = build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
