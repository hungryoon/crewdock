"""Custom oauth2-proxy sign-in/error templates, themed to match the gateway
dashboard.

oauth2-proxy ships Bulma-styled default pages. We override ``sign_in.html`` and
``error.html`` (via ``OAUTH2_PROXY_CUSTOM_TEMPLATES_DIR``) with our own dark
JetBrains-Mono theme so the login screen and the instance dashboard
(``routing.render_index``) look like one product.

The pages are Go ``html/template`` files: every ``{{ ... }}`` directive must be
preserved verbatim, and we may only reference variables oauth2-proxy actually
provides (.ProxyPrefix, .Redirect, .ProviderName, .SignInMessage, .CustomLogin,
.StatusCode, .LogoData, .Message, .RequestID, .Title, .Footer, .Version).

The font is inlined as a data URI rather than served from ``/_assets`` because
oauth2-proxy renders these pages to *unauthenticated* visitors — any request for
a stylesheet/font would itself be bounced back to the sign-in page.
"""

import base64
from pathlib import Path

from crew.gateway import theme

_FONT = Path(__file__).resolve().parent / "assets" / "JetBrainsMono-Regular.woff2"


def font_data_uri() -> str:
    """The bundled JetBrains Mono woff2 as a ``data:`` URI for inlining."""
    b64 = base64.b64encode(_FONT.read_bytes()).decode("ascii")
    return f"data:font/woff2;base64,{b64}"


def _css(font_uri: str) -> str:
    return (
        '@font-face { font-family:"JetBrainsMono"; font-display:swap;'
        ' src:url("' + font_uri + '") format("woff2"); }\n'
        "  :root { " + theme.ROOT_VARS + " }\n"
        "  * { box-sizing:border-box; }\n"
        "  body { margin:0; min-height:100vh; display:flex; align-items:center;\n"
        "    justify-content:center; background:var(--bg); color:var(--fg);\n"
        '    font:14px/1.55 "JetBrainsMono", ui-monospace, SFMono-Regular, Menlo, monospace; }\n'
        "  main { width:100%; max-width:380px; padding:40px 24px; }\n"
        "  .card { background:var(--panel); border:1px solid var(--border);\n"
        "    border-radius:12px; padding:30px 28px; display:flex;\n"
        "    flex-direction:column; gap:16px; text-align:center; }\n"
        "  .brand { font-size:18px; font-weight:600; letter-spacing:-0.01em;\n"
        "    display:flex; align-items:center; justify-content:center; gap:8px; }\n"
        "  .brand .p { color:var(--accent); }\n"
        "  .logo { flex:none; display:block; }\n"
        "  .sub, .msg { font-size:12px; color:var(--muted); margin:0; }\n"
        "  form { margin:0; }\n"
        "  .btn { display:block; width:100%; font:inherit; font-size:13px;\n"
        "    cursor:pointer; color:var(--bg); background:var(--accent);\n"
        "    border:1px solid var(--accent); border-radius:7px; padding:9px 14px;\n"
        "    font-weight:600; transition:opacity .12s; }\n"
        "  .btn:hover { opacity:.9; }\n"
        "  .btn.danger { color:#e07a8a; background:transparent; border-color:#5a3a42;\n"
        "    font-weight:400; }\n"
        "  .field { text-align:left; display:flex; flex-direction:column; gap:5px;\n"
        "    margin-bottom:12px; }\n"
        "  .field label { font-size:11px; color:var(--muted); }\n"
        "  .field input { font:inherit; font-size:13px; background:var(--bg);\n"
        "    color:var(--fg); border:1px solid var(--border); border-radius:6px;\n"
        "    padding:8px 10px; }\n"
        "  .field input:focus { outline:none; border-color:var(--accent); }\n"
        "  .alert { font-size:12px; color:#e07a8a; border:1px solid #5a3a42;\n"
        "    border-radius:6px; padding:7px 10px; }\n"
        "  .sep { border:none; border-top:1px solid var(--border); margin:2px 0; }\n"
        "  .cols { display:flex; gap:10px; }\n"
        "  .cols form { flex:1; }\n"
        "  .status { font-size:64px; font-weight:600; color:var(--accent); line-height:1; }\n"
        "  .title { font-size:15px; font-weight:600; margin:0; }\n"
        "  .info { text-align:left; font-size:12px; color:var(--muted);\n"
        "    background:var(--bg); border:1px solid var(--border); border-radius:6px;\n"
        "    padding:10px; white-space:pre-wrap; word-break:break-word; }\n"
        "  footer { margin-top:18px; text-align:center; font-size:11px; color:var(--muted); }\n"
        "  footer a { color:var(--muted); }"
    )


# Footer block shared by both pages (oauth2-proxy's standard footer logic).
_FOOTER = """  <footer>
    {{ if eq .Footer "-" }}
    {{ else if eq .Footer ""}}
    <p>Secured with <a href="https://github.com/oauth2-proxy/oauth2-proxy#oauth2_proxy">OAuth2 Proxy</a> {{.Version}}</p>
    {{ else }}
    <p>{{.Footer}}</p>
    {{ end }}
  </footer>"""

