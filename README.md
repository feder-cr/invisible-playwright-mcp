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

### 1. Add it to the assistant you have

Claude Code:

```bash
claude mcp add --scope user stealth -- uvx invisible-playwright-mcp
```

Then check it took, before trusting it:

```bash
claude mcp list
```

For every other client, see **Adding it to your client** below.

### 2. Run the interface instead

**[AIHawk](https://github.com/feder-cr/AIHawk).** Bring an
[OpenRouter](https://openrouter.ai) account and its key, get a page with the chat
on the left and the live browser on the right.

```bash
uvx aihawk ui --openrouter-key sk-or-...
```

Open **http://127.0.0.1:8765**.

It is a client of this server like any other, with no private path to the page -
which is the reason to believe the tools below are enough to build on.

## The browser downloads itself

The browser is about a quarter of a gigabyte and it is **not** inside the
package. The server starts fetching it the moment it starts. Claude Code starts
its servers when a session opens, so there the engine is usually on disk before
you have finished typing your first request; a client that starts the server at
the first request has that request wait for the download, and nothing else
happens. Cached afterwards, and shared with anything else that uses this engine.

To have it on disk before any of that, in a Docker image or a CI cache:

```bash
invisible-playwright fetch
```

Per-platform sizes are in the
[engine's README](https://github.com/feder-cr/invisible_playwright).

## Adding it to your client

Four clients have a command for this. The rest take a config file, and the file
is not the same everywhere: **three different top-level keys, and one of them is
not even JSON.** Find yours below.

### If your client has a command

**Claude Code.** `--scope user` because the default scope is the current project, so
without it the tools do not appear anywhere else and nothing reports an error:

```bash
claude mcp add --scope user stealth -- uvx invisible-playwright-mcp
```

**Codex:**

```bash
codex mcp add stealth -- uvx invisible-playwright-mcp
```

**Gemini CLI.** No `--` separator here, unlike the two above:

```bash
gemini mcp add --scope user stealth uvx invisible-playwright-mcp
```

**VS Code** (GitHub Copilot agent mode):

```bash
code --add-mcp "{\"name\":\"stealth\",\"command\":\"uvx\",\"args\":[\"invisible-playwright-mcp\"]}"
```

### If your client takes a config file

**Most use a top-level `mcpServers`** - Claude Desktop, Cursor, Windsurf, Cline:

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

| Client | File |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `.cursor/mcp.json` in the project, or `~/.cursor/mcp.json` for every project |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Cline | `~/.cline/data/settings/cline_mcp_settings.json`, or the **Configure MCP Servers** button in its MCP panel, which opens whichever file your version uses |

**Zed calls the key `context_servers`**, not `mcpServers`, in
`~/.config/zed/settings.json` (`%APPDATA%\Zed\settings.json` on Windows):

```json
{
  "context_servers": {
    "stealth": {
      "command": "uvx",
      "args": ["invisible-playwright-mcp"]
    }
  }
}
```

**VS Code calls it `servers`**, in `.vscode/mcp.json` for a workspace:

```json
{
  "servers": {
    "stealth": {
      "type": "stdio",
      "command": "uvx",
      "args": ["invisible-playwright-mcp"]
    }
  }
}
```

**Codex uses TOML**, in `~/.codex/config.toml`:

```toml
[mcp_servers.stealth]
command = "uvx"
args = ["invisible-playwright-mcp"]
```

**Continue** uses YAML with its own block format, which changed recently enough
that we would rather point you at
[their documentation](https://docs.continue.dev/customize/deep-dives/mcp) than
print a block here that may already be stale.

### Where a proxy and the other settings go

Everything in **Settings** below goes under `env` on the server entry, in
whatever shape your client uses:

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

In Codex's TOML that is a `[mcp_servers.stealth.env]` table; on the command line,
Claude Code and Codex take `-e KEY=value` and `--env KEY=value`.

⛔ **"Added" is not "connected".** Every one of these writes a config entry
without running anything, so a typo, a missing `uv`, or the first-run browser
download all surface later as a server that will not start. Check before you
trust it: `claude mcp list`, `codex mcp list`, or your client's MCP panel.

## Settings

Environment variables, all optional. A proxy is the one worth adding: without it
the exit IP, timezone and locale are your own machine's, which is a real gap
between what the browser says it is and where it appears to be.

| Variable | Meaning |
|---|---|
| `STEALTHFOX_PROXY` | Proxy URL, e.g. `http://user:pass@proxy.example.com:8080` or `socks5://proxy.example.com:1080`. Host and port are both required. Bring your own. With it set, the session's timezone, locale and egress are derived from the proxy. |
| `STEALTHFOX_NO_PROXY` | `1` to go out from this machine's own address even when `STEALTHFOX_PROXY` is set. |
| `STEALTHFOX_SEED` | Integer seed for a deterministic fingerprint (same seed, same identity). A profile's own seed wins over this one. |
| `STEALTHFOX_PROFILE_DIR` | A directory for a persistent profile, so logins survive across runs. |
| `STEALTHFOX_BINARY` | Path to an engine binary you already have. It must be the build the packaged seal pins, or startup refuses. |
| `STEALTHFOX_HEADLESS` | `0` to run headed; headless by default. |
| `STEALTHFOX_MCP_TRANSPORT` | `http` to serve over streamable HTTP instead of stdio. Default is stdio, which is what MCP clients expect. |
| `STEALTHFOX_MCP_HOST` | Bind address for the HTTP transport. Default `127.0.0.1`. |
| `STEALTHFOX_MCP_PORT` | Port for the HTTP transport. Default `8765`, which is also the AIHawk interface's default: change one of the two if you run both. |

## Tools

`session_start`, `session_status`, `session_new_page`, `session_list_pages`, `session_select_page`, `session_close_page`, `browser_navigate`, `browser_read_text`, `browser_snapshot`, `browser_read_html`, `browser_click`, `browser_click_at`, `browser_type`, `browser_press_key`, `browser_evaluate`, `browser_take_screenshot`, `browser_select_option`.

### Who is browsing

You can ignore this entirely. Say nothing and every session is a different
stranger, which is the right default.

When you do care, `session_start` chooses the person and `session_status` tells
you who you currently are. There is one browser, so two identities are visited
in turn rather than at once.

- **`seed`** is the identity. The same seed is the same fingerprint every time.
  Leave it out and one is drawn for you, and the answer says which, so a session
  worth repeating can be repeated.
- **`profile`** is a directory holding cookies and logins. **A profile also owns
  its seed**: the first session on a new one stores the identity inside it and
  every session after reuses it, so a login never comes back wearing different
  hardware. Ask for a seed that contradicts the one a profile carries and you get
  a refusal naming both numbers, never a silent choice between them.
- **`proxy`** is where the traffic leaves. Pass `""` to either of the last two to
  insist on *none*, which is how you get sessions a site cannot link together
  even when the environment sets a default.

**A profile does not own its exit the way it owns its seed.** Timezone, locale
and geography come from the exit, so the same login arriving from another country
is as visible as one arriving on different hardware. You are warned when a
profile's exit changes - but only when *you* change it. A provider rotating its
own addresses behind one host and port is indistinguishable from here, and no
warning should be read as saying otherwise.

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
