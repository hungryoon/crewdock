import socket

import aiohttp
import pytest
from aiohttp import web

from crew.gateway import router
from crew.gateway.discovery import Published


@pytest.fixture
def published(monkeypatch):
    pubs = [Published("alice", 9120, ["a@x.com"])]
    monkeypatch.setattr(router, "_published", lambda: pubs)
    return pubs


async def test_index_lists_authorized(aiohttp_client, published):
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 200
    body = await resp.text()
    assert "/i/alice/" in body


async def test_unknown_instance_404(aiohttp_client, published):
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/i/ghost/", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 404


async def test_forbidden_instance_403(aiohttp_client, published):
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/i/alice/", headers={"X-Forwarded-Email": "nobody@z.com"})
    assert resp.status == 403


async def test_http_proxy_forwards_with_prefix(aiohttp_client, published, monkeypatch):
    async def upstream(request):
        return web.json_response({
            "path": request.path,
            "prefix": request.headers.get("X-Forwarded-Prefix", ""),
        })
    up = web.Application()
    up.router.add_route("*", "/{tail:.*}", upstream)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", port, ["a@x.com"])])

    client = await aiohttp_client(router.build_app())
    resp = await client.get("/i/alice/foo", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 200
    data = await resp.json()
    assert data["path"] == "/foo"
    assert data["prefix"] == "/i/alice"


async def test_ws_proxy_echo(aiohttp_client, monkeypatch):
    async def ws_upstream(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await ws.send_str("echo:" + msg.data)
        return ws
    up = web.Application()
    up.router.add_route("GET", "/{tail:.*}", ws_upstream)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", port, ["a@x.com"])])
    client = await aiohttp_client(router.build_app())
    ws = await client.ws_connect("/i/alice/api/pty",
                                 headers={"X-Forwarded-Email": "a@x.com"})
    await ws.send_str("hi")
    msg = await ws.receive()
    assert msg.data == "echo:hi"
    await ws.close()


async def test_http_proxy_passes_compressed_body_unchanged(aiohttp_client, monkeypatch):
    import gzip
    payload = gzip.compress(b"hello world")
    async def upstream(request):
        return web.Response(body=payload, headers={"Content-Encoding": "gzip"})
    up = web.Application()
    up.router.add_route("*", "/{tail:.*}", upstream)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", port, ["a@x.com"])])
    client = await aiohttp_client(router.build_app())
    # auto_decompress on the test client will gunzip; if Content-Encoding was
    # wrongly stripped by the router, decoding would fail / mismatch.
    resp = await client.get("/i/alice/x", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 200
    assert await resp.read() == b"hello world"


async def test_upstream_down_returns_502(aiohttp_client, monkeypatch):
    # Allocate and immediately close a socket to get a port that is
    # definitely not listening — more reliable than guessing a fixed port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        dead_port = s.getsockname()[1]
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", dead_port, ["a@x.com"])])
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/i/alice/x", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 502
