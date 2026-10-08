from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, StringConstraints

from app.domain.enums import UserRole


def _fits_bcrypt(value: str) -> str:
    # bcrypt only accepts up to 72 bytes; multi-byte characters count more than once.
    if len(value.encode("utf-8")) > 72:
        raise ValueError("La contraseña es demasiado larga")
    return value


def _lowercase(value: str) -> str:
    return value.lower()


Password = Annotated[str, StringConstraints(min_length=8, max_length=64), AfterValidator(_fits_bcrypt)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Email = Annotated[EmailStr, AfterValidator(_lowercase)]


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: UserRole


class UserRead(UserSummary):
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: Email
    full_name: FullName
    password: Password
    role: UserRole = UserRole.REQUESTER


class UserUpdate(BaseModel):
    full_name: FullName | None = None
    password: Password | None = None
    role: UserRole | None = None
    is_active: bool | None = None
