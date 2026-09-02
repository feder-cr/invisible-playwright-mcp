"""The README describes this package. These check that it still describes THIS one.

Written 2026-09-02, after finding that the HTTP transport, the live view and the
two-pane chat had shipped in 0.4.0 and were named nowhere in the README. Three
environment variables and two whole pages that a user had no way to discover: not
broken, just invisible, which is the same thing from the outside.

Documentation drift is silent by construction. Nothing fails, nothing is red, and
the gap only surfaces when somebody asks for a feature that has been there for a
month. So the two facts most likely to drift are checked against the code that
defines them rather than against anybody's memory.
"""
from __future__ import annotations

import pathlib
import re

README = pathlib.Path(__file__).resolve().parents[1] / "README.md"
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "invisible_playwright_mcp"


def test_the_readme_lists_the_commands_the_stub_understands():
    """The placeholder's command list lives in one string in chat.py. When it
    grows, the README is the thing nobody remembers to move."""
    from invisible_playwright_mcp.chat import LiteralBrain

    commands = set(re.findall(r"`(\w+)[^`]*`", LiteralBrain.HELP))
    assert commands, "LiteralBrain.HELP no longer lists its commands in backticks"
    text = README.read_text(encoding="utf-8")
    missing = sorted(c for c in commands if f"`{c}" not in text)
    assert not missing, f"the stub understands these and the README does not mention them: {missing}"


def test_every_environment_variable_the_code_reads_is_documented():
    """Three of these were undocumented for a release: the HTTP transport and
    its host and port, which is the whole multi-client story.

    Reads the source rather than importing, because the variables are consulted
    at call time in several modules and a name that no test path reaches would
    otherwise be invisible here too.
    """
    used = set()
    for path in sorted(SRC.glob("*.py")):
        body = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"""["'](STEALTHFOX_[A-Z0-9_]+)["']""", body))
    assert used, "no STEALTHFOX_* variable found in the source; has the prefix changed?"

    text = README.read_text(encoding="utf-8")
    missing = sorted(name for name in used if name not in text)
    assert not missing, f"read by the code, absent from the README: {missing}"


def _listed_tools() -> set:
    """The names in the LIST, not the names in the section.

    Two versions of this survived their mutation before this one killed it.
    Searching the whole README failed because a deleted tool was still named in
    a paragraph further down. Narrowing to the Tools section failed for the same
    reason at a smaller scale: that section holds the list AND the prose about
    it. A name mentioned in passing is not a listed tool, and the only thing
    that separates the two is looking at the list itself.
    """
    text = README.read_text(encoding="utf-8")
    start = text.index("## Tools")
    rest = text[start + len("## Tools"):]
    end = rest.find(chr(10) + "## ")
    section = rest if end < 0 else rest[:end]
    # The list is the paragraph with the most backticked names in it.
    best = max((p for p in section.split(chr(10) * 2)),
               key=lambda p: len(re.findall(r"`(\w+)`", p)), default="")
    return set(re.findall(r"`(\w+)`", best))


def test_the_readme_names_every_tool_the_server_registers():
    """A tool nobody can find is a tool nobody uses. This is how the fourteenth
    was noticed, and by hand."""
    import asyncio

    from invisible_playwright_mcp import server

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    listed = _listed_tools()
    missing = sorted(names - listed)
    assert not missing, f"registered but not in the tool list under ## Tools: {missing}"
