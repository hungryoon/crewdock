from crew.core import gateway
from crew.core.expose import ExposeConfig


def test_render_gateway_oauth2_env():
    cfg = ExposeConfig("cid", "sec", "c" * 32, [])
    txt = gateway.render_gateway_oauth2_env(
        cfg, authport=9401, routerport=9400,
        redirect="https://h.ts.net/oauth2/callback", gateway_secret="S3CRET")
    assert "OAUTH2_PROXY_PROVIDER=google" in txt
    assert "OAUTH2_PROXY_CLIENT_ID=cid" in txt
    assert "OAUTH2_PROXY_REDIRECT_URL=https://h.ts.net/oauth2/callback" in txt
    assert "OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:9400/" in txt
    assert "OAUTH2_PROXY_BASIC_AUTH_PASSWORD=S3CRET" in txt
    assert "OAUTH2_PROXY_PASS_BASIC_AUTH=true" in txt
    assert "OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:9401" in txt
    assert "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/oauth2-proxy/emails.txt" in txt
    assert "OAUTH2_PROXY_PASS_USER_HEADERS=true" in txt
    assert "OAUTH2_PROXY_REVERSE_PROXY=true" in txt
    assert "OAUTH2_PROXY_PROXY_WEBSOCKETS=true" in txt
    assert "OAUTH2_PROXY_EMAIL_DOMAINS" not in txt


def test_router_build_argv():
    dep = _dep()
    argv = gateway.router_build_argv("/repo", dep.router_image())
    assert argv[:2] == ["docker", "build"]
    assert "-t" in argv and dep.router_image() in argv
    assert "-f" in argv
    assert argv[-1] == "/repo"


import pytest
from crew.core.errors import ExposeError
from crew.core.deployment import Deployment


def _dep():
    return Deployment(project="test", https_port=443, router_port=9400, auth_port=9401,
                      local_port=9402)


def _full_shared(root):
    data = root / "data"
    (data / "instances").mkdir(parents=True, exist_ok=True)
    (data / "_shared.env").write_text(
        "CREW_PROJECT=test\n"
        "CREW_GOOGLE_CLIENT_ID=cid\nCREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "a" * 32 + "\n")


def _published(root, name="alice", port=9120, emails="a@x.com"):
    d = root / "data" / "instances" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "instance.env").write_text(f"CREW_PORT={port}\nCREW_ALLOWED_EMAILS={emails}\n")


