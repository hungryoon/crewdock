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


def ws_proxy_request_headers(incoming: dict, prefix: str, port: int) -> dict:
    """Headers for an upstream WS upgrade, with Origin rewritten to loopback.

    The browser sends the gateway's public Origin (e.g. https://x.ts.net), but
    the upstream (Hermes) binds to loopback and rejects WS upgrades whose Origin
    targets a foreign host. Rewrite Origin to the exact upstream we dial so the
    upgrade is accepted. Only Origin is rewritten here, unlike on the HTTP path.
    """
    out = proxy_request_headers(incoming, prefix)
    # Drop any case-variant of Origin before setting the canonical one.
    for k in [k for k in out if k.lower() == "origin"]:
        del out[k]
    out["Origin"] = f"http://127.0.0.1:{port}"
    return out


def render_index(email: str, published: list[Published]) -> str:
    visible = [p for p in published if email in p.allowed_emails]
    if visible:
        cards = "\n".join(
            f'      <a class="card" href="/i/{_html.escape(p.name)}/">'
            f'<span class="name">{_html.escape(p.name)}</span>'
            f'<span class="go">open dashboard &rarr;</span></a>'
            for p in visible
        )
        body = f'<div class="grid">\n{cards}\n    </div>'
    else:
        body = ('<p class="empty">No instances are available for your account.</p>')
    return f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>crew</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh;
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #1a1a1a; background: #f6f7f9;
    display: flex; justify-content: center;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e8e8ea; background: #16171a; }}
    header {{ border-color: #2a2c31 !important; }}
    .card {{ background: #1e2024 !important; border-color: #2a2c31 !important; }}
    .card:hover {{ border-color: #4b6bfb !important; }}
  }}
  main {{ width: 100%; max-width: 720px; padding: 48px 24px; }}
  header {{ display: flex; align-items: baseline; justify-content: space-between;
    gap: 12px; flex-wrap: wrap;
    padding-bottom: 16px; margin-bottom: 28px; border-bottom: 1px solid #e3e5e9; }}
  h1 {{ margin: 0; font-size: 20px; letter-spacing: -0.01em; }}
  h1 .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #4b6bfb; }}
  .who {{ font-size: 13px; opacity: .7; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 14px; }}
  .card {{ display: flex; flex-direction: column; gap: 10px;
    padding: 18px 18px 16px; border: 1px solid #e3e5e9; border-radius: 12px;
    background: #fff; text-decoration: none; color: inherit;
    transition: border-color .12s ease, transform .12s ease; }}
  .card:hover {{ border-color: #4b6bfb; transform: translateY(-1px); }}
  .name {{ font-weight: 600; font-size: 16px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .go {{ font-size: 13px; opacity: .6; }}
  .empty {{ opacity: .65; }}
</style>
</head>
<body>
<main>
  <header>
    <h1><span class="mono">crew</span> &nbsp;instances</h1>
    <span class="who">{_html.escape(email)}</span>
  </header>
  {body}
</main>
</body>
</html>
"""
