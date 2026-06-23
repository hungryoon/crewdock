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


async def test_ws_proxy_rewrites_origin_to_upstream(aiohttp_client, monkeypatch):
    # Hermes (bound to loopback) rejects WS upgrades whose Origin targets a
    # foreign host. The router must rewrite Origin to http://127.0.0.1:<port>
    # (the upstream it dials) so the upgrade is accepted.
    seen = {}

    async def ws_upstream(request):
        seen["origin"] = request.headers.get("Origin")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await ws.send_str("ok")
        return ws
    up = web.Application()
    up.router.add_route("GET", "/{tail:.*}", ws_upstream)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", port, ["a@x.com"])])
    client = await aiohttp_client(router.build_app())
    ws = await client.ws_connect("/i/alice/api/pty",
                                 headers={"X-Forwarded-Email": "a@x.com",
                                          "Origin": "https://h.ts.net"})
    await ws.send_str("hi")
    await ws.receive()
    await ws.close()
    assert seen["origin"] == f"http://127.0.0.1:{port}"


async def test_ws_proxy_forwards_query_string(aiohttp_client, monkeypatch):
    # The dashboard passes its WS auth credential (?token=/?ticket=) and the
    # channel id (?channel=) in the query string. The router must forward it or
    # Hermes rejects the upgrade (no_credential -> 403) and chat/events never
    # connect.
    seen = {}

    async def ws_upstream(request):
        seen["qs"] = request.query_string
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await ws.send_str("ok")
        return ws
    up = web.Application()
    up.router.add_route("GET", "/{tail:.*}", ws_upstream)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", port, ["a@x.com"])])
    client = await aiohttp_client(router.build_app())
    ws = await client.ws_connect("/i/alice/api/pty?token=secret&channel=c1",
                                 headers={"X-Forwarded-Email": "a@x.com"})
    await ws.send_str("hi")
    await ws.receive()
    await ws.close()
    assert seen["qs"] == "token=secret&channel=c1"


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
    body = await resp.text()
    assert 'href="/"' in body


async def test_index_403_without_gateway_secret(aiohttp_client, published, monkeypatch):
    monkeypatch.setattr(router, "_GATEWAY_SECRET", "S3CRET")
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 403


async def test_proxy_403_without_gateway_secret(aiohttp_client, published, monkeypatch):
    monkeypatch.setattr(router, "_GATEWAY_SECRET", "S3CRET")
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/i/alice/", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 403


async def test_proxy_ok_with_correct_gateway_secret(aiohttp_client, monkeypatch):
    import base64
    async def upstream(request):
        return web.json_response({"ok": True, "auth": request.headers.get("Authorization", "")})
    up = web.Application()
    up.router.add_route("*", "/{tail:.*}", upstream)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", port, ["a@x.com"])])
    monkeypatch.setattr(router, "_GATEWAY_SECRET", "S3CRET")
    client = await aiohttp_client(router.build_app())
    auth = "Basic " + base64.b64encode(b"a@x.com:S3CRET").decode()
    resp = await client.get("/i/alice/x",
                            headers={"X-Forwarded-Email": "a@x.com", "Authorization": auth})
    assert resp.status == 200
    # Authorization (the gateway secret) must NOT be forwarded to the instance
    data = await resp.json()
    assert data["auth"] == ""


async def test_status_json_returns_authorized_cards(aiohttp_client, monkeypatch):
    async def ok(request):
        return web.Response(text="x")
    up = web.Application(); up.router.add_route("GET", "/", ok)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", port, ["a@x.com"])])
    monkeypatch.setattr(router, "_probe_cache", {})
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/_status.json", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 200
    data = await resp.json()
    assert [c["name"] for c in data] == ["alice"]
    assert data[0]["up"] is True


async def test_status_json_hides_unauthorized(aiohttp_client, monkeypatch):
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", 9120, ["a@x.com"])])
    monkeypatch.setattr(router, "_probe_cache", {})
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/_status.json", headers={"X-Forwarded-Email": "nobody@z.com"})
    assert resp.status == 200
    assert await resp.json() == []


