# invisible-playwright-mcp

A stealth Firefox, exposed as an [MCP](https://modelcontextprotocol.io) server, so
an AI agent can browse and act on real websites without being blocked by anti-bot
systems.

It wraps [`invisible-playwright`](https://github.com/feder-cr/invisible_playwright),
a real Firefox patched at the C++ source, and hands your client the usual browser
tools: navigate, click, type, read, screenshot. The fingerprint is set inside the
engine, not bolted onto the page.

## First, one prerequisite

**Python 3.11 or newer**, on **Windows (x86_64) or Linux (x86_64, arm64)** - macOS
is not supported, the last engine build for it was `firefox-20`. Then
[uv](https://docs.astral.sh/uv/), because the command below starts with `uvx`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh              # Linux
```
```powershell
irm https://astral.sh/uv/install.ps1 | iex                   # Windows
```

## Then pick one

**Do you already use an AI assistant that can run tools?** If yes, it brings the
model and you add this browser to it. If no, or if you would rather watch the work
happen, there is an interface that brings a model too.

<table>
<tr>
<th width="50%">1. Add it to the assistant you have</th>
<th width="50%">2. Run the interface instead</th>
</tr>
<tr>
<td valign="top">

**This package.** Your assistant brings the model.

Claude Code, once for every project on the machine:

```bash
claude mcp add -s user stealth -- uvx invisible-playwright-mcp
```

Drop `-s user` if you want it in the current project only.

Check it took, before trusting it:

```bash
claude mcp list
```

For Claude Desktop, Cursor and the rest, see **Config file** below.

</td>
<td valign="top">

**[AIHawk](https://github.com/feder-cr/AIHawk).** No assistant needed. Bring an
[OpenRouter](https://openrouter.ai) account and its key, get a page with the chat
on the left and the live browser on the right.

```bash
uvx aihawk ui --openrouter-key sk-or-...
```

Open **http://127.0.0.1:8765**.

It is a client of this server like any other, with no private path to the page -
which is the reason to believe the tools below are enough to build on.

</td>
</tr>
</table>

## The download nobody warns you about

The browser is about a quarter of a gigabyte and it is **not** fetched when the
server is installed, nor when it starts. It arrives on the **first tool call that
needs a page**, so the first thing you ask your assistant to do sits there, and on
a slow connection you get a timeout that says nothing about a download.

Get it over with first, in a terminal where you can watch it:

```bash
uvx invisible-playwright fetch
```

Cached afterwards, and shared with anything else that uses this engine.
Per-platform sizes are in the
[engine's README](https://github.com/feder-cr/invisible_playwright).

## Config file

For any client that takes a JSON block rather than a command:

```json
{
  "mcpServers": {
    "stealth": {
      "command": "uvx",
      "args": ["invisible-playwright-mcp"]
    }
  }
}
```

Where it goes:

| Client | File |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `~/.cursor/mcp.json`, or `.cursor/mcp.json` in the project |
| Claude Code | `~/.claude.json`, but use `claude mcp add` above instead |

Settings from the table below go in the same block, under `env`:

```json
{
  "mcpServers": {
    "stealth": {
      "command": "uvx",
      "args": ["invisible-playwright-mcp"],
      "env": {
        "STEALTHFOX_PROXY": "http://user:pass@proxy.example.com:8080",
        "STEALTHFOX_SEED": "4242"
      }
    }
  }
}
```

## Settings

Environment variables, all optional. A proxy is the one worth adding: without it
the exit IP, timezone and locale are your own machine's, which is a real gap
between what the browser says it is and where it appears to be.

| Variable | Meaning |
|---|---|
| `STEALTHFOX_PROXY` | Proxy URL, e.g. `http://user:pass@proxy.example.com:8080` or `socks5://proxy.example.com:1080`. Host and port are both required. Bring your own. With it set, the session's timezone, locale and egress are derived from the proxy. |
| `STEALTHFOX_SEED` | Integer seed for a deterministic fingerprint (same seed, same identity). |
| `STEALTHFOX_PROFILE_DIR` | A directory for a persistent profile, so logins survive across runs. |
| `STEALTHFOX_BINARY` | Path to an engine binary you already have. It must be the build the packaged seal pins, or startup refuses. |
| `STEALTHFOX_HEADLESS` | `0` to run headed; headless by default. |
| `STEALTHFOX_MCP_TRANSPORT` | `http` to serve over streamable HTTP instead of stdio. Default is stdio, which is what MCP clients expect. |
| `STEALTHFOX_MCP_HOST` | Bind address for the HTTP transport. Default `127.0.0.1`. |
| `STEALTHFOX_MCP_PORT` | Port for the HTTP transport. Default `8765`, which is also the AIHawk interface's default: change one of the two if you run both. |

## Tools

`session_new_page`, `session_list_pages`, `session_select_page`, `session_close_page`, `browser_navigate`, `browser_read_text`, `browser_snapshot`, `browser_read_html`, `browser_click`, `browser_click_at`, `browser_type`, `browser_press_key`, `browser_evaluate`, `browser_take_screenshot`, `browser_select_option`.

### The order to try them in

The server hands every client this ladder, because a model that cannot find a
way down it invents one:

1. **A named tool with a selector** - `browser_click`, `browser_type`,
   `browser_select_option`, `browser_press_key`. `browser_snapshot` supplies the
   selector.
2. **Coordinates** - the snapshot reports `at: [x, y]` for every element, and
   `browser_click_at` moves the pointer there. For a canvas, a slider, a map, a
   widget built out of divs.
3. **A screenshot** - `browser_take_screenshot`, then `browser_click_at` on what
   you can see. For what the snapshot does not list at all.
4. **`browser_evaluate`**, to READ what none of the above can see.

`browser_evaluate` reads; it will not act. Assigning to `value`, `checked` or
`selected`, or calling `click()`, `dispatchEvent()` or `submit()`, is refused,
and the refusal names the tool to use instead. Script reaches the page with no
keystroke and no pointer, so the event carries `isTrusted` false, which is the
clearest signal a page can collect that nobody is really there. Reading those
properties is fine.


`browser_click_at` takes viewport coordinates instead of a selector, moves the
pointer there rather than teleporting, and optionally holds before releasing -
for a slider, a canvas-drawn challenge, or a press-and-hold.

`browser_snapshot` returns the title, the url and the visible interactive
elements rather than the accessibility tree. Every element carries `at: [x, y]`,
its centre in the viewport, and a `selector` as well when one can reach it -
pass that straight to `browser_click` or `browser_type`. `browser_read_html`
returns reduced markup instead, for when the structure is what matters.

Tool names mirror the Microsoft Playwright MCP, so prompts written for it work
here too.

**Why each of those returns what it does**, with the measurements behind it:
[docs/tool-design.md](docs/tool-design.md).

## More than one client on the same browser

Over stdio the browser belongs to the client that opened it. Set
`STEALTHFOX_MCP_TRANSPORT=http` and it does not: the session is owned by the
server, so a second client can attach to the browser the first one left open,
and closing a client no longer kills the browser.

To SEE the browser rather than share it, use
[AIHawk](https://github.com/feder-cr/AIHawk) from column 2, which shows the live
page beside the conversation.

```bash
STEALTHFOX_MCP_TRANSPORT=http uvx invisible-playwright-mcp        # Linux
```
```powershell
$env:STEALTHFOX_MCP_TRANSPORT = "http"; uvx invisible-playwright-mcp   # Windows
```

## Notes

- This is a browser, not a captcha solver. It does not solve or bypass challenges for you; it makes an ordinary Firefox session look like a real one.

## License

[MIT](https://github.com/feder-cr/invisible-playwright-mcp/blob/main/LICENSE),
the same as the engine it wraps.
