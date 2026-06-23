import asyncio
import os
from pathlib import Path

import aiohttp
from aiohttp import web

from crew.gateway import discovery, routing

_EMAIL_HEADER = "X-Forwarded-Email"
# Shared secret only oauth2-proxy injects (as the Basic-auth password). When set,
# every request must carry it, so a host-networked instance can't reach the
# router directly and spoof X-Forwarded-Email. Unset (dev/tests) = check off.
_GATEWAY_SECRET = os.environ.get("CREW_GATEWAY_SECRET") or None


def _root() -> Path:
    return Path(os.environ.get("CREW_ROOT", "/crew"))


def _published():
    return discovery.published_instances(_root())


def _require_gateway(request: web.Request) -> None:
    if not routing.gateway_secret_ok(dict(request.headers), _GATEWAY_SECRET):
        raise web.HTTPForbidden(text="gateway authentication required")


async def _index(request: web.Request) -> web.Response:
    _require_gateway(request)
    email = request.headers.get(_EMAIL_HEADER, "")
    return web.Response(text=routing.render_index(email, _published()),
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
    app.router.add_route("*", "/i/{tail:.*}", _proxy)
    return app


def main() -> None:
    port = int(os.environ.get("CREW_ROUTER_PORT", "9400"))
    web.run_app(build_app(), host="127.0.0.1", port=port)
