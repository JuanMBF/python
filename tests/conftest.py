import os

# Must be set before the application reads its settings.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import build_engine, get_db
from app.domain.enums import TicketCategory, TicketPriority, UserRole
from app.main import app
from app.models import User

PASSWORD = "Password123!"


@pytest.fixture
def engine() -> Iterator[Engine]:
    # A single shared in-memory connection, recreated for every test.
    engine = build_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    counter = 0

    def _make_user(
        role: UserRole = UserRole.REQUESTER,
        email: str | None = None,
        full_name: str | None = None,
        is_active: bool = True,
    ) -> User:
        nonlocal counter
        counter += 1
        user = User(
            email=email or f"{role.value}{counter}@example.com",
            full_name=full_name or f"{role.value.title()} {counter}",
            hashed_password=hash_password(PASSWORD),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return _make_user


@pytest.fixture
def admin(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.ADMIN, email="admin@example.com", full_name="Ada Admin")


@pytest.fixture
def agent(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.AGENT, email="agent@example.com", full_name="Tito Técnico")


@pytest.fixture
def requester(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.REQUESTER, email="user@example.com", full_name="Sara Solicitante")


@pytest.fixture
def other_requester(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.REQUESTER, email="other@example.com", full_name="Otro Usuario")


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def create_ticket(client: TestClient) -> Callable[..., dict]:
    def _create_ticket(
        user: User,
        title: str = "La impresora no imprime",
        description: str = "Aparece un error de atasco de papel.",
        category: TicketCategory = TicketCategory.HARDWARE,
        priority: TicketPriority = TicketPriority.MEDIUM,
    ) -> dict:
        response = client.post(
            "/api/v1/tickets",
            json={"title": title, "description": description, "category": category, "priority": priority},
            headers=auth(user),
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _create_ticket
