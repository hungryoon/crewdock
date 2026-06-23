import asyncio
import mimetypes
import os
import time
from pathlib import Path

import aiohttp
from aiohttp import web

from crew.gateway import discovery, routing
from crew.core import paths

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_ASSET_WHITELIST = {"JetBrainsMono-Regular.woff2"}
mimetypes.add_type("font/woff2", ".woff2")

_EMAIL_HEADER = "X-Forwarded-Email"
# Shared secret only oauth2-proxy injects (as the Basic-auth password). When set,
# every request must carry it, so a host-networked instance can't reach the
# router directly and spoof X-Forwarded-Email. Unset (dev/tests) = check off.
_GATEWAY_SECRET = os.environ.get("CREW_GATEWAY_SECRET") or None


def _root() -> Path:
    return Path(os.environ.get("CREW_ROOT", "/crew"))


def _published():
    return discovery.published_instances(_root())


async def _assets(request: web.Request) -> web.StreamResponse:
    # Gate-exempt static fonts. Whitelist-only (no traversal); not secret.
    name = request.match_info["name"]
    if name not in _ASSET_WHITELIST:
        raise web.HTTPNotFound()
    path = _ASSETS_DIR / name
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={
        "Content-Type": "font/woff2",
        "Cache-Control": "public, max-age=86400",
    })


_PROBE_TTL = 5.0
_probe_cache: dict[int, tuple[float, bool]] = {}


async def _probe_up(port: int) -> bool:
    """Is the instance dashboard answering on loopback? Cached for _PROBE_TTL s.
    Any HTTP response counts as up; timeout/refused = down."""
    now = time.monotonic()
    hit = _probe_cache.get(port)
    if hit is not None and now - hit[0] < _PROBE_TTL:
        return hit[1]
    up = False
    try:
        timeout = aiohttp.ClientTimeout(total=1.5)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(f"http://127.0.0.1:{port}/"):
                up = True
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        up = False
    _probe_cache[port] = (now, up)
    return up


async def _gather_cards(email: str) -> list[dict]:
    """Build display cards for the instances this email may see."""
    root = _root()
    pubs = [p for p in _published() if email in p.allowed_emails]

    async def build(p):
        meta = paths.read_meta(root, p.name)
        return {
            "name": p.name,
            "up": await _probe_up(p.port),
            "image": routing.short_image(meta.get("image", "")),
            "timezone": meta.get("timezone", ""),
            "created": routing.fmt_created(meta.get("created_at", "")),
            "type": meta.get("type", ""),
            "port": p.port,
            "layers": list(meta.get("layers", []) or []),
            "credentials": list(meta.get("credentials", []) or []),
            "rollback": bool(meta.get("previous_image")),
        }

    return list(await asyncio.gather(*[build(p) for p in pubs]))


def _require_gateway(request: web.Request) -> None:
    if not routing.gateway_secret_ok(dict(request.headers), _GATEWAY_SECRET):
        raise web.HTTPForbidden(text="gateway authentication required")


async def _status_json(request: web.Request) -> web.Response:
    _require_gateway(request)
    email = request.headers.get(_EMAIL_HEADER, "")
    return web.json_response(await _gather_cards(email))


async def _index(request: web.Request) -> web.Response:
    _require_gateway(request)
    email = request.headers.get(_EMAIL_HEADER, "")
    cards = await _gather_cards(email)
    return web.Response(text=routing.render_index(email, cards),
                        content_type="text/html")


def _is_websocket(request: web.Request) -> bool:
    return request.headers.get("Upgrade", "").lower() == "websocket"


async def _proxy(request: web.Request) -> web.StreamResponse:
    _require_gateway(request)
    email = request.headers.get(_EMAIL_HEADER, "")
    parsed = routing.parse_instance_path(request.path)
    if parsed is None:
        raise web.HTTPNotFound()
    name, tail = parsed
    pubs = _published()
    match = next((p for p in pubs if p.name == name), None)
    if match is None:
        raise web.HTTPNotFound()
    if not routing.authorize(email, name, pubs):
        raise web.HTTPForbidden()
    prefix = f"/i/{name}"
    if _is_websocket(request):
        return await _proxy_ws(request, match.port, tail, prefix)
    return await _proxy_http(request, match.port, tail, prefix)


async def _proxy_http(request, port, tail, prefix) -> web.StreamResponse:
    url = routing.upstream_url(port, tail)
    headers = routing.proxy_request_headers(dict(request.headers), prefix)
    body = await request.read()
    try:
        timeout = aiohttp.ClientTimeout(total=None, connect=5, sock_connect=5)
        async with aiohttp.ClientSession(auto_decompress=False, timeout=timeout) as session:
            async with session.request(
                request.method, url, headers=headers, params=request.query,
                data=body, allow_redirects=False,
            ) as up:
                resp = web.StreamResponse(status=up.status, headers={
                    k: v for k, v in up.headers.items()
                    if k.lower() not in routing._HOP_BY_HOP
                })
                await resp.prepare(request)
                async for chunk in up.content.iter_chunked(65536):
                    await resp.write(chunk)
                await resp.write_eof()
                return resp
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise web.HTTPBadGateway(
            text='<!doctype html><p>upstream unavailable — '
                 '<a href="/">back to instances</a></p>',
            content_type="text/html")


async def _proxy_ws(request, port, tail, prefix) -> web.StreamResponse:
    ws_url = f"ws://127.0.0.1:{port}{tail}"
    if request.query_string:
        # The dashboard passes its WS auth credential (?token= / ?ticket=) and
        # the channel id (?channel=) in the query string — forward it, or the
        # instance rejects the upgrade (no_credential -> 403) and the chat /
        # events feed never connect.
        ws_url += f"?{request.query_string}"
    headers = routing.ws_proxy_request_headers(dict(request.headers), prefix, port)
    server_ws = web.WebSocketResponse()
    await server_ws.prepare(request)
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url, headers=headers) as client_ws:
            async def pump(src, dst):
                async for msg in src:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await dst.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await dst.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                      aiohttp.WSMsgType.CLOSING,
                                      aiohttp.WSMsgType.CLOSED,
                                      aiohttp.WSMsgType.ERROR):
                        break
                await dst.close()
            await asyncio.gather(pump(server_ws, client_ws),
                                pump(client_ws, server_ws),
                                return_exceptions=True)
    return server_ws


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/_assets/{name}", _assets)
    app.router.add_get("/_status.json", _status_json)
    app.router.add_route("*", "/i/{tail:.*}", _proxy)
    return app


def main() -> None:
    port = int(os.environ.get("CREW_ROUTER_PORT", "9400"))
    web.run_app(build_app(), host="127.0.0.1", port=port)
