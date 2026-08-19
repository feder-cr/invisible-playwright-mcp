"""Translate STEALTHFOX_* environment variables into InvisiblePlaywright kwargs."""
from __future__ import annotations

from typing import Any, Mapping

from .proxy import proxy_from_url


def launch_kwargs(env: Mapping[str, str]) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    seed = env.get("STEALTHFOX_SEED")
    if seed:
        kw["seed"] = int(seed)
    proxy = proxy_from_url(env.get("STEALTHFOX_PROXY"))
    if proxy is not None:
        kw["proxy"] = proxy
    kw["headless"] = env.get("STEALTHFOX_HEADLESS", "1") != "0"
    binary = env.get("STEALTHFOX_BINARY")
    if binary:
        kw["binary_path"] = binary
    profile = env.get("STEALTHFOX_PROFILE_DIR")
    if profile:
        kw["profile_dir"] = profile
    return kw
