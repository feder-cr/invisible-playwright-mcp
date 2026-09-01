"""The browser operations, as plain functions over a session.

This module is the only implementation. The MCP tools in `server.py` are a thin
wrapper over it, and anything else that drives the browser - the built-in chat,
a test, a script - calls the same functions rather than reimplementing them.

That constraint is the point of the file. A second path to the page would give
two behaviours to keep in step, and they would drift: the tool would grow a
timeout the chat never got, the chat would grow a retry the tool never got, and
the difference would surface as a bug report nobody could reproduce.

Nothing here knows what MCP is, or what a session id is. It takes a session and
acts on it.
"""
from __future__ import annotations

import json
from typing import Any

# The character cap every text-returning action shares. Callers can lower it;
# it exists so one enormous page cannot fill a model's context by itself.
DEFAULT_MAX_CHARS = 6000


def json_capped(obj: Any, limit: int = DEFAULT_MAX_CHARS) -> str:
    """Serialize obj as JSON, capped at `limit` chars.

    Never slices an already-serialized string, which would yield invalid JSON.
    When the payload is too big it returns a small, always-valid envelope.
    """
    s = json.dumps(obj)
    if len(s) <= limit:
        return s
    return json.dumps({"truncated": True, "chars": len(s), "preview": s[:limit]})


# --- pages -----------------------------------------------------------------

async def new_page(session) -> str:
    return await session.new_page()


def list_pages(session) -> str:
    return json.dumps(session.list_pages())


def select_page(session, page_id: str) -> str:
    session.select_page(page_id)
    return f"active tab is {page_id}"


async def close_page(session, page_id: str = "") -> str:
    await session.close_page(page_id or None)
    return "page closed"


# --- reading ---------------------------------------------------------------

async def navigate(session, url: str, wait_until: str = "domcontentloaded") -> str:
    if not session.list_pages():
        await session.new_page()
    await session.page().goto(url, wait_until=wait_until, timeout=45_000)
    return f"navigated to {url}"


async def read_text(session, selector: str = "body", max_chars: int = DEFAULT_MAX_CHARS) -> str:
    txt = await session.page().evaluate(
        "(sel) => { const el = document.querySelector(sel);"
        " return el ? el.innerText : null; }", selector,
    )
    return f"(no element matches {selector!r})" if txt is None else txt[:max_chars]


SNAPSHOT_JS = """() => {
    // Read only. Numbering the elements would mean writing an attribute into
    // the page, which is a detection surface in a product that exists not to
    // have one. If a stable index is ever wanted, it gets decided in the open.
    const SEL = [
        'input', 'button', 'select', 'textarea', 'a[href]',
        '[role="button"]', '[role="link"]', '[role="checkbox"]',
        '[role="radio"]', '[role="tab"]', '[role="menuitem"]', '[role="switch"]',
        '[onclick]', '[tabindex]:not([tabindex="-1"])',
        '[contenteditable="true"]'
    ].join(',');

    // offsetParent used to stand in for "visible" and was wrong both ways: it is
    // null on every position:fixed element - the cookie banner, the sticky bar,
    // the button inside a modal - and it says nothing about visibility:hidden or
    // about an element parked at left:-9999px.
    function shown(el) {
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return false;
        const s = getComputedStyle(el);
        if (s.visibility === 'hidden' || s.display === 'none') return false;
        if (parseFloat(s.opacity) === 0) return false;
        if (el.disabled === true) return false;
        // Parked off-canvas to the left or above: the ordinary way to hide
        // something without hiding it. Below the fold is NOT excluded, because
        // the page may simply be long and that content is still real.
        if (r.right <= 0 || r.bottom <= 0) return false;
        return true;
    }

    const seen = new Set();
    const out = [];
    for (const el of document.querySelectorAll(SEL)) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (!shown(el)) continue;
        const r = el.getBoundingClientRect();
        out.push({
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role') || undefined,
            type: el.type || undefined,
            name: el.name || undefined,
            id: el.id || undefined,
            href: el.tagName === 'A' ? (el.getAttribute('href') || undefined) : undefined,
            placeholder: el.placeholder || undefined,
            label: el.getAttribute('aria-label') || undefined,
            text: (el.innerText || el.value || '').trim().slice(0, 50),
            // Viewport coordinates of the centre, so browser_click_at can reach
            // what no selector describes.
            at: [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)],
            in_view: r.top < innerHeight && r.left < innerWidth
        });
    }
    return { title: document.title, url: location.href, interactive_elements: out };
}"""


async def snapshot(session, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Title, url, and the interactive elements that are actually visible.

    Not the accessibility tree, and the reason is measured rather than
    aesthetic: on a real sign-up page a single country `<select>` contributes
    about two hundred `<option>` nodes, which fill the character cap before the
    form the caller was looking for appears at all. Filtering to elements a
    caller can act on - and to `offsetParent !== null`, so hidden ones do not
    count - keeps the answer about the page rather than about its longest
    dropdown.
    """
    return json_capped(await session.page().evaluate(SNAPSHOT_JS), limit=max_chars)


async def screenshot_png(session) -> bytes:
    """Raw PNG bytes of the active tab.

    Bytes rather than an MCP Image, because this is also what a live view in a
    browser tab needs, and that caller has no use for an MCP type.
    """
    return await session.page().screenshot()


# --- acting ----------------------------------------------------------------

async def click(session, selector: str) -> str:
    await session.page().click(selector, timeout=15_000)
    return f"clicked {selector}"


async def click_at(session, x: float, y: float, hold_seconds: float = 0.0) -> bytes:
    """Click (or press-and-hold) a raw viewport coordinate instead of a
    selector - for targets a selector cannot reliably reach: a slider track, a
    canvas-drawn captcha, or a precise point inside a wider element. Moves the
    pointer there first (no teleport), then down, then - if hold_seconds is 0 -
    immediately up (a plain click); otherwise waits before releasing.

    Returns a screenshot taken right after release, so the result of the click
    is visible without a second round-trip.
    """
    page = session.page()
    await page.mouse.move(x, y, steps=12)
    await page.mouse.down()
    if hold_seconds > 0:
        await page.wait_for_timeout(int(hold_seconds * 1000))
    await page.mouse.up()
    # Give a post-click transition (checkmark, redirect, reflow) a moment to
    # start before the screenshot, so it reflects the outcome, not the click.
    await page.wait_for_timeout(400)
    return await page.screenshot()


async def type_text(session, selector: str, text: str) -> str:
    await session.page().fill(selector, text, timeout=15_000)
    return f"typed into {selector}"


async def press_key(session, key: str) -> str:
    await session.page().keyboard.press(key)
    return f"pressed {key}"


async def evaluate(session, expression: str) -> str:
    return json_capped(await session.page().evaluate(expression))
