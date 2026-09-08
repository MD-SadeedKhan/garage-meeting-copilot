"""A malformed session id must read as "not found", never as a server error.

`MeetingSession.id` is a Postgres `uuid` column, so `WHERE id = 'not-a-uuid'`
does not come back empty — the driver raises `invalid input syntax for type
uuid` as the statement runs. All sixteen `{session_id}` routes already handle a
missing session correctly and not one could reach that code, so a bad id in a
URL surfaced to the caller as a 500.

Found by the NetworkChains desktop route sweep, which walks every screen with a
deliberately synthetic id. The same defect was live in a sibling service.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.repositories.copilot_repo import (
    MeetingSessionRepository,
    is_valid_session_id,
)


class ExplodingSession:
    """A database that fails loudly if anyone queries it.

    The point of the guard is that an unusable id never reaches the driver, so
    the test has to be able to tell "returned None after querying" apart from
    "returned None without querying". Only the second is the fix.
    """

    def __init__(self) -> None:
        self.queried = False

    async def execute(self, *_args, **_kwargs):
        self.queried = True
        raise AssertionError("queried the database with an unusable id")


def test_accepts_a_well_formed_id():
    assert is_valid_session_id(str(uuid.uuid4()))


@pytest.mark.parametrize(
    "bad",
    [
        "sweep-nonexistent-id",  # the id the desktop sweep sends
        "",
        "123",
        "'; DROP TABLE meeting_sessions; --",
        # One character too many: passes a careless regex, still rejected by
        # Postgres.
        "0b7f4a4e-1f0e-4d0a-9d5b-1a2b3c4d5e6f7",
    ],
)
def test_rejects_ids_postgres_cannot_parse(bad):
    assert not is_valid_session_id(bad)


@pytest.mark.parametrize("lookup", ["get_by_id", "get_with_relations"])
def test_lookups_short_circuit_instead_of_raising(lookup):
    # Driven with asyncio.run rather than pytest-asyncio: one coroutine does not
    # justify a plugin the service does not otherwise need.
    db = ExplodingSession()
    repo = MeetingSessionRepository(db)

    result = asyncio.run(getattr(repo, lookup)("sweep-nonexistent-id"))

    assert result is None
    assert not db.queried
