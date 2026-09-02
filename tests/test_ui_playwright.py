"""The UI tested by driving it, not by reading it.

Opens the two-pane shell in a real browser, types into the chat, and checks that
the conversation fills up and that the right pane loads the view.

The browser driving the test is the same one the product drives: if the UI
breaks under invisible_playwright, it breaks for whoever uses it.

Marked `e2e` because it starts two real processes (the server and a browser) and
downloads the engine the first time. It skips itself when the server is not
listening, so the ordinary suite stays fast and does not pretend to have tested
something.
"""
import os
import socket

import pytest

URL = os.environ.get("AIHAWK_UI_URL", "http://127.0.0.1:8765/")


def _server_listening(url: str) -> bool:
    from urllib.parse import urlparse
    u = urlparse(url)
    try:
        with socket.create_connection((u.hostname, u.port or 80), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _server_listening(URL),
                       reason=f"no server on {URL}; start one with STEALTHFOX_MCP_TRANSPORT=http"),
]


@pytest.fixture(scope="module")
def page():
    from invisible_playwright import InvisiblePlaywright
    with InvisiblePlaywright(seed=4242, headless=True) as browser:
        ctx = browser.new_context()
        pg = ctx.new_page()
        pg.goto(URL, wait_until="load", timeout=30_000)
        yield pg
        ctx.close()


def test_both_panes_are_there(page):
    """The shell: the chat column, the input, and the frame on the right."""
    assert page.locator("#log").count() == 1
    assert page.locator("#i").count() == 1
    assert page.locator("iframe").count() == 1
    src = page.locator("iframe").get_attribute("src")
    assert src and "live" in src


def test_the_right_pane_loads_the_view(page):
    """The iframe must actually serve the view page, not a 404."""
    frame = page.frame_locator("iframe")
    assert frame.locator("#f, #empty").count() >= 1


def test_the_view_really_takes_a_frame(page):
    """That the iframe exists says nothing.

    Measured: the five preceding tests were all green while the right pane
    showed `error 404` on every poll. The view page asked for `frame` RELATIVE,
    which from `/live` resolves to `/frame` and does not exist. No assertion
    about structure could see that: you have to look at what the state says and
    whether the image has any pixels.
    """
    page.fill("#i", "go https://example.com")
    page.press("#i", "Enter")

    # Wait for the CONDITION, not for a duration. A fixed wait is fragile by
    # construction: on a freshly restarted server the session does not exist yet
    # and Firefox has to be born, so the first frame can arrive much later than
    # it does on a warm browser. A test that picks a number reports a product
    # defect every time the machine is slow.
    def view_frame():
        # Reached through the frame directly rather than through
        # `frame_locator`, which raises "Cannot find object with id" on this
        # client - a defect of its own, not of the page.
        v = [x for x in page.frames if x.url.rstrip("/").endswith("/live")]
        return v[0] if v else None

    # A SINGLE error is not a defect: `live.py` states that a screenshot asked
    # for mid-navigation fails routinely and answers 503 on purpose, so the view
    # does not fall over. Asserting "no poll ever errors" turned this test into a
    # measure of network speed - it passed on an idle machine and failed 4 times
    # out of 4 after a heavy bench, with nothing in the product changed.
    #
    # What the test must demand is that the view REACHES a frame. A PERSISTENT
    # error prevents that, and it is exactly the shape of the defect this test
    # was born from: `error 404` on every poll, forever.
    # No early exit on a run of errors, and that is a correction rather than an
    # omission. A first version failed after eight consecutive error polls,
    # which is a load-sensitive constant: on a busy machine a single navigation
    # produces more than eight failed frames at one every 400ms, so the test
    # went red over the CPU rather than over the product. It passed alone and
    # failed inside the full suite.
    #
    # It also bought nothing. The loop below already fails when the view never
    # reaches `live`, which is exactly what a persistent error does, and that is
    # the defect this test was born from: `error 404` on every poll, forever.
    # The only thing the counter added was a clearer message, and that is kept
    # by reporting the last state seen.
    state = "connecting"
    for _ in range(60):
        page.wait_for_timeout(1_000)
        f = view_frame()
        if f is None:
            continue
        state = f.evaluate("() => document.getElementById('state').textContent")
        if state == "live":
            break
    else:
        raise AssertionError(f"no frame after 60s; last state: {state}")

    f = view_frame()

    width = f.evaluate("() => document.getElementById('f').naturalWidth")
    assert width and width > 0, "the view image has no pixels"

    # And it must be VISIBLE. `naturalWidth` is true even on a display:none
    # element, and that is exactly how the pane stayed black while the state
    # said `live` and the tests passed: the code did `style.display = ''`, which
    # removes the inline style and falls back on the stylesheet rule, which was
    # `none`.
    box = f.evaluate("""() => {
        const i = document.getElementById('f');
        const r = i.getBoundingClientRect();
        return {w: Math.round(r.width), h: Math.round(r.height),
                display: getComputedStyle(i).display};
    }""")
    assert box["display"] != "none", "the image is there but CSS is hiding it"
    assert box["w"] > 100 and box["h"] > 100, f"the image takes up no space: {box}"


def test_no_view_request_ends_in_a_404(page):
    """The defect in direct form: the responses are watched, not the appearance."""
    failed = []
    page.on("response", lambda r: failed.append(r.url) if r.status == 404 and "frame" in r.url else None)
    page.wait_for_timeout(3_000)
    assert not failed, f"the view asks for a path that does not exist: {failed[:2]}"


def test_a_typed_line_appears_in_the_conversation(page):
    """The shell's full loop: type, send, and the conversation grows."""
    before = page.locator("#log .msg").count()
    page.fill("#i", "this is a test")
    page.press("#i", "Enter")
    page.wait_for_function(
        "n => document.querySelectorAll('#log .msg').length > n",
        arg=before, timeout=15_000,
    )
    text = page.locator("#log").inner_text()
    assert "this is a test" in text


def test_the_stub_says_it_is_a_stub(page):
    """Whoever is watching must be able to tell there is no model yet.

    It is why the stub answers the way it does: a placeholder dressed as an
    agent is the thing that demos well and that nobody can build on.
    """
    page.fill("#i", "find me a flight to Lisbon under 200 euros")
    page.press("#i", "Enter")
    page.wait_for_function(
        "() => document.querySelector('#log').innerText.toLowerCase().includes('placeholder')",
        timeout=15_000,
    )


def test_the_input_clears_after_sending(page):
    """Small, but it is the defect anyone notices on their second message."""
    page.fill("#i", "hello")
    page.press("#i", "Enter")
    page.wait_for_function("() => document.querySelector('#i').value === ''", timeout=5_000)
