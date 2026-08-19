import json


def test_small_object_returns_normal_json():
    from invisible_playwright_mcp.server import _json_capped
    s = _json_capped({"a": 1})
    assert json.loads(s) == {"a": 1}


def test_large_object_returns_valid_truncated_json():
    from invisible_playwright_mcp.server import _json_capped
    big = {"data": "x" * 20000}
    s = _json_capped(big, limit=6000)
    parsed = json.loads(s)  # must not raise: slicing raw JSON breaks this
    assert parsed["truncated"] is True
    assert parsed["chars"] > 6000
    assert isinstance(parsed["preview"], str)
    assert len(parsed["preview"]) <= 6000
