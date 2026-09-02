# invisible-playwright-mcp

A stealth Firefox browser, exposed as an [MCP](https://modelcontextprotocol.io) server, so any AI agent can browse and act on real websites without being blocked by anti-bot systems.

It wraps [`invisible-playwright`](https://github.com/feder-cr/invisible_playwright) (a real Firefox patched at the C++ source for stealth) and hands your MCP client the usual browser tools: navigate, click, type, read, screenshot. The browser is always launched by the stealth engine, so the fingerprint is set inside the engine, not bolted on.

## Install (Claude Code)

One line:

```bash
claude mcp add stealth --env STEALTHFOX_PROXY=http://user:pass@host:port -- uvx invisible-playwright-mcp
```

Or add it to any MCP client via a config block (Claude Code, Cursor, Claude Desktop):

```json
{
  "mcpServers": {
    "stealth": {
      "command": "uvx",
      "args": ["invisible-playwright-mcp"],
      "env": { "STEALTHFOX_PROXY": "http://user:pass@host:port" }
    }
  }
}
```

`uvx` downloads and runs it in one step; no manual install. The stealth Firefox engine is fetched automatically on first use.

## Configuration (environment variables)

| Variable | Meaning |
|---|---|
| `STEALTHFOX_PROXY` | Your proxy URL (`http://…`, `https://…` or `socks5://…`). Bring your own. With it set, the session's timezone, locale and egress are derived from the proxy automatically. |
| `STEALTHFOX_SEED` | Integer seed for a deterministic fingerprint (same seed, same identity). |
| `STEALTHFOX_PROFILE_DIR` | A directory for a persistent profile, so logins survive across runs. |
| `STEALTHFOX_BINARY` | Path to a specific engine binary (otherwise fetched automatically). |
| `STEALTHFOX_HEADLESS` | `0` to run headed; headless by default. |
| `STEALTHFOX_MCP_TRANSPORT` | `http` to serve over streamable HTTP instead of stdio. Default is stdio, which is what MCP clients expect. |
| `STEALTHFOX_MCP_HOST` | Bind address for the HTTP transport. Default `127.0.0.1`. |
| `STEALTHFOX_MCP_PORT` | Port for the HTTP transport. Default `8765`. |

## Tools

`session_new_page`, `session_list_pages`, `session_select_page`, `session_close_page`, `browser_navigate`, `browser_read_text`, `browser_snapshot`, `browser_read_html`, `browser_click`, `browser_click_at`, `browser_type`, `browser_press_key`, `browser_evaluate`, `browser_take_screenshot`.

`browser_click_at` takes viewport coordinates instead of a selector, moves the
pointer there rather than teleporting, optionally holds before releasing, and
returns a screenshot of what happened - for a slider, a canvas-drawn challenge,
or a press-and-hold.

`browser_snapshot` returns the title, the url and the visible interactive
elements rather than the accessibility tree: one country `<select>` on a real
sign-up page contributes about two hundred `<option>` nodes, which fill the
character budget before the form does.

Each element comes with a `selector` when one can reach it, and that string goes
to `browser_click` or `browser_type` verbatim. It is built to match exactly one
element, which the obvious selector often does not: measured across 958 elements
on real pages, 88% could be addressed but only 48% unambiguously, and Playwright
acts on the first match without complaining, so aiming at the third of five
identical links quietly hit the first. Elements no selector can reach carry `at`
instead, the centre coordinates, for `browser_click_at`.

When a click does not land, the error says what stopped it rather than only that
it timed out: an element covering the target is named, with its id, its class and
its text, because the next move is to deal with that thing and not to retry. If
the page has replaced `getBoundingClientRect` so that nothing can be measured,
the snapshot reports `unmeasurable` with a count instead of an empty list, so a
tampered page cannot be mistaken for a page with no controls.

When an element has none of those, the selector falls back to `data-testid` and
then to a unique `aria-label`, which together took coverage from 90.5% of
elements to 97.9%. It stops there: a text-based selector is not stable, and a
handle that sometimes points elsewhere is the thing this exists to remove. What
is left carries `at` and nothing else.

A link addressed by its href has no separate `href` field, because the selector
already holds it: `a[href='/cart']` says where the link goes as plainly as the
field did, and not repeating it is what kept this affordable (+47% of the
payload with the repetition, +15% without). A link addressed by its id keeps its
href, having nothing duplicated.

`browser_read_html` returns the page's markup instead of a flat list, for when
the structure is what matters: a form and its labels, a table, what a control is
wired to. The browser decides what is actually painted, on a clone of the
document so the live page is never written to, and the markup is then reduced to
what is worth reading. Measured on real pages, 9.6 MB of markup became 293 KB
with every one of the 1,453 interactive elements still present. `mode`
is `form` (the interactive surface and the text explaining it), `text` (the prose
alone) or `full` (the structure, with the noise and the attribute soup gone).

Tool names mirror the Microsoft Playwright MCP, so prompts written for it work here too.

## Watching it work, and more than one client

Over stdio the browser belongs to the client that opened it. Set
`STEALTHFOX_MCP_TRANSPORT=http` and it does not: the session is owned by the
server, so a second client can attach to the browser the first one left open,
and closing a client no longer kills the browser.

    STEALTHFOX_MCP_TRANSPORT=http uvx invisible-playwright-mcp

## Something to watch it with

This package used to serve two pages of its own: a live view of the browser and a
two-pane chat. Since 0.9.0 it does not. They are in
[`aihawk`](https://github.com/feder-cr/AIHawk), which brings a model as well, and
which reaches the browser through the tools above rather than through anything
private.

The move is worth a sentence because it is a promise about this package. Nothing
here has a privileged path to the page any more, so the fourteen tools are enough
to build an interface on - and that is not an assertion, it is how the interface
that exists is built. A page kept inside the server is a page whose needs quietly
become the server's requirements.

## Notes

- **Bring your own proxy.** The engine does the stealth; a residential proxy gives you the matching IP and geography. Without one it still runs, but the exit is your own address.
- This is a browser, not a captcha solver. It does not solve or bypass challenges for you; it makes an ordinary Firefox session look like a real one.

## License

See the engine project, [`invisible-playwright`](https://github.com/feder-cr/invisible_playwright).
