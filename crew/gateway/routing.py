import html as _html

from crew.gateway.discovery import Published

# Hop-by-hop headers must not be forwarded by a proxy (RFC 7230 6.1).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
}


def parse_instance_path(path: str):
    """('/i/<name>/<tail>') -> (name, '/<tail>'); None if not an instance path."""
    if not path.startswith("/i/"):
        return None
    rest = path[len("/i/"):]
    name, slash, tail = rest.partition("/")
    if not name:
        return None
    return name, ("/" + tail if tail else "/")


def authorize(email: str, name: str, published: list[Published]) -> bool:
    for p in published:
        if p.name == name:
            return email in p.allowed_emails
    return False


def upstream_url(port: int, tail: str) -> str:
    return f"http://127.0.0.1:{port}{tail}"


def proxy_request_headers(incoming: dict, prefix: str) -> dict:
    out = {k: v for k, v in incoming.items()
           if k.lower() not in _HOP_BY_HOP}
    out["X-Forwarded-Prefix"] = prefix
    return out


def render_index(email: str, published: list[Published]) -> str:
    visible = [p for p in published if email in p.allowed_emails]
    items = "\n".join(
        f'      <li><a href="/i/{_html.escape(p.name)}/">'
        f'{_html.escape(p.name)}</a></li>'
        for p in visible
    )
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        "<title>crew</title></head><body>"
        f"<h1>crew instances</h1><p>signed in as {_html.escape(email)}</p>"
        f"<ul>\n{items}\n</ul></body></html>"
    )
