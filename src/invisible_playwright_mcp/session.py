"""One InvisiblePlaywright browser, many tabs. The browser is ALWAYS launched
by InvisiblePlaywright, never Playwright directly, so the full stealth stack
applies."""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from invisible_playwright.async_api import InvisiblePlaywright

from .config import launch_kwargs


#: Where capture lands when STEALTHFOX_CAPTURE_DIR says nothing.
#:
#: The working directory, not a path counted upwards from this file. An earlier
#: version used `Path(__file__).resolve().parents[4]`, which lands on the
#: project directory from `site-packages/invisible_playwright_mcp/session.py`
#: and on something else entirely from a src-layout checkout, where four levels
#: up leaves the repository. A default that depends on how the package was
#: installed writes frames somewhere the caller cannot predict; the working
#: directory is at least the place they ran the thing from.
def _default_capture_root() -> Path:
    return Path.cwd() / "mcp_captures"


class StealthSession:
    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs or launch_kwargs(os.environ)
        self._ipw: Optional[InvisiblePlaywright] = None
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}
        self._capture_tasks: dict[str, asyncio.Task] = {}
        self._active: Optional[str] = None
        self._counter = 0
        capture_dir = os.environ.get("STEALTHFOX_CAPTURE_DIR", "").strip()
        self._capture_root = (
            Path(capture_dir) if capture_dir else _default_capture_root()
        )
        interval_ms = float(os.environ.get("STEALTHFOX_CAPTURE_INTERVAL_MS", "200"))
        self._capture_interval = max(0.1, interval_ms / 1000.0)
        quality = int(os.environ.get("STEALTHFOX_CAPTURE_QUALITY", "55"))
        self._capture_quality = min(100, max(1, quality))
        self._capture_session_dir: Optional[Path] = None

    def _start_capture(self, page_id: str, page: Any) -> None:
        if self._capture_session_dir is None:
            session_name = datetime.now().strftime("session_%Y%m%d_%H%M%S_%f")
            self._capture_session_dir = self._capture_root / session_name
            self._capture_session_dir.mkdir(parents=True, exist_ok=True)
        page_dir = self._capture_session_dir / page_id
        page_dir.mkdir(parents=True, exist_ok=True)
        status_path = page_dir / "capture_status.json"
        status_path.write_text(json.dumps({
            "state": "started",
            "page_id": page_id,
            "interval_ms": int(self._capture_interval * 1000),
            "quality": self._capture_quality,
            "started_at": datetime.now().isoformat(timespec="milliseconds"),
        }, indent=2), encoding="utf-8")
        self._capture_tasks[page_id] = asyncio.create_task(
            self._capture_loop(page_id, page, page_dir),
            name=f"capture-{page_id}",
        )

    async def _capture_loop(self, page_id: str, page: Any, page_dir: Path) -> None:
        frame_index = 0
        metadata_path = page_dir / "frames.jsonl"
        while not page.is_closed():
            started = time.monotonic()
            frame_name = f"frame_{frame_index:06d}.jpg"
            frame_path = page_dir / frame_name
            try:
                await page.screenshot(
                    path=str(frame_path),
                    type="jpeg",
                    quality=self._capture_quality,
                    animations="allow",
                    caret="initial",
                    scale="css",
                    timeout=10_000,
                )
                record = {
                    "frame": frame_index,
                    "file": frame_name,
                    "captured_at": datetime.now().isoformat(timespec="milliseconds"),
                    "url": page.url,
                    "page_id": page_id,
                }
                with metadata_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                frame_index += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                # Navigations can temporarily destroy a document while a
                # screenshot is in flight. Skip that frame and keep recording.
                status_path = page_dir / "capture_status.json"
                try:
                    status_path.write_text(json.dumps({
                        "state": "retrying_after_error",
                        "page_id": page_id,
                        "last_error_at": datetime.now().isoformat(timespec="milliseconds"),
                    }, indent=2), encoding="utf-8")
                except Exception:
                    pass
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0, self._capture_interval - elapsed))

    async def _stop_capture(self, page_id: str) -> None:
        task = self._capture_tasks.pop(page_id, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

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
        self._start_capture(page_id, page)
        return page_id

    def list_pages(self) -> list[str]:
        """The tabs this session knows about, including ones it did not open.

        A page can appear without `new_page` being called - a target with
        `_blank`, or `window.open` - and a caller that cannot name it cannot
        act on it. Adopting live pages from the context keeps the list honest.
        """
        if self._context is not None and hasattr(self._context, "pages"):
            for p in self._context.pages:
                # ⛔ CLOSED pages are not adopted. Without this a tab that was
                # just closed comes straight back under a NEW id, because
                # `close_page` removes it from our own map while the context
                # can still list it - and then `page()` hands the caller a
                # handle that raises on the next tool. Found by the multi-tab
                # test, which asserted the list after a close.
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

        # ⛔ A tab the caller NAMED is answered strictly. The fallback below
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
        await self._stop_capture(pid)
        try:
            await self._pages[pid].close()
        except Exception:
            pass
        finally:
            self._pages.pop(pid, None)
            if self._active == pid:
                self._active = next(reversed(self._pages), None)

    async def close(self) -> None:
        for pid in list(self._capture_tasks):
            await self._stop_capture(pid)
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
