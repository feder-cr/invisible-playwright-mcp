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
        self._pages[page_id] = await self._context.new_page()
        self._active = page_id
        return page_id

    def list_pages(self) -> list[str]:
        return list(self._pages)

    def select_page(self, page_id: str) -> None:
        if page_id not in self._pages:
            raise RuntimeError(f"no such tab: {page_id}")
        self._active = page_id

    def page(self, page_id: Optional[str] = None):
        pid = page_id or self._active
        if pid is None or pid not in self._pages:
            raise RuntimeError("no such tab; open one with session_new_page")
        return self._pages[pid]

    async def close_page(self, page_id: Optional[str] = None) -> None:
        pid = page_id or self._active
        if pid is None or pid not in self._pages:
            return
        try:
            await self._pages[pid].close()
        finally:
            del self._pages[pid]
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
