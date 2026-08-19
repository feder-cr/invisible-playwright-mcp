from invisible_playwright_mcp.config import launch_kwargs


def test_defaults_headless_true_no_proxy():
    kw = launch_kwargs({})
    assert kw["headless"] is True
    assert "proxy" not in kw or kw["proxy"] is None
    assert "seed" not in kw


def test_headless_zero_disables():
    assert launch_kwargs({"STEALTHFOX_HEADLESS": "0"})["headless"] is False


def test_seed_parsed_as_int():
    assert launch_kwargs({"STEALTHFOX_SEED": "42"})["seed"] == 42


def test_proxy_parsed():
    kw = launch_kwargs({"STEALTHFOX_PROXY": "http://u:p@h.example:8080"})
    assert kw["proxy"] == {"server": "http://h.example:8080", "username": "u", "password": "p"}


def test_binary_and_profile_passthrough():
    kw = launch_kwargs({"STEALTHFOX_BINARY": "C:/ff.exe", "STEALTHFOX_PROFILE_DIR": "C:/prof"})
    assert kw["binary_path"] == "C:/ff.exe"
    assert kw["profile_dir"] == "C:/prof"
