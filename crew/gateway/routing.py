import base64
import binascii
import hmac
import html as _html

from crew.gateway.discovery import Published

# Hop-by-hop headers must not be forwarded by a proxy (RFC 7230 6.1).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
}


def short_image(ref: str) -> str:
    """Compact image label for the UI: prefer the tag, else a short digest."""
    if not ref:
        return ""
    name_part, _, digest = ref.partition("@sha256:")
    last = name_part.rsplit("/", 1)[-1]          # e.g. hermes-agent:v2026.6.19
    tag = last.split(":", 1)[1] if ":" in last else ""
    if tag:
        return tag
    if digest:
        return "@" + digest[:12]
    return last


def fmt_created(stamp: str) -> str:
    """`20260623T024431Z` -> `2026-06-23`; empty/unparseable -> ''."""
    s = stamp or ""
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return ""


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
    # Authorization carries the gateway↔oauth2-proxy shared secret (Basic auth);
    # it is consumed by the router and must NOT be forwarded to the instance.
    out = {k: v for k, v in incoming.items()
           if k.lower() not in _HOP_BY_HOP and k.lower() != "authorization"}
    out["X-Forwarded-Prefix"] = prefix
    return out


def gateway_secret_from_headers(incoming: dict) -> str | None:
    """Password from an ``Authorization: Basic base64(user:pass)`` header
    (oauth2-proxy sets this via --basic-auth-password). None if absent/malformed."""
    for k, v in incoming.items():
        if k.lower() == "authorization" and v.startswith("Basic "):
            try:
                decoded = base64.b64decode(v[6:]).decode("utf-8", "replace")
            except (binascii.Error, ValueError):
                return None
            return decoded.split(":", 1)[1] if ":" in decoded else None
    return None


def gateway_secret_ok(incoming: dict, secret: str | None) -> bool:
    """True when no secret is configured (check disabled) or the request carries
    the matching shared secret — proving it arrived through oauth2-proxy rather
    than a direct connection from a host-networked instance spoofing the email."""
    if not secret:
        return True
    got = gateway_secret_from_headers(incoming)
    return got is not None and hmac.compare_digest(got, secret)


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


def _detail_kvs(c: dict) -> list[str]:
    """Ordered, HTML-escaped key/value chips for an instance row (only present
    fields). Used by render_index; pure for testability."""
    kvs: list[str] = []
    if c.get("type"):
        kvs.append(_html.escape(c["type"]))
    if c.get("image"):
        kvs.append(_html.escape(c["image"]))
    if c.get("port"):
        kvs.append(f':{int(c["port"])}')
    if c.get("timezone"):
        kvs.append(_html.escape(c["timezone"]))
    if c.get("created"):
        kvs.append(_html.escape(c["created"]))
    if c.get("layers"):
        kvs.append("layers: " + _html.escape(", ".join(c["layers"])))
    if c.get("credentials"):
        kvs.append("creds: " + _html.escape(", ".join(c["credentials"])))
    return kvs


def render_index(email: str, cards: list[dict]) -> str:
    if cards:
        def row(c: dict) -> str:
            name = _html.escape(c["name"])
            chips = "".join(f'<span class="kv">{kv}</span>' for kv in _detail_kvs(c))
            if c.get("rollback"):
                chips += '<span class="kv rb">&#8629; rollback</span>'
            return (
                f'      <div class="row" data-name="{name}">\n'
                f'        <div class="head">'
                f'<span class="dot {"up" if c["up"] else "down"}"></span>'
                f'<span class="name">{name}</span>'
                f'<span class="state">{"running" if c["up"] else "down"}</span>'
                f'<a class="go" href="/i/{name}/">open dashboard &rarr;</a>'
                f'<button class="setup" data-setup="{name}">&#9881; model setup</button>'
                f'</div>\n'
                f'        <div class="detail">{chips}</div>\n'
                f'        <div class="panel" data-panel="{name}" hidden>\n'
                f'          <select class="prov">'
                f'<option value="openai-codex">openai-codex</option>'
                f'<option value="nous">nous</option>'
                f'<option value="qwen-oauth">qwen-oauth</option>'
                f'<option value="anthropic">anthropic</option>'
                f'<option value="openrouter">openrouter</option></select>'
                f'<button class="start">start</button>\n'
                f'          <pre class="out"></pre>\n'
                f'        </div>\n'
                f'      </div>'
            )
        rows = "\n".join(row(c) for c in cards)
        body = f'<div class="list">\n{rows}\n    </div>'
    else:
        body = '<p class="empty">No instances are available for your account.</p>'
    return f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>crew</title>
