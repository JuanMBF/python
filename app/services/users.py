from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password, verify_password
from app.domain.enums import UserRole
from app.domain.workflow import ACTIVE_STATUSES
from app.models import Ticket, User
from app.schemas.user import UserCreate, UserUpdate

STAFF_ROLES = (UserRole.AGENT, UserRole.ADMIN)


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("Usuario no encontrado")
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    # Same normalization as the Email schema used when the user was created: no surrounding spaces.
    return db.scalar(select(User).where(User.email == email.strip().lower()))


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user


def list_users(db: Session, roles: list[UserRole] | None = None, is_active: bool | None = None) -> list[User]:
    query = select(User).order_by(User.full_name)
    if roles:
        query = query.where(User.role.in_(roles))
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    return list(db.scalars(query))


def create_user(db: Session, data: UserCreate) -> User:
    if get_user_by_email(db, data.email) is not None:
        raise ConflictError("Ya existe un usuario con ese email")
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: int, data: UserUpdate, actor: User) -> User:
    user = get_user(db, user_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)

    if user.id == actor.id:
        # Protect against an admin locking themselves (and maybe everyone) out.
        if changes.get("is_active") is False:
            raise ConflictError("No podés desactivar tu propio usuario")
        if "role" in changes and changes["role"] != UserRole.ADMIN:
            raise ConflictError("No podés quitarte tus propios permisos de administrador")

    # Tickets can only be assigned to active staff: leaving one with a requester or an inactive user
    # means nobody can work on it, and the requester cannot even see it.
    stays_staff = changes.get("role", user.role) in STAFF_ROLES and changes.get("is_active", user.is_active)
    if user.is_staff and not stays_staff:
        assigned = db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.assignee_id == user.id, Ticket.status.in_(ACTIVE_STATUSES)
            )
        )
        if assigned:
            noun = "ticket activo asignado" if assigned == 1 else "tickets activos asignados"
            raise ConflictError(f"El usuario tiene {assigned} {noun}: reasignalos antes")

    if "password" in changes:
        user.hashed_password = hash_password(changes.pop("password"))
    for field, value in changes.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user
