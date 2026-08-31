"""One InvisiblePlaywright browser, many tabs. The browser is ALWAYS launched
by InvisiblePlaywright, never Playwright directly, so the full stealth stack
applies."""
from __future__ import annotations

import os
from typing import Any, Optional

from invisible_playwright.async_api import InvisiblePlaywright

from .config import launch_kwargs


class StealthSession:
    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs or launch_kwargs(os.environ)
        self._ipw: Optional[InvisiblePlaywright] = None
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}
        self._active: Optional[str] = None
        self._counter = 0

    async def _attach(self, result) -> None:
        """`InvisiblePlaywright.__aenter__()` returns a Browser in ephemeral
        mode, or a persistent BrowserContext directly when profile_dir is
        set (that object has no .new_context()). Branch on capability so
        both paths are exercised."""
        if hasattr(result, "new_context"):        # a Browser (ephemeral mode)
            self._browser = result
            self._context = await result.new_context()
        else:                                     # a persistent BrowserContext (profile_dir)
            self._context = result

    async def start(self) -> None:
        self._ipw = InvisiblePlaywright(**self._kwargs)
        await self._attach(await self._ipw.__aenter__())

    async def new_page(self) -> str:
        self._counter += 1
        page_id = f"tab-{self._counter}"
        page = await self._context.new_page()
        self._pages[page_id] = page
        self._active = page_id
        return page_id

    def list_pages(self) -> list[str]:
        """The tabs this session knows about, including ones it did not open.

        A page can appear without `new_page` being called - a target with
        `_blank`, or `window.open` - and a caller that cannot name it cannot
        act on it. Adopting live pages from the context keeps the list honest.
        """
        if self._context is not None and hasattr(self._context, "pages"):
            for p in self._context.pages:
                # CLOSED pages are not adopted. Without this a tab that was
                # just closed comes straight back under a NEW id, because
                # `close_page` removes it from our own map while the context
                # can still list it - and then `page()` hands the caller a
                # handle that raises on the next tool.
                if getattr(p, "is_closed", None) is not None and p.is_closed():
                    continue
                if p not in self._pages.values():
                    self._counter += 1
                    pid = f"tab-{self._counter}"
                    self._pages[pid] = p
                    if not self._active:
                        self._active = pid
        return list(self._pages)

    def select_page(self, page_id: str) -> None:
        if page_id not in self._pages:
            raise RuntimeError(f"no such tab: {page_id}")
        self._active = page_id

    def page(self, page_id: Optional[str] = None):
        """The active page, or any live one, rather than a closed handle.

        The recorded tab can be closed under us - by the site, or by a
        navigation that replaced it - and returning it produces an error from
        whatever tool touched it rather than from here. Falling back to a live
        page from the context keeps a session usable after that.
        """
        pid = page_id or self._active
        if pid is not None and pid in self._pages:
            p = self._pages[pid]
            if not p.is_closed():
                return p

        # A tab the caller NAMED is answered strictly. The fallback below
        # exists so a session survives losing its active tab; applied to an
        # explicit id it would hand back a DIFFERENT page under the name that
        # was asked for, which is worse than an error - the caller goes on
        # acting on the wrong tab and nothing says so.
        if page_id is not None:
            raise RuntimeError(f"no such tab: {page_id}")

        if self._context is not None and hasattr(self._context, "pages") and self._context.pages:
            for p in reversed(self._context.pages):
                if not p.is_closed():
                    self._counter += 1
                    new_pid = f"tab-{self._counter}"
                    self._pages[new_pid] = p
                    self._active = new_pid
                    return p

        raise RuntimeError("no such tab; open one with session_new_page")

    async def close_page(self, page_id: Optional[str] = None) -> None:
        pid = page_id or self._active
        if pid is None or pid not in self._pages:
            return
        try:
            await self._pages[pid].close()
        except Exception:
            pass
        finally:
            self._pages.pop(pid, None)
            if self._active == pid:
                self._active = next(reversed(self._pages), None)

    async def close(self) -> None:
        for pid in list(self._pages):
            await self.close_page(pid)
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._ipw is not None:
            try:
                await self._ipw.__aexit__(None, None, None)
            finally:
                self._ipw = None
                self._browser = None
