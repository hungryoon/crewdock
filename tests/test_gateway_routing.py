from crew.gateway import routing
from crew.gateway.discovery import Published


def test_parse_instance_path():
    assert routing.parse_instance_path("/i/alice/foo/bar") == ("alice", "/foo/bar")
    assert routing.parse_instance_path("/i/alice") == ("alice", "/")
    assert routing.parse_instance_path("/i/alice/") == ("alice", "/")
    assert routing.parse_instance_path("/") is None
    assert routing.parse_instance_path("/oauth2/start") is None


def test_authorize():
    pubs = [Published("alice", "alice-aaaaaa", 9120, ["a@x.com"]),
            Published("bob", "bob-aaaaaa", 9121, ["b@y.com"])]
    assert routing.authorize("a@x.com", "alice", pubs) is True
    assert routing.authorize("b@y.com", "alice", pubs) is False  # not on alice
    assert routing.authorize("a@x.com", "ghost", pubs) is False  # unknown


def test_authorize_empty_whitelist_is_fail_closed():
    # The canonical "hidden" state under publish-by-default: an instance with an
    # empty CREW_ALLOWED_EMAILS is reachable by no one (no marker gate anymore).
    pubs = [Published("alice", "alice-aaaaaa", 9120, [])]
    assert routing.authorize("a@x.com", "alice", pubs) is False
    assert routing.authorize("", "alice", pubs) is False


def test_upstream_url():
    assert routing.upstream_url(9120, "/foo") == "http://127.0.0.1:9120/foo"
    assert routing.upstream_url(9120, "/") == "http://127.0.0.1:9120/"


def test_proxy_request_headers_sets_prefix_and_drops_hop_by_hop():
    incoming = {"Host": "h.ts.net", "Connection": "keep-alive",
                "Cookie": "x=1", "X-Forwarded-Email": "a@x.com"}
    out = routing.proxy_request_headers(incoming, prefix="/i/alice")
    assert out["X-Forwarded-Prefix"] == "/i/alice"
    assert "Connection" not in out          # hop-by-hop dropped
    assert "Host" not in out                # let client set upstream Host
    assert out["Cookie"] == "x=1"           # passthrough preserved


def test_ws_proxy_request_headers_rewrites_origin_to_upstream():
    # Browser sends the gateway's public origin; Hermes (bound to loopback)
    # only accepts an Origin targeting 127.0.0.1/localhost on WS upgrades.
    # The WS proxy must rewrite Origin to the exact upstream it dials.
    incoming = {"Host": "h.ts.net", "Connection": "Upgrade",
                "Origin": "https://h.ts.net", "Cookie": "x=1"}
    out = routing.ws_proxy_request_headers(incoming, prefix="/i/alice", port=9120)
    assert out["Origin"] == "http://127.0.0.1:9120"
    assert out["X-Forwarded-Prefix"] == "/i/alice"
    assert "Connection" not in out          # hop-by-hop dropped
    assert "Host" not in out                # let client set upstream Host
    assert out["Cookie"] == "x=1"           # passthrough preserved


def test_proxy_request_headers_leaves_origin_untouched():
    # The HTTP path must NOT rewrite Origin (only the WS path does).
    incoming = {"Origin": "https://h.ts.net"}
    out = routing.proxy_request_headers(incoming, prefix="/i/alice")
    assert out["Origin"] == "https://h.ts.net"


def test_render_index_lists_only_authorized():
    # render_index now takes card dicts; filtering is done upstream by _gather_cards
    cards = [{"name": "alice", "up": True, "image": "", "timezone": "", "created": ""}]
    html = routing.render_index("a@x.com", cards)
    assert "/i/alice/" in html
    assert "/i/bob/" not in html
    assert "a@x.com" in html


def test_render_index_empty_state():
    html = routing.render_index("a@x.com", [])
    assert "No instances" in html
    assert "a@x.com" in html


def test_gateway_secret_ok_disabled_without_secret():
    from crew.gateway import routing
    assert routing.gateway_secret_ok({}, None) is True
    assert routing.gateway_secret_ok({}, "") is True


def test_gateway_secret_ok_matches_basic_auth_password():
    import base64
    from crew.gateway import routing
    hdr = "Basic " + base64.b64encode(b"ted@x.com:S3CRET").decode()
    assert routing.gateway_secret_ok({"Authorization": hdr}, "S3CRET") is True