def test_gateway_up_builds_runs_and_serves(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    cmds = []
    monkeypatch.setattr(gateway, "_run", lambda argv: cmds.append(argv))
    monkeypatch.setattr(gateway, "_run_quiet", lambda argv: cmds.append(("q", argv)))
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_repo_root", gateway._repo_root)
    monkeypatch.setattr(gateway, "_container_exists", lambda name: False)
    monkeypatch.setattr(gateway, "_port_free", lambda port: True)
    monkeypatch.setattr(gateway, "_https_port_served", lambda port: False)

    info = gateway.gateway_up(tmp_path)

    assert info["url"] == "https://h.ts.net/"
    assert info["redirect_uri"] == "https://h.ts.net/oauth2/callback"
    assert info["no_whitelist"] is False
    run = [c for c in cmds if isinstance(c, list)]
    assert any(c[:2] == ["docker", "build"] for c in run)
    assert any(c[:2] == ["docker", "run"] for c in run)
    assert any(c[:2] == ["tailscale", "serve"] for c in run)
    emails = (tmp_path / "data" / "_gateway" / "emails.txt").read_text()
    assert "a@x.com" in emails


def test_gateway_up_warns_without_whitelist(tmp_path, monkeypatch):
    _full_shared(tmp_path)   # OAuth config + CREW_PROJECT, but NO instance/whitelist
    monkeypatch.setattr(gateway, "_run", lambda argv: None)
    monkeypatch.setattr(gateway, "_run_quiet", lambda argv: None)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_repo_root", lambda: ".")
    monkeypatch.setattr(gateway, "_require_build_context", lambda r: None)
    monkeypatch.setattr(gateway, "_container_exists", lambda name: False)
    monkeypatch.setattr(gateway, "_port_free", lambda port: True)
    monkeypatch.setattr(gateway, "_https_port_served", lambda port: False)
    info = gateway.gateway_up(tmp_path)          # must NOT raise
    assert info["no_whitelist"] is True
    assert info["local_url"] == "http://127.0.0.1:9402/"


def test_broker_build_and_run_argv():
    dep = _dep()
    bb = gateway.broker_build_argv("/repo", dep.broker_image())
    assert bb[:2] == ["docker", "build"]
    assert "-f" in bb and any("broker.Dockerfile" in a for a in bb)
    assert dep.broker_image() in bb
    br = gateway.broker_run_argv("/abs/gw/broker", "BSECRET",
                                 dep.broker_container(), dep.broker_image(), dep.project)
    assert br[:2] == ["docker", "run"]
    assert "test-gateway-broker" in br
    assert any(a == "/var/run/docker.sock:/var/run/docker.sock" for a in br)
    assert "CREW_BROKER_SECRET=BSECRET" in br
    assert "CREW_PROJECT=test" in br


def test_router_run_argv_gets_broker_wiring():
    dep = _dep()
    argv = gateway.router_run_argv("/abs/root", 9400, "S", "/abs/gw/broker",
                                   "BSECRET", dep.router_container(), dep.router_image())
    assert "test-gateway-router" in argv
    assert any(a == "/abs/gw/broker:/run/crew-broker" for a in argv)
    assert "CREW_BROKER_SECRET=BSECRET" in argv
    assert "CREW_BROKER_SOCK=/run/crew-broker/broker.sock" in argv


def test_gateway_up_rolls_back_on_run_failure(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_repo_root", gateway._repo_root)
    monkeypatch.setattr(gateway, "_container_exists", lambda name: False)
    monkeypatch.setattr(gateway, "_port_free", lambda port: True)
    monkeypatch.setattr(gateway, "_https_port_served", lambda port: False)
    quiet = []
    monkeypatch.setattr(gateway, "_run_quiet", lambda argv: quiet.append(argv))

    def fake_run(argv):
        if argv[:2] == ["tailscale", "serve"]:
            raise ExposeError("serve boom")
    monkeypatch.setattr(gateway, "_run", fake_run)

    from crew.core import paths
    gdir = paths.gateway_dir(tmp_path)
    dep = _dep()

    with pytest.raises(ExposeError):
        gateway.gateway_up(tmp_path)
    # both containers removed during rollback
    assert any(q[:3] == ["docker", "rm", "-f"] and q[3] == dep.router_container()
               for q in quiet)
    assert any(q[:3] == ["docker", "rm", "-f"] and q[3] == dep.auth_container()
               for q in quiet)
    # gdir is cleaned up on failure
    assert not gdir.exists()


def test_gateway_up_errors_when_already_up(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_container_exists", lambda name: True)
    with pytest.raises(ExposeError, match="already up"):
        gateway.gateway_up(tmp_path)


def test_gateway_up_errors_on_busy_port(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_container_exists", lambda name: False)
    monkeypatch.setattr(gateway, "_port_free", lambda port: False)
    with pytest.raises(ExposeError, match="in use"):
        gateway.gateway_up(tmp_path)


def test_gateway_up_errors_when_build_context_missing(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_container_exists", lambda name: False)
    monkeypatch.setattr(gateway, "_port_free", lambda port: True)
    monkeypatch.setattr(gateway, "_https_port_served", lambda port: False)
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    monkeypatch.setattr(gateway, "_repo_root", lambda: str(empty))
    with pytest.raises(ExposeError, match="source checkout"):
        gateway.gateway_up(tmp_path)


def test_gateway_reload_raises_when_down(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    monkeypatch.setattr(gateway, "gateway_running", lambda dep: False)
    with pytest.raises(ExposeError, match="not running"):
        gateway.gateway_reload(tmp_path)


def test_gateway_reload_regenerates_when_up(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    monkeypatch.setattr(gateway, "gateway_running", lambda dep: True)
    regen = []
    monkeypatch.setattr(gateway, "regenerate_union_emails", lambda r: regen.append(r))
    gateway.gateway_reload(tmp_path)
    assert regen == [tmp_path]


def test_local_run_argv():
    dep = _dep()
    argv = gateway.local_run_argv("/abs/root", dep.local_port, "/abs/gw/broker",
                                  "BSECRET", dep.local_container(), dep.router_image())
    assert argv[:2] == ["docker", "run"]
    assert "test-gateway-local" in argv
    assert "CREW_LOCAL_MODE=1" in argv
    assert "CREW_ROUTER_PORT=9402" in argv
    assert any(a == "/abs/gw/broker:/run/crew-broker" for a in argv)
    assert "CREW_BROKER_SECRET=BSECRET" in argv
    assert not any(a.startswith("CREW_GATEWAY_SECRET=") for a in argv)


def test_gateway_up_starts_local_view_and_returns_local_url(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    cmds = []
    monkeypatch.setattr(gateway, "_run", lambda argv: cmds.append(argv))
    monkeypatch.setattr(gateway, "_run_quiet", lambda argv: None)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_repo_root", lambda: ".")
    monkeypatch.setattr(gateway, "_require_build_context", lambda r: None)
    monkeypatch.setattr(gateway, "_container_exists", lambda name: False)
    monkeypatch.setattr(gateway, "_port_free", lambda port: True)
    monkeypatch.setattr(gateway, "_https_port_served", lambda port: False)
    info = gateway.gateway_up(tmp_path)
    assert info["local_url"] == "http://127.0.0.1:9402/"
    run = [c for c in cmds if isinstance(c, list)]
    assert any("test-gateway-local" in c for c in run)


def test_gateway_up_preflights_local_port(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_container_exists", lambda name: False)
    monkeypatch.setattr(gateway, "_port_free", lambda port: port != 9402)
    with pytest.raises(ExposeError, match="9402"):
        gateway.gateway_up(tmp_path)


def test_local_view_url_raises_when_down(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    monkeypatch.setattr(gateway, "gateway_running", lambda dep: False)
    with pytest.raises(ExposeError, match="not up"):
        gateway.local_view_url(tmp_path)


def test_local_view_url_when_up(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    monkeypatch.setattr(gateway, "gateway_running", lambda dep: True)
    assert gateway.local_view_url(tmp_path) == "http://127.0.0.1:9402/"
