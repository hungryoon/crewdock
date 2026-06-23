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


def _secret_ok(request: web.Request) -> bool:
    if not _SECRET:
        return True
    got = request.headers.get("X-Crew-Broker-Secret", "")
    return hmac.compare_digest(got, _SECRET)


async def _stream(ws: web.WebSocketResponse, argv: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    async def pump():
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = strip_ansi(raw.decode("utf-8", "replace")).rstrip("\n")
            if not ws.closed:
                await ws.send_json({"line": line})

    code: int
    try:
        try:
            await asyncio.wait_for(asyncio.gather(pump(), proc.wait()),
                                   timeout=_TIMEOUT)
            code = proc.returncode or 0
        except asyncio.TimeoutError:
            if not ws.closed:
                await ws.send_json({"line": "timed out waiting for sign-in"})
            code = 124
        if not ws.closed:
            await ws.send_json({"done": True, "code": code})
    finally:
        # Reap the child on ANY exit path (timeout, or e.g. a send raising on a
        # reset connection) so a dropped WS never orphans a `docker exec`.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def _exec(request: web.Request) -> web.StreamResponse:
    if not _secret_ok(request):
        return web.Response(status=403, text="forbidden")
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    instance = request.query.get("instance", "")
    action = request.query.get("action", "add")
    provider = request.query.get("provider", "")
    try:
        argv = build_argv(instance, action, provider)
    except ValueError as exc:
        await ws.send_json({"line": f"error: {exc}"})
        await ws.send_json({"done": True, "code": 2})
        await ws.close()
        return ws
    key = (instance, provider)
    if key in _active:
        await ws.send_json({"line": "a setup is already running for this instance"})
        await ws.send_json({"done": True, "code": 1})
        await ws.close()
        return ws
    _active.add(key)
    try:
        await _stream(ws, argv)
    finally:
        _active.discard(key)
    await ws.close()
    return ws


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/exec", _exec)
    return app


def main() -> None:
    async def _serve() -> None:
        runner = web.AppRunner(build_app())
        await runner.setup()
        if os.path.exists(_SOCK):
            os.unlink(_SOCK)
        site = web.UnixSite(runner, _SOCK)
        await site.start()
        os.chmod(_SOCK, 0o666)   # router connects from a possibly-different uid
        await asyncio.Event().wait()
    asyncio.run(_serve())
