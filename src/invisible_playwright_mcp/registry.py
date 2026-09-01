"""Sessions, owned here rather than by whoever happens to be connected.

The server used to hold one session in a module global and close it when the
client went away. That made the browser a property of the connection, which
blocked three things at once: only one client could ever attach, the session
could not outlive the process that served it, and nothing but a tool call could
reach the page.

So sessions live here, keyed by id, and a client is just something that borrows
one. Closing happens when the process shuts down, or when someone asks - not
when a client disconnects.
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional

from .session import StealthSession

# The id used by callers that do not ask for one. Existing stdio clients send no
# session id and must keep behaving exactly as they did, which means they all
# land here, on one shared session, as before.
DEFAULT_SESSION_ID = "default"


def _is_usable(session) -> bool:
    """Whether a stored session can still be handed out.

    Two failures are handled, and they are different:

    * A session whose browser has DIED under it. The object is intact, so
      nothing raises until a tool touches the page, and then it raises somewhere
      unhelpful.
    * A session that never finished starting, which leaves `_context` unset.

    Anything unexpected while checking counts as unusable: the cost of throwing
    away a good session is one relaunch, and the cost of keeping a bad one is an
    error that names nothing.
    """
    try:
        if session._browser is not None and not session._browser.is_connected():
            return False
        return session._context is not None
    except Exception:
        return False


class SessionRegistry:
    """Sessions by id, created on demand, closed on request or at shutdown."""

    def __init__(self, factory=StealthSession) -> None:
        self._factory = factory
        self._sessions: Dict[str, StealthSession] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        # One lock per id, so two clients racing to first-use the same session
        # start one browser rather than two. Without it the second caller finds
        # an empty slot while the first is still awaiting start().
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def peek(self, session_id: str = DEFAULT_SESSION_ID) -> Optional[StealthSession]:
        """The session as it stands, without starting anything. For callers that
        want to know whether a browser is up, such as a live view."""
        return self._sessions.get(session_id)

    def ids(self) -> list:
        return sorted(self._sessions)

    async def ensure(self, session_id: str = DEFAULT_SESSION_ID) -> StealthSession:
        """The session for this id, started and usable.

        A start that FAILS must not poison the id. The original bug here stored
        the session before awaiting `start()`, so a start that raised left a
        half-built object behind: every later call found something non-None,
        skipped the start, and died on `'NoneType' object has no attribute ...`,
        an error that names nothing and, on a stdio server, ended the whole
        conversation. The two ways to hit it are ordinary - a stale
        INVISIBLE_SEAL_FILE, and a proxy that is down when the first tool runs.

        So a session is stored only once it has actually started.
        """
        async with self._lock(session_id):
            existing = self._sessions.get(session_id)
            if existing is not None and not _is_usable(existing):
                await self._discard(session_id)
                existing = None

            if existing is None:
                session = self._factory()
                await session.start()
                self._sessions[session_id] = session
                return session
            return existing

    async def _discard(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        try:
            await session.close()
        except Exception:
            # A session being discarded is already suspect; a failure to close
            # it cleanly must not stop the replacement from starting.
            pass

    async def drop(self, session_id: str = DEFAULT_SESSION_ID) -> None:
        """Throw a session away so the next `ensure` builds a fresh one."""
        async with self._lock(session_id):
            await self._discard(session_id)

    async def close_all(self) -> None:
        """Shut every session down. Called when the PROCESS ends, not when a
        client disconnects - that difference is the reason this class exists."""
        for session_id in list(self._sessions):
            await self._discard(session_id)
