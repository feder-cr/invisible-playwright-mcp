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

`browser_read_html` returns the page's markup instead of a flat list, for when
the structure is what matters: a form and its labels, a table, what a control is
wired to. The browser decides what is actually painted, on a clone of the
document so the live page is never written to, and the markup is then reduced to
what is worth reading. Measured on real pages, 8.9 MB of markup became 223 KB
with every one of the 1,204 interactive elements still present. `mode`
is `form` (the interactive surface and the text explaining it), `text` (the prose
alone) or `full` (the structure, with the noise and the attribute soup gone).

Tool names mirror the Microsoft Playwright MCP, so prompts written for it work here too.

## Notes

- **Bring your own proxy.** The engine does the stealth; a residential proxy gives you the matching IP and geography. Without one it still runs, but the exit is your own address.
- This is a browser, not a captcha solver. It does not solve or bypass challenges for you; it makes an ordinary Firefox session look like a real one.

## License

See the engine project, [`invisible-playwright`](https://github.com/feder-cr/invisible_playwright).
