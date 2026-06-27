"""SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from trading.core.settings import Settings


def sqlalchemy_url(database_url: str) -> str:
    """Normalize env-style PostgreSQL URLs for psycopg/SQLAlchemy."""

    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def create_db_engine(settings: Settings, *, echo: bool = False) -> Engine:
    return create_engine(
        sqlalchemy_url(settings.DATABASE_URL),
        echo=echo,
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
