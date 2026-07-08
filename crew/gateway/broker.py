import asyncio
import fcntl
import hmac
import json
import os
import pty
import re
import struct
import termios

from aiohttp import web

_SECRET = os.environ.get("CREW_BROKER_SECRET") or None
_SOCK = os.environ.get("CREW_BROKER_SOCK", "/run/crew-broker/broker.sock")
_PROJECT = os.environ.get("CREW_PROJECT", "crew")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
_PROVIDERS = {"openai-codex", "nous", "qwen-oauth", "anthropic", "openrouter"}
_ACTIONS = {"add"}
_TIMEOUT = 300.0
# Idle cap for interactive shells: reap a session with no keystrokes for this
# long so a forgotten-open browser tab never orphans a `docker exec`.
# ponytail: idle on *input* only — watching `top` with no keypress for 30min
# still gets reaped. Acceptable; widen to output-activity if users complain.
_PTY_IDLE_TIMEOUT = 1800.0
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_active: set[tuple[str, str]] = set()
_pty_active: set[str] = set()


def strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


def build_argv(instance: str, action: str, provider: str,
               project: str = _PROJECT) -> list[str]:
    """Strict, shell-free argv for the one allowed operation. Raises ValueError
    on any non-whitelisted input."""
    if not _NAME_RE.match(instance):
        raise ValueError("invalid instance name")
    if action not in _ACTIONS:
        raise ValueError("invalid action")
    if provider not in _PROVIDERS:
        raise ValueError("invalid provider")
    return ["docker", "exec", "-i", f"{project}-{instance}",
            "hermes", "auth", "add", provider, "--no-browser"]


def build_pty_argv(instance: str, uid: int, gid: int, workdir: str,
                   project: str = _PROJECT) -> list[str]:
    """argv for an interactive shell in the instance. Runs as the host-mapped
    hermes user (not root) so file ownership matches the bind mount. Raises
    ValueError on any non-conforming input."""
    if not _NAME_RE.match(instance):
        raise ValueError("invalid instance name")
    if not (isinstance(uid, int) and isinstance(gid, int) and uid >= 0 and gid >= 0):
        raise ValueError("invalid uid/gid")
    if not workdir.startswith("/") or "\x00" in workdir:
        raise ValueError("invalid workdir")
    return ["docker", "exec", "-i", "-t", "-u", f"{uid}:{gid}", "-w", workdir,
            f"{project}-{instance}", "bash"]


def _apply_resize(master: int, text: str) -> None:
    """Handle a browser resize frame: TIOCSWINSZ on the pty master; docker -t
    forwards the SIGWINCH into the container exec. Ignores malformed frames."""
    try:
        r = json.loads(text)["resize"]
        rows, cols = int(r["rows"]), int(r["cols"])
    except (ValueError, KeyError, TypeError):
        return
    try:
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


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


async def _pty(request: web.Request) -> web.StreamResponse:
    if not _secret_ok(request):
        return web.Response(status=403, text="forbidden")
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    instance = request.query.get("instance", "")
    workdir = request.query.get("workdir", "/opt/data")
    try:
        uid = int(request.query.get("uid", ""))
        gid = int(request.query.get("gid", ""))
        argv = build_pty_argv(instance, uid, gid, workdir)
    except ValueError as exc:
        await ws.send_bytes(f"error: {exc}\r\n".encode())
        await ws.close()
        return ws
    if instance in _pty_active:
        await ws.send_bytes(b"a terminal is already open for this instance\r\n")
        await ws.close()
        return ws
    _pty_active.add(instance)
    master, slave = pty.openpty()
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    loop = asyncio.get_running_loop()
    out: asyncio.Queue = asyncio.Queue()

    def on_readable() -> None:
        try:
            data = os.read(master, 65536)
        except OSError:
            data = b""
        if not data:                 # child exited / pty closed
            loop.remove_reader(master)
        out.put_nowait(data)         # b"" = EOF sentinel

    loop.add_reader(master, on_readable)

    async def to_ws() -> None:
        while True:
            data = await out.get()
            if not data:
                break
            if not ws.closed:
                await ws.send_bytes(data)

    async def from_ws() -> None:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=_PTY_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                break
            if msg.type == web.WSMsgType.BINARY:
                try:
                    os.write(master, msg.data)
                except OSError:
                    break
            elif msg.type == web.WSMsgType.TEXT:
                _apply_resize(master, msg.data)
            else:                    # CLOSE/CLOSING/CLOSED/ERROR
                break

    try:
        done, pending = await asyncio.wait(
            {asyncio.ensure_future(to_ws()), asyncio.ensure_future(from_ws())},
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    finally:
        try:
            loop.remove_reader(master)
        except (OSError, ValueError):
            pass
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        os.close(master)
        _pty_active.discard(instance)
        if not ws.closed:
            await ws.close()
    return ws


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/exec", _exec)
    app.router.add_get("/pty", _pty)
    return app


def _require_secret_configured() -> None:
    if not _SECRET:
        raise SystemExit(
            "CREW_BROKER_SECRET is not set — refusing to start.")


def main() -> None:
    _require_secret_configured()
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