def test_gateway_secret_ok_rejects_wrong_or_missing():
    import base64
    from crew.gateway import routing
    assert routing.gateway_secret_ok({}, "S3CRET") is False
    hdr = "Basic " + base64.b64encode(b"ted@x.com:WRONG").decode()
    assert routing.gateway_secret_ok({"Authorization": hdr}, "S3CRET") is False


def test_proxy_request_headers_drops_authorization():
    from crew.gateway import routing
    out = routing.proxy_request_headers(
        {"Authorization": "Basic abc", "X-Foo": "1"}, "/i/a")
    assert "X-Foo" in out
    assert not any(k.lower() == "authorization" for k in out)


def test_render_index_shows_status_fields():
    from crew.gateway import routing
    cards = [{"name": "alice", "up": True, "image": "v2026.6.19",
              "timezone": "Asia/Seoul", "created": "2026-06-23"}]
    html = routing.render_index("a@x.com", cards)
    assert "alice" in html
    assert "/i/alice/" in html
    assert "v2026.6.19" in html
    assert "Asia/Seoul" in html
    assert "JetBrainsMono" in html            # @font-face present
    assert "/_assets/JetBrainsMono-Regular.woff2" in html
    assert 'data-name="alice"' in html        # JS refresh hook
    assert "a@x.com" in html


def test_render_index_marks_down():
    from crew.gateway import routing
    cards = [{"name": "bob", "up": False, "image": "latest",
              "timezone": "UTC", "created": ""}]
    html = routing.render_index("a@x.com", cards)
    assert "down" in html        # status token
    assert "bob" in html


def test_render_index_empty():
    from crew.gateway import routing
    assert "No instances" in routing.render_index("a@x.com", [])


def test_render_index_escapes():
    from crew.gateway import routing
    html = routing.render_index("<b>@x.com",
        [{"name": "<x>", "up": True, "image": "", "timezone": "", "created": ""}])
    assert "<b>@x.com" not in html      # escaped
    assert "&lt;x&gt;" in html


def test_short_image_prefers_tag():
    from crew.gateway import routing
    assert routing.short_image(
        "nousresearch/hermes-agent:v2026.6.19@sha256:9f367c7756ef00") == "v2026.6.19"
    assert routing.short_image("nousresearch/hermes-agent:latest") == "latest"


def test_short_image_falls_back_to_short_digest():
    from crew.gateway import routing
    assert routing.short_image(
        "nousresearch/hermes-agent@sha256:9f367c7756ef0011aa") == "@9f367c7756ef"
    assert routing.short_image("") == ""


def test_fmt_created():
    from crew.gateway import routing
    assert routing.fmt_created("20260623T024431Z") == "2026-06-23"
    assert routing.fmt_created("") == ""
    assert routing.fmt_created("garbage") == ""


def test_detail_kvs_includes_present_fields_only():
    from crew.gateway import routing
    c = {"type": "hermes", "image": "v1", "port": 9120, "timezone": "UTC",
         "created": "2026-06-23", "layers": ["k"], "credentials": ["anthropic"]}
    kvs = routing._detail_kvs(c)
    assert "hermes" in kvs and "v1" in kvs and ":9120" in kvs and "UTC" in kvs
    assert "2026-06-23" in kvs
    assert "layers: k" in kvs and "creds: anthropic" in kvs
    assert routing._detail_kvs({"name": "x"}) == []


def test_render_index_list_shows_details_and_rollback():
    from crew.gateway import routing
    cards = [{"name": "alice", "up": True, "image": "v1", "timezone": "UTC",
              "created": "2026-06-23", "type": "hermes", "port": 9120,
              "layers": ["knowledge"], "credentials": ["anthropic"], "rollback": True}]
    html = routing.render_index("a@x.com", cards)
    assert 'class="list"' in html
    assert 'class="row"' in html
    assert ":9120" in html
    assert "hermes" in html
    assert "layers: knowledge" in html
    assert "creds: anthropic" in html
    assert "rollback" in html


def test_render_index_has_setup_button_and_panel():
    from crew.gateway import routing
    cards = [{"name": "alice", "up": True, "image": "v1", "timezone": "UTC",
              "created": "2026-06-23", "type": "hermes", "port": 9120,
              "layers": [], "credentials": [], "rollback": False}]
    html = routing.render_index("a@x.com", cards)
    assert "model setup" in html.lower()
    assert 'data-setup="alice"' in html        # button hook
    assert "/_setup?" in html                   # JS opens the setup WS
    assert "openai-codex" in html               # provider option present


