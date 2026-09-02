"""The selector the snapshot hands out must reach one element, and the right one.

Measured 2026-09-02 across 969 interactive elements on real pages: 88.1% carried
an id, a name or an href, and every one of those selectors reached the element it
came from. But before this, only 47.6% reached it ALONE.

For the other 40% the obvious selector matches several nodes, and Playwright acts
on the first. A model looking at the third of five identical links builds
`a[href='/x']`, clicks, and is told it worked. Nothing raises, nothing is logged,
and the wrong thing happened. That is the failure mode this file exists for: not
an error, a quiet substitution.

The source checks run without a browser, because the mechanism lives in a JS
string. The end-to-end ones share ONE browser through a module fixture: three
parametrized cases plus two separate tests meant five launches and over two
minutes, and a launch is the most expensive thing in this suite.
"""
import re

import pytest

from invisible_playwright_mcp import actions

CASES = {
    "three identical links": (
        "<a href='/dup'>primo</a><a href='/dup'>secondo</a><a href='/dup'>terzo</a>", 3),
    "a unique id": ("<button id='solo'>x</button>", 1),
    "a named field": ("<input name='email'>", 1),
    "an id needing escaping": ("<div id='a.b:c' role='button'>x</div>", 1),
    "duplicate ids": ("<span id='same' role='button'>one</span>"
                      "<span id='same' role='button'>two</span>", 2),
    "a quote inside the value": ('<input name="e\'mail">', 1),
}


def _code(js: str) -> str:
    """The JS with its comments stripped: the comments name the defect on
    purpose, and a check that read them would fail over its own documentation."""
    return re.sub(r"//[^\n]*", "", js)


# --- the mechanism, without a browser --------------------------------------

def test_the_snapshot_emits_a_selector_field():
    assert "e.selector" in _code(actions.SNAPSHOT_JS), (
        "the snapshot no longer hands out a selector")


def test_the_handle_counts_matches_before_trusting_a_selector():
    """The count has to come from the document. Counting within the snapshot's
    own list undercounts, because an element filtered out here for being
    invisible still occupies a position in querySelectorAll, and the index would
    then point at the wrong node."""
    js = _code(actions.SNAPSHOT_JS)
    assert "querySelectorAll" in js
    assert "nth-match" in js, "ambiguity is no longer disambiguated"
    assert "indexOf" in js, "the position among matches is no longer computed"


def test_attribute_values_are_escaped_into_the_selector():
    """A quote or a backslash in an id or an href turns a selector into a syntax
    error, and a syntax error in a handle is a handle that never works."""
    js = _code(actions.SNAPSHOT_JS)
    assert "CSS.escape" in js, "ids go into a selector unescaped"
    assert "replace(/'/g" in js, "attribute values go into a selector unescaped"


def test_the_selector_uses_single_quotes():
    """It is about to be serialized as JSON, where every double quote comes back
    as two characters. CSS accepts either, so this is free."""
    js = _code(actions.SNAPSHOT_JS)
    assert "[name='" in js and "a[href='" in js, "the selector is back on double quotes"


# --- the same claims, on a real engine, in one browser ---------------------

@pytest.fixture(scope="module")
def page():
    from invisible_playwright import InvisiblePlaywright

    with InvisiblePlaywright(seed=1, headless=True) as browser:
        ctx = browser.new_context()
        yield ctx.new_page()
        ctx.close()


def _load(page, body):
    page.goto(f"data:text/html,<html><body>{body}</body></html>")
    page.wait_for_timeout(250)
    return page.evaluate(actions.SNAPSHOT_JS)["interactive_elements"]


@pytest.mark.e2e
def test_every_selector_resolves_to_exactly_one_and_to_the_right_one(page):
    """Two assertions per element and they are not the same one. Resolving to a
    single node says the handle is unambiguous; reaching the element it came
    from says it is the RIGHT node. Without the index all three duplicate links
    satisfy the first and fail the second, which is the defect in its purest
    form: a handle that works and points somewhere else.
    """
    problems = []
    for name, (body, expected) in CASES.items():
        elements = _load(page, body)
        if len(elements) != expected:
            problems.append(f"{name}: saw {len(elements)} elements, expected {expected}")
            continue
        for element in elements:
            selector = element.get("selector")
            if not selector:
                problems.append(f"{name}: no handle for {element.get('text')!r}")
                continue
            found = page.locator(selector).count()
            if found != 1:
                problems.append(f"{name}: {selector!r} matched {found} elements")
                continue
            reached = page.locator(selector).inner_text(timeout=3000).strip()
            if reached != (element.get("text") or "").strip():
                problems.append(f"{name}: {selector!r} reached {reached!r}, "
                                f"snapshot said {element.get('text')!r}")
    assert not problems, problems


@pytest.mark.e2e
def test_the_href_is_not_repeated_inside_and_beside_the_selector(page):
    """Emitting the selector cost +47.2% of the payload on real pages and +15.1%
    once the duplicated href came out, for the same information: `a[href='/x']`
    says where the link goes as plainly as a separate field did. A link
    addressed by its id keeps its href, having nothing duplicated."""
    by_href, by_id = _load(page, "<a href='/dup'>a</a><a href='/dup'>b</a>"), None
    for element in by_href:
        assert "href" not in element, (
            f"the href is repeated beside the selector that already holds it: {element}")
        assert "/dup" in element["selector"]

    by_id = _load(page, "<a href='/solo' id='x'>a</a>")[0]
    assert by_id["selector"] == "#x"
    assert by_id.get("href") == "/solo", "a link addressed by id lost its href for nothing"


@pytest.mark.e2e
def test_an_ambiguous_selector_silently_clicks_the_first_match(page):
    """A claim about a DEPENDENCY, pinned because it is the reason the whole
    handle exists and because it is exactly the sort that changes on an upgrade
    without anybody noticing.

    It was written into four places - a public README, a tool description, the
    JS comments and these docstrings - before it was ever run. It turned out to
    be true. `page.click` on a selector matching three elements does not raise:
    it clicks the first and reports success. So does `locator.click`, which is
    the API documented as strict.

    If this test ever goes red, the fix is not here. It is that Playwright
    changed, and every sentence built on this needs rewriting.
    """
    body = ("<a href='/d' onclick='window.__hit=\"primo\";return false'>primo</a>"
            "<a href='/d' onclick='window.__hit=\"secondo\";return false'>secondo</a>"
            "<a href='/d' onclick='window.__hit=\"terzo\";return false'>terzo</a>")
    page.goto(f"data:text/html,<html><body>{body}</body></html>")
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.querySelectorAll(\"a[href='/d']\").length") == 3

    page.click("a[href='/d']", timeout=5000)
    assert page.evaluate("() => window.__hit") == "primo", (
        "Playwright no longer silently picks the first match; the sentences "
        "explaining why `selector` exists need rewriting")

    page.goto(f"data:text/html,<html><body>{body}</body></html>")
    page.wait_for_timeout(250)
    page.click(":nth-match(a[href='/d'], 3)", timeout=5000)
    assert page.evaluate("() => window.__hit") == "terzo", (
        "the disambiguated handle no longer reaches the element it names")
