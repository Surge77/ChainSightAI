"""The vocabulary the column contract is written in.

Two questions are asked of every column in the source table, and they are different
questions that people routinely collapse into one:

*When does this value exist?* — `Availability`. A value that is only known after the
lorry arrives cannot be an input to a prediction made before it leaves.

*What do we do about it?* — `Disposition`. Several columns exist at order time and are
still dropped, because they duplicate another column, identify a row, or identify a
person.

Keeping the two separate is what makes the audit reviewable. "Dropped" alone invites the
reader to assume leakage; `AT_ORDER` + `DROP_DUPLICATE` says plainly that the column was
available and was discarded for a different reason entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Availability(Enum):
    """When the value is knowable, relative to the moment a prediction is made."""

    AT_ORDER = "at order"
    """Known when the order is placed. Eligible to be a feature."""

    POST_DISPATCH = "post dispatch"
    """Only known once the shipment has happened. Never a feature; may be a target."""

    NEVER = "never"
    """Personal data. Not used at any point, whenever it happens to exist."""


class Disposition(Enum):
    """What this project does with the column."""

    USE = "use"
    TARGET = "target"
    DROP_LEAK = "drop: leak"
    DROP_PII = "drop: personal data"
    DROP_ID = "drop: identifier"
    DROP_DUPLICATE = "drop: duplicate"
    DROP_CONSTANT = "drop: constant or empty"


#: Dispositions that mean the column does not survive `ingest`.
DROPPED = frozenset(
    {
        Disposition.DROP_LEAK,
        Disposition.DROP_PII,
        Disposition.DROP_ID,
        Disposition.DROP_DUPLICATE,
        Disposition.DROP_CONSTANT,
    }
)


@dataclass(frozen=True)
class Column:
    """One column of the source table, and the decision made about it.

    `why` is one sentence and is not optional. A drop-list without reasons decays into
    superstition within a month: nobody remembers whether a column was dropped because it
    leaked or because it was empty, so nobody dares put it back.
    """

    name: str
    availability: Availability
    disposition: Disposition
    why: str

    @property
    def is_dropped(self) -> bool:
        return self.disposition in DROPPED
