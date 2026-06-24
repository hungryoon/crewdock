from crew.gateway import signin, theme


# --- shared theme tokens ---

def test_theme_palette_has_gateway_accent():
    # The sign-in page must reuse the same accent as render_index so the login
    # flow and the instance dashboard read as one UI.
    assert theme.PALETTE["accent"] == "#58e6a8"
    assert theme.PALETTE["bg"] == "#0e1116"
    assert "--accent:#58e6a8;" in theme.ROOT_VARS
    assert "color-scheme: dark light;" in theme.ROOT_VARS


# --- font inlining ---

def test_font_data_uri_is_inline_woff2():
    uri = signin.font_data_uri()
    assert uri.startswith("data:font/woff2;base64,")
    assert len(uri) > 100   # real font bytes, not an empty placeholder


# --- sign_in.html template ---

def test_render_sign_in_keeps_go_template_contract():
    html = signin.render_sign_in("data:font/woff2;base64,AAAA")
    # Go template wrapper oauth2-proxy requires to register the override
    assert html.startswith('{{define "sign_in.html"}}')
    assert html.rstrip().endswith("{{end}}")
    # the Google login flow must stay intact
    assert 'action="{{.ProxyPrefix}}/start"' in html
    assert 'name="rd" value="{{.Redirect}}"' in html
    assert "{{.ProviderName}}" in html


def test_render_sign_in_unifies_with_gateway_design():
    html = signin.render_sign_in("data:font/woff2;base64,AAAA")
    assert "data:font/woff2;base64,AAAA" in html      # font inlined, not /_assets
    assert "JetBrainsMono" in html
    assert theme.PALETTE["accent"] in html            # same palette as render_index
    # the default oauth2-proxy chrome (Bulma) must be gone
    assert "bulma.min.css" not in html


def test_render_sign_in_preserves_status_and_message_blocks():
    html = signin.render_sign_in("data:font/woff2;base64,AAAA")
    assert "{{ if .SignInMessage }}" in html
    assert "{{ if eq .StatusCode 400 401 }}" in html


# --- error.html template ---

def test_render_error_keeps_go_template_contract():
    html = signin.render_error("data:font/woff2;base64,AAAA")
    assert html.startswith('{{define "error.html"}}')
    assert html.rstrip().endswith("{{end}}")
    assert "{{.StatusCode}}" in html
    assert "{{.Title}}" in html
    assert 'action="{{.ProxyPrefix}}/sign_in"' in html
    assert 'action="{{.Redirect}}"' in html


def test_render_error_unifies_with_gateway_design():
    html = signin.render_error("data:font/woff2;base64,BBBB")
    assert "data:font/woff2;base64,BBBB" in html
    assert theme.PALETTE["accent"] in html
    assert "bulma.min.css" not in html


# --- writing templates to disk for the bind mount ---

def test_write_templates_creates_world_readable_files(tmp_path):
    dest = tmp_path / "templates"
    signin.write_templates(dest)
    sign_in = dest / "sign_in.html"
    error = dest / "error.html"
    assert sign_in.exists() and error.exists()
    # oauth2-proxy runs as a non-root uid inside the container and reads these
    # over a bind mount; they hold no secrets, so make them readable.
    assert (dest.stat().st_mode & 0o777) == 0o755
    assert (sign_in.stat().st_mode & 0o777) == 0o644
    assert (error.stat().st_mode & 0o777) == 0o644
    # font is inlined into the written file
    assert "data:font/woff2;base64," in sign_in.read_text()
