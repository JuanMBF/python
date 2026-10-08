"""Database-level checks: migrations, custom types and demo data."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.domain.enums import TicketStatus
from app.models import Ticket, User
from app.seed import ROOT_DIR, seed_demo_data


def test_migrations_create_exactly_the_schema_defined_by_the_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False

    command.upgrade(config, "head")

    engine = build_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []

    command.downgrade(config, "base")


def test_datetimes_are_returned_timezone_aware(db: Session, requester: User) -> None:
    db.expire_all()

    assert db.get(User, requester.id).created_at.tzinfo == UTC


def test_naive_datetimes_are_rejected(db: Session, requester: User) -> None:
    requester.created_at = datetime(2026, 1, 1)  # noqa: DTZ001 - intentionally naive

    with pytest.raises(Exception, match="Naive datetimes"):
        db.commit()


def test_demo_data_is_consistent(db: Session) -> None:
    seed_demo_data(db, ticket_count=60)

    tickets = db.scalars(select(Ticket)).all()
    assert len(tickets) == 60
    assert db.scalar(select(func.count(User.id))) == 12
    for ticket in tickets:
        assert ticket.events[0].event_type == "created"
        assert ticket.due_at > ticket.created_at
        if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            assert ticket.resolved_at is not None and ticket.resolved_at >= ticket.created_at
        else:
            assert ticket.resolved_at is None
        if ticket.status != TicketStatus.OPEN:
            assert ticket.assignee is not None
