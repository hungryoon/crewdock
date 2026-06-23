from crew.gateway import routing
from crew.gateway.discovery import Published


def test_parse_instance_path():
    assert routing.parse_instance_path("/i/alice/foo/bar") == ("alice", "/foo/bar")
    assert routing.parse_instance_path("/i/alice") == ("alice", "/")
    assert routing.parse_instance_path("/i/alice/") == ("alice", "/")
    assert routing.parse_instance_path("/") is None
    assert routing.parse_instance_path("/oauth2/start") is None


def test_authorize():
    pubs = [Published("alice", 9120, ["a@x.com"]),
            Published("bob", 9121, ["b@y.com"])]
    assert routing.authorize("a@x.com", "alice", pubs) is True
    assert routing.authorize("b@y.com", "alice", pubs) is False  # not on alice
    assert routing.authorize("a@x.com", "ghost", pubs) is False  # unknown


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
    pubs = [Published("alice", 9120, ["a@x.com"]),
            Published("bob", 9121, ["b@y.com"])]
    html = routing.render_index("a@x.com", pubs)
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
