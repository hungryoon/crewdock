import pytest

from crew.core import expose
from crew.core.errors import ExposeError


def _setup_shared(root, body):
    data = root / "data"
    data.mkdir(exist_ok=True)
    (data / "_shared.env").write_text(body)


def test_serve_argv_on_and_off():
    ts = expose.tailscale_bin()
    assert expose.serve_argv(9120, 9300) == [
        ts, "serve", "--bg", "--https=9120", "http://127.0.0.1:9300"]
    assert expose.serve_off_argv(9120) == [
        ts, "serve", "--https=9120", "off"]


def test_tailscale_bin_prefers_path(monkeypatch):
    monkeypatch.setattr(expose.shutil, "which", lambda _: "/usr/bin/tailscale")
    assert expose.tailscale_bin() == "/usr/bin/tailscale"


def test_tailscale_bin_falls_back_to_macos_app_bundle(monkeypatch):
    monkeypatch.setattr(expose.shutil, "which", lambda _: None)
    monkeypatch.setattr(expose.os.path, "exists",
                        lambda p: p == expose.TAILSCALE_APP_BIN)
    assert expose.tailscale_bin() == expose.TAILSCALE_APP_BIN


def test_tailscale_bin_stays_bare_when_nothing_found(monkeypatch):
    monkeypatch.setattr(expose.shutil, "which", lambda _: None)
    monkeypatch.setattr(expose.os.path, "exists", lambda _: False)
    assert expose.tailscale_bin() == "tailscale"


def test_tailnet_dns_name_strips_trailing_dot():
    payload = '{"BackendState":"Running","Self":{"DNSName":"box.tail1234.ts.net."}}'
    assert expose.tailnet_dns_name(run_capture=lambda argv: payload) \
        == "box.tail1234.ts.net"


def test_check_tailscale_up_passes_when_running():
    expose.check_tailscale_up(
        run_capture=lambda argv: '{"BackendState":"Running"}')  # no raise


def test_check_tailscale_up_raises_when_not_running():
    with pytest.raises(ExposeError, match="tailscale"):
        expose.check_tailscale_up(
            run_capture=lambda argv: '{"BackendState":"NoState"}')


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
