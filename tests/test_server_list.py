import pytest


@pytest.mark.asyncio
async def test_server_registers_expected_tools():
    from invisible_playwright_mcp import server
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "session_new_page", "session_list_pages", "session_select_page",
        "session_close_page", "browser_navigate", "browser_read_text",
        "browser_snapshot", "browser_click", "browser_type",
        "browser_press_key", "browser_evaluate", "browser_wait_for",
        "browser_take_screenshot",
    }
    assert expected <= names