# Re-applies the URL fragment to every `rd` field, matching oauth2-proxy's
# default sign-in page so deep links survive the round trip.
_HASH_SCRIPT = """<script>
  if (window.location.hash) {
    (function() {
      var inputs = document.getElementsByName('rd');
      for (var i = 0; i < inputs.length; i++) {
        var idx = inputs[i].value.indexOf('#');
        if (idx >= 0) { inputs[i].value = inputs[i].value.substr(0, idx); }
        inputs[i].value += window.location.hash;
      }
    })();
  }
</script>"""


def render_sign_in(font_uri: str) -> str:
    return (
        '{{define "sign_in.html"}}\n'
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>crew ~ sign in</title>\n"
        '<link rel="icon" href="' + theme.FAVICON_HREF + '">\n'
        "<style>\n  " + _css(font_uri) + "\n</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        '  <div class="card">\n'
        '    {{ if .LogoData }}<div class="logo">{{.LogoData}}</div>{{ end }}\n'
        '    <div class="brand">' + theme.logo_svg(22)
        + '<span><span class="p">crew</span>&nbsp;~&nbsp;sign in</span></div>\n'
        '    <p class="sub">Authentication required to continue.</p>\n'
        '    {{ if .SignInMessage }}<p class="msg">{{.SignInMessage}}</p>{{ end }}\n'
        '    <form method="GET" action="{{.ProxyPrefix}}/start">\n'
        '      <input type="hidden" name="rd" value="{{.Redirect}}">\n'
        '      <button type="submit" class="btn">Sign in with {{.ProviderName}}</button>\n'
        "    </form>\n"
        "    {{ if .CustomLogin }}\n"
        '    <hr class="sep">\n'
        '    <form method="POST" action="{{.ProxyPrefix}}/sign_in">\n'
        '      <input type="hidden" name="rd" value="{{.Redirect}}">\n'
        '      <div class="field">\n'
        '        <label for="username">Username</label>\n'
        '        <input type="text" name="username" id="username" placeholder="you@example.com">\n'
        "      </div>\n"
        '      <div class="field">\n'
        '        <label for="password">Password</label>\n'
        '        <input type="password" name="password" id="password" placeholder="********">\n'
        "      </div>\n"
        '      <button type="submit" class="btn">Sign in</button>\n'
        "    </form>\n"
        "    {{ end }}\n"
        "    {{ if eq .StatusCode 400 401 }}\n"
        '    <div class="alert">\n'
        "      {{ if eq .StatusCode 400 }}{{.StatusCode}}: Username cannot be empty\n"
        "      {{ else }}{{.StatusCode}}: Invalid Username or Password{{ end }}\n"
        "    </div>\n"
        "    {{ end }}\n"
        "  </div>\n"
        + _FOOTER + "\n"
        "</main>\n"
        + _HASH_SCRIPT + "\n"
        "</body>\n"
        "</html>\n"
        "{{end}}\n"
    )


def render_error(font_uri: str) -> str:
    return (
        '{{define "error.html"}}\n'
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>{{.StatusCode}} {{.Title}}</title>\n"
        '<link rel="icon" href="' + theme.FAVICON_HREF + '">\n'
        "<style>\n  " + _css(font_uri) + "\n</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        '  <div class="card">\n'
        '    <div class="status">{{.StatusCode}}</div>\n'
        '    <h1 class="title">{{.Title}}</h1>\n'
        "    {{ if or .Message .RequestID }}\n"
        '    <div class="info">{{ if .Message }}{{.Message}}{{ end }}{{ if .RequestID }}\n'
        "Request ID: {{.RequestID}}{{ end }}</div>\n"
        "    {{ end }}\n"
        "    {{ if .Redirect }}\n"
        '    <hr class="sep">\n'
        '    <div class="cols">\n'
        '      <form method="GET" action="{{.Redirect}}">\n'
        '        <button type="submit" class="btn danger">Go back</button>\n'
        "      </form>\n"
        '      <form method="GET" action="{{.ProxyPrefix}}/sign_in">\n'
        '        <input type="hidden" name="rd" value="{{.Redirect}}">\n'
        '        <button type="submit" class="btn">Sign in</button>\n'
        "      </form>\n"
        "    </div>\n"
        "    {{ end }}\n"
        "  </div>\n"
        + _FOOTER + "\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
        "{{end}}\n"
    )


def write_templates(dest: Path) -> None:
    """Generate sign_in.html and error.html under ``dest`` for the auth
    container's ``OAUTH2_PROXY_CUSTOM_TEMPLATES_DIR`` bind mount. The files hold
    no secrets and are read by oauth2-proxy's non-root uid, so make them
    world-readable."""
    dest.mkdir(parents=True, exist_ok=True)
    dest.chmod(0o755)
    uri = font_data_uri()
    for name, text in (("sign_in.html", render_sign_in(uri)),
                       ("error.html", render_error(uri))):
        f = dest / name
        f.write_text(text)
        f.chmod(0o644)