def test_render_index_model_setup_carries_instance_id():
    # The model-setup control targets the instance_id (hashed dir) so the broker
    # execs the real container; the card title / dashboard link / refresh hook
    # stay the base name.
    from crew.gateway import routing
    cards = [{"name": "ted", "instance_id": "ted-9b8c7d", "up": True,
              "image": "v1", "timezone": "UTC", "created": "2026-06-23",
              "type": "hermes", "port": 9120, "layers": [], "credentials": [],
              "rollback": False}]
    html = routing.render_index("a@x.com", cards)
    assert 'data-setup="ted-9b8c7d"' in html      # WS targets the instance_id
    assert 'data-label="ted"' in html             # modal title shows base name
    assert 'data-name="ted"' in html              # refresh hook = base name
    assert "/i/ted/" in html                       # dashboard link = base name
    assert 'data-name="ted-9b8c7d"' not in html    # not the hashed id


def test_render_index_llm_chip_connected_and_not_set():
    from crew.gateway import routing
    html = routing.render_index("u@x.com",
        [{"name": "a", "up": True, "model": "openai-codex", "model_ok": True}])
    assert "llm: openai-codex" in html
    assert 'class="llm ok"' in html
    html2 = routing.render_index("u@x.com",
        [{"name": "b", "up": True, "model": "", "model_ok": False}])
    assert "not set" in html2
    assert 'class="llm no"' in html2


def test_render_index_has_modal():
    from crew.gateway import routing
    html = routing.render_index("u@x.com", [{"name": "a", "up": True}])
    assert 'id="modal"' in html
    assert 'id="m-start"' in html
    assert 'id="m-out"' in html
    assert "openai-codex" in html


def test_render_index_emails_button_local_only():
    cards = [{"name": "alice", "up": True, "instance_id": "alice-aaaaaa"}]
    local = routing.render_index("local", cards, local=True)
    assert 'class="emails"' in local
    assert 'data-emails="alice-aaaaaa"' in local
    assert ".elist" in local            # emails CSS present in the local render
    # not present in the SSO (non-local) render
    sso = routing.render_index("a@x.com", cards, local=False)
    assert 'class="emails"' not in sso
    assert "emodal" not in sso
    assert ".elist" not in sso          # emails CSS must not leak into SSO output


def test_render_index_emails_modal_before_script():
    # The emails JS captures #emodal (and #e-* children) into top-level consts at
    # parse time, so the modal must appear BEFORE the <script> block — exactly like
    # the model #modal does. If it comes after, getElementById returns null and the
    # click handler dereferences null, so the button does nothing.
    cards = [{"name": "alice", "up": True, "instance_id": "alice-aaaaaa"}]
    html = routing.render_index("local", cards, local=True)
    assert html.index('id="emodal"') < html.index("<script>")


def test_render_index_default_is_non_local():
    cards = [{"name": "alice", "up": True, "instance_id": "alice-aaaaaa"}]
    assert 'class="emails"' not in routing.render_index("a@x.com", cards)


def test_instance_model_connected(tmp_path):
    import json
    from crew.gateway import discovery
    d = tmp_path / "data" / "instances" / "alice" / "data"
    d.mkdir(parents=True)
    (d / "auth.json").write_text(json.dumps(
        {"active_provider": "openai-codex", "credential_pool": ["openai-codex"]}))
    assert discovery.instance_model(tmp_path, "alice") == {
        "provider": "openai-codex", "connected": True}


def test_instance_model_not_connected_or_missing(tmp_path):
    import json
    from crew.gateway import discovery
    d = tmp_path / "data" / "instances" / "bob" / "data"
    d.mkdir(parents=True)
    (d / "auth.json").write_text(json.dumps(
        {"active_provider": "openai-codex", "credential_pool": []}))
    assert discovery.instance_model(tmp_path, "bob") == {
        "provider": "openai-codex", "connected": False}
    (tmp_path / "data" / "instances" / "carol" / "data").mkdir(parents=True)
    assert discovery.instance_model(tmp_path, "carol") == {
        "provider": "", "connected": False}
