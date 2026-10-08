from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, StaffUser
from app.domain.enums import UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["Usuarios"])


@router.get("", response_model=list[UserRead], summary="Listar usuarios")
def list_users(
    db: DbSession,
    _: StaffUser,
    role: Annotated[list[UserRole] | None, Query()] = None,
    is_active: bool | None = None,
) -> list[UserRead]:
    """Disponible para técnicos (p. ej. para elegir a quién asignar un ticket) y administradores."""
    users = user_service.list_users(db, roles=role, is_active=is_active)
    return [UserRead.model_validate(user) for user in users]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Crear usuario")
def create_user(db: DbSession, _: AdminUser, data: UserCreate) -> UserRead:
    return UserRead.model_validate(user_service.create_user(db, data))


@router.patch("/{user_id}", response_model=UserRead, summary="Actualizar usuario")
def update_user(db: DbSession, admin: AdminUser, user_id: int, data: UserUpdate) -> UserRead:
    return UserRead.model_validate(user_service.update_user(db, user_id, data, actor=admin))
