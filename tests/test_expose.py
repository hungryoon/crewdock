import pytest

from crew.core import expose, paths
from crew.core.errors import ExposeError, InstanceNotFoundError


def _setup_shared(root, body):
    inst = root / "instances"
    inst.mkdir(exist_ok=True)
    (inst / "_shared.env").write_text(body)


def _shared_oauth(root):
    # shared infra only: client/secret/cookie. NO emails here — the whitelist
    # is per-instance.
    _setup_shared(root,
        "CREW_GOOGLE_CLIENT_ID=cid\n"
        "CREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "a" * 32 + "\n")



def test_serve_argv_on_and_off():
    assert expose.serve_argv(9120, 9300) == [
        "tailscale", "serve", "--bg", "--https=9120", "http://127.0.0.1:9300"]
    assert expose.serve_off_argv(9120) == [
        "tailscale", "serve", "--https=9120", "off"]


def test_tailnet_dns_name_strips_trailing_dot():
    payload = '{"BackendState":"Running","Self":{"DNSName":"box.tail1234.ts.net."}}'
    assert expose.tailnet_dns_name(run_capture=lambda argv: payload) \
        == "box.tail1234.ts.net"


def test_redirect_and_dashboard_url():
    assert expose.redirect_url("box.ts.net", 9120) \
        == "https://box.ts.net:9120/oauth2/callback"
    assert expose.dashboard_url("box.ts.net", 9120) == "https://box.ts.net:9120/"


def test_check_tailscale_up_passes_when_running():
    expose.check_tailscale_up(
        run_capture=lambda argv: '{"BackendState":"Running"}')  # no raise


def test_check_tailscale_up_raises_when_not_running():
    with pytest.raises(ExposeError, match="tailscale"):
        expose.check_tailscale_up(
            run_capture=lambda argv: '{"BackendState":"NoState"}')


def _setup_instance(root, name="alice", port=9120):
    d = root / "instances" / name
    d.mkdir(parents=True, exist_ok=True)
    # whitelist is per-instance — it lives in instance.env, not _shared.env
    (d / "instance.env").write_text(
        f"CREW_PORT={port}\nCREW_ALLOWED_EMAILS=a@x.com\n")


def _full_shared(root):
    # shared infra only — no emails (those are per-instance, in instance.env)
    _setup_shared(root,
        "CREW_GOOGLE_CLIENT_ID=cid\n"
        "CREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "a" * 32 + "\n")


def test_load_shared_oauth_reads_client_secret_cookie(tmp_path):
    _setup_shared(tmp_path,
        "CREW_GOOGLE_CLIENT_ID=cid\nCREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "a" * 32 + "\n")
    cfg = expose.load_shared_oauth(tmp_path)
    assert (cfg.client_id, cfg.client_secret) == ("cid", "sec")
    assert cfg.allowed_emails == []


def test_load_shared_oauth_missing_raises(tmp_path):
    _setup_shared(tmp_path, "CREW_GOOGLE_CLIENT_ID=cid\n")
    with pytest.raises(ExposeError, match="CREW_GOOGLE_CLIENT_SECRET"):
        expose.load_shared_oauth(tmp_path)


def test_expose_marks_published_and_regenerates_union(tmp_path, monkeypatch):
    _setup_instance(tmp_path)
    regen = []
    import crew.core.gateway as gateway
    monkeypatch.setattr(gateway, "gateway_running", lambda: True)
    monkeypatch.setattr(gateway, "regenerate_union_emails", lambda root: regen.append(root))
    expose.expose(tmp_path, "alice")
    assert paths.exposed_marker_path(tmp_path, "alice").exists()
    assert regen == [tmp_path]


def test_expose_requires_whitelist(tmp_path):
    d = tmp_path / "instances" / "alice"
    d.mkdir(parents=True)
    (d / "instance.env").write_text("CREW_PORT=9120\n")  # no emails
    with pytest.raises(ExposeError, match="CREW_ALLOWED_EMAILS"):
        expose.expose(tmp_path, "alice")


def test_expose_unknown_instance_raises(tmp_path):
    (tmp_path / "instances").mkdir()
    with pytest.raises(InstanceNotFoundError):
        expose.expose(tmp_path, "ghost")


def test_unexpose_removes_marker(tmp_path, monkeypatch):
    _setup_instance(tmp_path)
    import crew.core.gateway as gateway
    monkeypatch.setattr(gateway, "gateway_running", lambda: False)
    monkeypatch.setattr(gateway, "regenerate_union_emails", lambda root: None)
    paths.exposed_marker_path(tmp_path, "alice").write_text("")
    expose.unexpose(tmp_path, "alice")
    assert not paths.exposed_marker_path(tmp_path, "alice").exists()


def test_is_exposed_reflects_marker(tmp_path):
    _setup_instance(tmp_path)
    assert expose.is_exposed_for(tmp_path, "alice") is False
    paths.exposed_marker_path(tmp_path, "alice").write_text("")
    assert expose.is_exposed_for(tmp_path, "alice") is True