async def test_status_json_403_without_gateway_secret(aiohttp_client, monkeypatch):
    monkeypatch.setattr(router, "_GATEWAY_SECRET", "S3CRET")
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/_status.json", headers={"X-Forwarded-Email": "a@x.com"})
    assert resp.status == 403


async def test_assets_serves_font_without_gateway_secret(aiohttp_client, monkeypatch):
    monkeypatch.setattr(router, "_GATEWAY_SECRET", "S3CRET")   # gate ON
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/_assets/JetBrainsMono-Regular.woff2")  # no Basic auth
    assert resp.status == 200
    assert "woff2" in resp.headers.get("Content-Type", "")
    assert len(await resp.read()) > 0


async def test_assets_rejects_unknown_or_traversal(aiohttp_client):
    client = await aiohttp_client(router.build_app())
    assert (await client.get("/_assets/secrets.env")).status == 404
    assert (await client.get("/_assets/..%2f..%2fetc%2fpasswd")).status in (400, 404)


async def test_probe_up_true_for_live_upstream(aiohttp_client, monkeypatch):
    async def ok(request):
        return web.Response(text="x")
    up = web.Application()
    up.router.add_route("GET", "/", ok)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_probe_cache", {})
    assert await router._probe_up(port) is True


async def test_probe_up_false_for_dead_port(monkeypatch):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    monkeypatch.setattr(router, "_probe_cache", {})
    assert await router._probe_up(dead) is False


async def test_probe_up_caches_within_ttl(aiohttp_client, monkeypatch):
    hits = {"n": 0}
    async def ok(request):
        hits["n"] += 1
        return web.Response(text="x")
    up = web.Application()
    up.router.add_route("GET", "/", ok)
    up_client = await aiohttp_client(up)
    port = up_client.server.port
    monkeypatch.setattr(router, "_probe_cache", {})
    await router._probe_up(port)
    await router._probe_up(port)
    assert hits["n"] == 1   # second call served from cache


async def test_setup_forbidden_for_unauthorized(aiohttp_client, monkeypatch):
    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", 9120, ["a@x.com"])])
    monkeypatch.setattr(router, "_BROKER_SOCK", "/nope.sock")
    client = await aiohttp_client(router.build_app())
    resp = await client.get("/_setup?instance=alice&provider=openai-codex",
                            headers={"X-Forwarded-Email": "nobody@z.com"})
    assert resp.status == 403


async def test_setup_proxies_broker_stream(aiohttp_client, monkeypatch, tmp_path):
    # Stand up a fake "broker" on a unix socket that echoes 2 frames + done.
    # Use /tmp directly to avoid macOS AF_UNIX 104-char path limit on tmp_path.
    import aiohttp
    import tempfile
    sockpath = tempfile.mktemp(suffix=".sock", dir="/tmp")

    async def fake_exec(request):
        ws = web.WebSocketResponse(); await ws.prepare(request)
        await ws.send_json({"line": "url: https://x"})
        await ws.send_json({"line": "code: AB-CD"})
        await ws.send_json({"done": True, "code": 0})
        await ws.close(); return ws
    bapp = web.Application(); bapp.router.add_get("/exec", fake_exec)
    brunner = web.AppRunner(bapp); await brunner.setup()
    bsite = web.UnixSite(brunner, sockpath); await bsite.start()

    monkeypatch.setattr(router, "_published",
                        lambda: [Published("alice", 9120, ["a@x.com"])])
    monkeypatch.setattr(router, "_BROKER_SOCK", sockpath)
    monkeypatch.setattr(router, "_BROKER_SECRET", None)
    client = await aiohttp_client(router.build_app())
    ws = await client.ws_connect("/_setup?instance=alice&provider=openai-codex",
                                 headers={"X-Forwarded-Email": "a@x.com"})
    frames = [msg.json() async for msg in ws]
    await brunner.cleanup()
    assert any("https://x" in f.get("line", "") for f in frames)
    assert any(f.get("done") for f in frames)
