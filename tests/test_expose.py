import pytest

from crew.core import expose
from crew.core.errors import ExposeError


def _setup_shared(root, body):
    inst = root / "instances"
    inst.mkdir(exist_ok=True)
    (inst / "_shared.env").write_text(body)


def test_load_expose_config_reads_shared_env(tmp_path):
    _setup_shared(tmp_path,
        "CREW_GOOGLE_CLIENT_ID=cid\n"
        "CREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "a" * 32 + "\n"
        "CREW_ALLOWED_EMAILS=a@x.com, b@y.com\n")
    cfg = expose.load_expose_config(tmp_path)
    assert cfg.client_id == "cid"
    assert cfg.client_secret == "sec"
    assert cfg.cookie_secret == "a" * 32
    assert cfg.allowed_emails == ["a@x.com", "b@y.com"]


def test_load_expose_config_missing_secret_raises(tmp_path):
    _setup_shared(tmp_path, "CREW_GOOGLE_CLIENT_ID=cid\n")
    with pytest.raises(ExposeError, match="CREW_GOOGLE_CLIENT_SECRET"):
        expose.load_expose_config(tmp_path)


def test_load_expose_config_allows_missing_emails(tmp_path):
    _setup_shared(tmp_path,
        "CREW_GOOGLE_CLIENT_ID=cid\n"
        "CREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "z" * 32 + "\n")
    cfg = expose.load_expose_config(tmp_path)
    assert cfg.allowed_emails == []


def test_render_oauth2_env_contains_all_keys():
    cfg = expose.ExposeConfig("cid", "sec", "c" * 32, ["a@x.com"])
    txt = expose.render_oauth2_env(
        cfg, authport=9300, dashport=9120,
        redirect="https://h.ts.net:9120/oauth2/callback")
    assert "OAUTH2_PROXY_PROVIDER=google" in txt
    assert "OAUTH2_PROXY_CLIENT_ID=cid" in txt
    assert "OAUTH2_PROXY_CLIENT_SECRET=sec" in txt
    assert "OAUTH2_PROXY_COOKIE_SECRET=" + "c" * 32 in txt
    assert "OAUTH2_PROXY_REDIRECT_URL=https://h.ts.net:9120/oauth2/callback" in txt
    assert "OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:9120/" in txt
    assert "OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:9300" in txt
    assert "OAUTH2_PROXY_EMAIL_DOMAINS=*" in txt
    assert "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/oauth2-proxy/emails.txt" in txt
    assert "OAUTH2_PROXY_REVERSE_PROXY=true" in txt


def test_auth_container_name():
    assert expose.auth_container_name("alice") == "crew-alice-auth"


def test_oauth2_run_argv_shape():
    argv = expose.oauth2_run_argv("alice", "/e/oauth2.env", "/e/emails.txt")
    assert argv[:5] == ["docker", "run", "-d", "--name", "crew-alice-auth"]
    assert "--network" in argv and "host" in argv
    assert "--env-file" in argv and "/e/oauth2.env" in argv
    assert any(a == "/e/emails.txt:/etc/oauth2-proxy/emails.txt:ro" for a in argv)
    assert argv[-1] == expose.OAUTH2_IMAGE


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
