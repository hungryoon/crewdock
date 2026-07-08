import asyncio
import fcntl
import os
import pty
import struct
import termios

import pytest
from aiohttp import WSMsgType
from crew.gateway import broker


def test_require_secret_configured_raises_without_secret(monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", None)
    with pytest.raises(SystemExit):
        broker._require_secret_configured()


def test_require_secret_configured_ok_with_secret(monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", "x")
    broker._require_secret_configured()  # no raise


def test_build_argv_default_project():
    assert broker.build_argv("alice", "add", "openai-codex") == [
        "docker", "exec", "-i", "crew-alice",
        "hermes", "auth", "add", "openai-codex", "--no-browser"]


def test_build_argv_namespaced_project():
    assert broker.build_argv("alice", "add", "openai-codex", project="synt") == [
        "docker", "exec", "-i", "synt-alice",
        "hermes", "auth", "add", "openai-codex", "--no-browser"]


@pytest.mark.parametrize("inst,action,prov", [
    ("../etc", "add", "openai-codex"),
    ("alice;rm", "add", "openai-codex"),
    ("alice", "shell", "openai-codex"),
    ("alice", "add", "evil-provider"),
    ("", "add", "openai-codex"),
])
def test_build_argv_rejects(inst, action, prov):
    with pytest.raises(ValueError):
        broker.build_argv(inst, action, prov)


def test_strip_ansi():
    assert broker.strip_ansi("\x1b[94mhttps://x\x1b[0m") == "https://x"


def test_build_pty_argv_ok():
    assert broker.build_pty_argv("ted-9b8c7d", 501, 20, "/opt/data", project="crew") == [
        "docker", "exec", "-i", "-t", "-u", "501:20", "-w", "/opt/data",
        "crew-ted-9b8c7d", "bash"]


@pytest.mark.parametrize("inst,uid,gid,wd", [
    ("../etc", 501, 20, "/opt/data"),   # bad name
    ("alice;rm", 501, 20, "/opt/data"),
    ("alice", -1, 20, "/opt/data"),     # bad uid
    ("alice", 501, 20, "relative"),     # non-absolute workdir
    ("alice", 501, 20, "/o\x00pt"),     # NUL in workdir
])
def test_build_pty_argv_rejects(inst, uid, gid, wd):
    with pytest.raises(ValueError):
        broker.build_pty_argv(inst, uid, gid, wd)


def test_apply_resize_sets_winsize():
    master, slave = pty.openpty()
    try:
        broker._apply_resize(master, '{"resize":{"rows":40,"cols":100}}')
        rows, cols, _, _ = struct.unpack(
            "HHHH", fcntl.ioctl(slave, termios.TIOCGWINSZ, b"\0" * 8))
        assert (rows, cols) == (40, 100)
    finally:
        os.close(master)
        os.close(slave)


def test_apply_resize_ignores_garbage():
    master, slave = pty.openpty()
    try:
        broker._apply_resize(master, "not json")          # no raise
        broker._apply_resize(master, '{"resize":{"rows":"x"}}')
    finally:
        os.close(master)
        os.close(slave)


async def test_pty_echoes_stdin(aiohttp_client, monkeypatch):
    # `cat` stands in for the container shell: whatever we type comes back.
    monkeypatch.setattr(broker, "build_pty_argv", lambda *a, **k: ["cat"])
    monkeypatch.setattr(broker, "_SECRET", None)
    client = await aiohttp_client(broker.build_app())
    ws = await client.ws_connect("/pty?instance=alice&uid=1000&gid=1000")
    await ws.send_bytes(b"hi\n")
    got = b""
    try:
        while b"hi" not in got:
            msg = await asyncio.wait_for(ws.receive(), timeout=5)
            if msg.type == WSMsgType.BINARY:
                got += msg.data
            else:
                break
    finally:
        await ws.close()
    assert b"hi" in got


async def test_pty_rejects_bad_uid(aiohttp_client, monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", None)
    client = await aiohttp_client(broker.build_app())
    ws = await client.ws_connect("/pty?instance=alice&uid=notint&gid=20")
    got = b""
    async for msg in ws:
        if msg.type == WSMsgType.BINARY:
            got += msg.data
    assert b"error" in got


async def test_exec_streams_lines_and_done(aiohttp_client, monkeypatch):
    # benign command instead of docker exec
    monkeypatch.setattr(broker, "build_argv",
        lambda i, a, p: ["sh", "-c", "printf 'l1\\nl2\\n'; exit 0"])
    monkeypatch.setattr(broker, "_SECRET", None)
    client = await aiohttp_client(broker.build_app())
    ws = await client.ws_connect("/exec?instance=alice&provider=openai-codex")
    lines, done = [], None
    async for msg in ws:
        d = msg.json()
        if d.get("done"):
            done = d
            break
        lines.append(d["line"])
    assert lines == ["l1", "l2"]
    assert done["code"] == 0


async def test_exec_rejects_bad_secret(aiohttp_client, monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", "S")
    client = await aiohttp_client(broker.build_app())
    resp = await client.get("/exec?instance=alice&provider=openai-codex")  # no secret hdr
    assert resp.status == 403


async def test_exec_rejects_bad_provider(aiohttp_client, monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", None)
    client = await aiohttp_client(broker.build_app())
    ws = await client.ws_connect("/exec?instance=alice&provider=nope")
    seen = [msg.json() async for msg in ws]
    assert any(d.get("done") and d["code"] == 2 for d in seen)
    assert any("invalid provider" in d.get("line", "") for d in seen)
