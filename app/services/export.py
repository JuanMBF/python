"""CSV export of tickets, meant to be opened in a spreadsheet."""

import csv
import io
from collections.abc import Iterable

from app.models import Ticket

COLUMNS = (
    "id",
    "title",
    "category",
    "priority",
    "status",
    "requester",
    "assignee",
    "created_at",
    "due_at",
    "resolved_at",
    "sla_breached",
)

# Excel and LibreOffice run a cell that starts with one of these as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str) -> str:
    """Text written by users: a leading apostrophe makes spreadsheets show it as text, not run it."""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def tickets_to_csv(tickets: Iterable[Ticket]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for ticket in tickets:
        writer.writerow(
            [
                ticket.id,
                _text(ticket.title),
                ticket.category.value,
                ticket.priority.value,
                ticket.status.value,
                _text(ticket.requester.full_name),
                _text(ticket.assignee.full_name) if ticket.assignee else "",
                ticket.created_at.isoformat(),
                ticket.due_at.isoformat(),
                ticket.resolved_at.isoformat() if ticket.resolved_at else "",
                str(ticket.sla_breached).lower(),
            ]
        )
    # The BOM makes Excel read the file as UTF-8; without it accented characters come out garbled.
    return buffer.getvalue().encode("utf-8-sig")
