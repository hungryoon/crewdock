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


def test_router_image_and_build_argv():
    assert gateway.ROUTER_IMAGE == "crewdock-gateway-router:local"
    argv = gateway.router_build_argv("/repo")
    assert argv[:2] == ["docker", "build"]
    assert "-t" in argv and gateway.ROUTER_IMAGE in argv
    assert "-f" in argv
    assert argv[-1] == "/repo"


def test_router_run_argv():
    argv = gateway.router_run_argv(root_abs="/abs/root", router_port=9400,
                                   gateway_secret="S3CRET")
    assert argv[:7] == ["docker", "run", "-d", "--pull", "never",
                        "--name", "crew-gateway-router"]
    assert "--network" in argv and "host" in argv
    assert any(a == "/abs/root/instances:/crew/instances:ro" for a in argv)
    assert "CREW_ROUTER_PORT=9400" in argv
    assert "CREW_GATEWAY_SECRET=S3CRET" in argv
    assert "CREW_ROOT=/crew" in argv
    assert argv[-1] == gateway.ROUTER_IMAGE


import pytest
from crew.core.errors import ExposeError


def _full_shared(root):
    inst = root / "instances"
    inst.mkdir(exist_ok=True)
    (inst / "_shared.env").write_text(
        "CREW_GOOGLE_CLIENT_ID=cid\nCREW_GOOGLE_CLIENT_SECRET=sec\n"
        "CREW_OAUTH_COOKIE_SECRET=" + "a" * 32 + "\n")


def _published(root, name="alice", port=9120, emails="a@x.com"):
    d = root / "instances" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "instance.env").write_text(f"CREW_PORT={port}\nCREW_ALLOWED_EMAILS={emails}\n")
    (d / "exposed").write_text("")


def test_gateway_up_builds_runs_and_serves(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    cmds = []
    monkeypatch.setattr(gateway, "_run", lambda argv: cmds.append(argv))
    monkeypatch.setattr(gateway, "_run_quiet", lambda argv: cmds.append(("q", argv)))
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_repo_root", lambda: "/repo")

    info = gateway.gateway_up(tmp_path)

    assert info["url"] == "https://h.ts.net/"
    assert info["redirect_uri"] == "https://h.ts.net/oauth2/callback"
    run = [c for c in cmds if isinstance(c, list)]
    assert any(c[:2] == ["docker", "build"] for c in run)
    assert any(c[:2] == ["docker", "run"] for c in run)
    assert any(c[:2] == ["tailscale", "serve"] for c in run)
    emails = (tmp_path / "instances" / "_gateway" / "emails.txt").read_text()
    assert "a@x.com" in emails


def test_gateway_up_refuses_with_no_published(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    with pytest.raises(ExposeError, match="no published"):
        gateway.gateway_up(tmp_path)


def test_gateway_up_rolls_back_on_run_failure(tmp_path, monkeypatch):
    _full_shared(tmp_path)
    _published(tmp_path)
    monkeypatch.setattr(gateway, "_run_capture",
        lambda argv: '{"BackendState":"Running","Self":{"DNSName":"h.ts.net."}}')
    monkeypatch.setattr(gateway, "_repo_root", lambda: "/repo")
    quiet = []
    monkeypatch.setattr(gateway, "_run_quiet", lambda argv: quiet.append(argv))

    def fake_run(argv):
        if argv[:2] == ["tailscale", "serve"]:
            raise ExposeError("serve boom")
    monkeypatch.setattr(gateway, "_run", fake_run)

    from crew.core import paths
    gdir = paths.gateway_dir(tmp_path)

    with pytest.raises(ExposeError):
        gateway.gateway_up(tmp_path)
    # both containers removed during rollback
    assert any(q[:3] == ["docker", "rm", "-f"] and q[3] == gateway.ROUTER_CONTAINER
               for q in quiet)
    assert any(q[:3] == ["docker", "rm", "-f"] and q[3] == gateway.GATEWAY_AUTH_CONTAINER
               for q in quiet)
    # gdir is cleaned up on failure
    assert not gdir.exists()
