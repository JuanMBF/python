from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

# Ids are 64-bit integers at most: a bigger number cannot even be sent to the database as a parameter.
MAX_DB_ID = 2**63 - 1
DbId = Annotated[int, Field(ge=1, le=MAX_DB_ID)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


class Message(BaseModel):
    detail: str