<style>
  @font-face {{ font-family: "JetBrainsMono"; font-display: swap;
    src: url("/_assets/JetBrainsMono-Regular.woff2") format("woff2"); }}
  :root {{ color-scheme: dark light;
    --bg:#0e1116; --panel:#161b22; --border:#2a313c; --fg:#d6dde6;
    --muted:#7d8694; --accent:#58e6a8; --accent2:#f5e7c8; --down:#5a6573; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; justify-content:center;
    background:var(--bg); color:var(--fg);
    font:14px/1.55 "JetBrainsMono", ui-monospace, SFMono-Regular, Menlo, monospace; }}
  main {{ width:100%; max-width:760px; padding:48px 24px; }}
  header {{ display:flex; align-items:baseline; justify-content:space-between;
    gap:12px; flex-wrap:wrap; padding-bottom:14px; margin-bottom:26px;
    border-bottom:1px solid var(--border); }}
  h1 {{ margin:0; font-size:18px; font-weight:600; letter-spacing:-0.01em; }}
  h1 .p {{ color:var(--accent); }}
  .who {{ font-size:12px; color:var(--muted); }}
  .list {{ display:flex; flex-direction:column; gap:10px; }}
  .row {{ display:flex; flex-direction:column; gap:8px; padding:13px 16px;
    border:1px solid var(--border); border-radius:10px; background:var(--panel);
    text-decoration:none; color:inherit; transition:border-color .12s; }}
  .row:hover {{ border-color:var(--accent); }}
  .head {{ display:flex; align-items:center; gap:10px; }}
  .dot {{ width:8px; height:8px; border-radius:50%; flex:none; background:var(--down); }}
  .dot.up {{ background:var(--accent); box-shadow:0 0 6px var(--accent); }}
  .name {{ font-weight:600; font-size:15px; }}
  .state {{ font-size:12px; color:var(--muted); }}
  .go {{ margin-left:auto; color:var(--accent2); opacity:.85; font-size:12px; }}
  .detail {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .kv {{ font-size:11px; color:var(--muted);
    border:1px solid var(--border); border-radius:5px; padding:1px 7px; }}
  .kv.rb {{ color:var(--accent2); border-color:var(--accent2); opacity:.85; }}
  .empty {{ color:var(--muted); }}
  .setup {{ margin-left:8px; font:inherit; font-size:11px; cursor:pointer;
    color:var(--fg); background:transparent; border:1px solid var(--border);
    border-radius:5px; padding:1px 7px; }}
  .setup:hover {{ border-color:var(--accent); }}
  .panel {{ display:flex; flex-direction:column; gap:8px; margin-top:4px; }}
  .panel select, .panel .start {{ font:inherit; font-size:12px; align-self:flex-start;
    background:var(--bg); color:var(--fg); border:1px solid var(--border);
    border-radius:5px; padding:3px 8px; }}
  .panel .start {{ cursor:pointer; }}
  .out {{ margin:0; white-space:pre-wrap; word-break:break-all; font-size:12px;
    color:var(--muted); max-height:220px; overflow:auto; }}
  .out a {{ color:var(--accent); }}
</style>
</head>
<body>
<main>
  <header>
    <h1><span class="p">crew</span>&nbsp;~&nbsp;instances</h1>
    <span class="who">{_html.escape(email)}</span>
  </header>
  {body}
</main>
<script>
  async function refresh() {{
    try {{
      const r = await fetch("/_status.json", {{credentials:"same-origin"}});
      if (!r.ok) return;
      for (const c of await r.json()) {{
        const el = document.querySelector('.row[data-name="'+CSS.escape(c.name)+'"] .dot');
        if (el) el.className = "dot " + (c.up ? "up" : "down");
        const st = document.querySelector('.row[data-name="'+CSS.escape(c.name)+'"] .state');
        if (st) st.textContent = c.up ? "running" : "down";
      }}
    }} catch (e) {{}}
  }}
  setInterval(refresh, 10000);
  document.addEventListener("click", (e) => {{
    const b = e.target.closest(".setup");
    if (b) {{
      const p = document.querySelector('.panel[data-panel="'+CSS.escape(b.dataset.setup)+'"]');
      if (p) p.hidden = !p.hidden;
      return;
    }}
    const s = e.target.closest(".start");
    if (s) {{
      const panel = s.closest(".panel");
      const name = panel.getAttribute("data-panel");
      const prov = panel.querySelector(".prov").value;
      const out = panel.querySelector(".out");
      out.textContent = "starting...\\n";
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(proto + "//" + location.host
        + "/_setup?instance=" + encodeURIComponent(name)
        + "&provider=" + encodeURIComponent(prov));
      ws.onmessage = (ev) => {{
        const d = JSON.parse(ev.data);
        if (d.done) {{ out.textContent += (d.code === 0 ? "\\n✓ done" : "\\n✗ failed (code "+d.code+")"); ws.close(); }}
        else {{ out.textContent += d.line + "\\n"; out.scrollTop = out.scrollHeight; }}
      }};
      ws.onerror = () => {{ out.textContent += "\\nconnection error"; }};
    }}
  }});
</script>
</body>
</html>
"""
