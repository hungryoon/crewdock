import asyncio
import hmac
import os
import re

from aiohttp import web

_SECRET = os.environ.get("CREW_BROKER_SECRET") or None
_SOCK = os.environ.get("CREW_BROKER_SOCK", "/run/crew-broker/broker.sock")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
_PROVIDERS = {"openai-codex", "nous", "qwen-oauth", "anthropic", "openrouter"}
_ACTIONS = {"add"}
_TIMEOUT = 300.0
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_active: set[tuple[str, str]] = set()


def strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


def build_argv(instance: str, action: str, provider: str) -> list[str]:
    """Strict, shell-free argv for the one allowed operation. Raises ValueError
    on any non-whitelisted input."""
    if not _NAME_RE.match(instance):
        raise ValueError("invalid instance name")
    if action not in _ACTIONS:
        raise ValueError("invalid action")
    if provider not in _PROVIDERS:
        raise ValueError("invalid provider")
    return ["docker", "exec", "-i", f"crew-{instance}",
            "hermes", "auth", "add", provider, "--no-browser"]
