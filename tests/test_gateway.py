from crew.core import gateway
from crew.core.expose import ExposeConfig


def test_render_gateway_oauth2_env():
    cfg = ExposeConfig("cid", "sec", "c" * 32, [])
    txt = gateway.render_gateway_oauth2_env(
        cfg, authport=9401, routerport=9400,
        redirect="https://h.ts.net/oauth2/callback")
    assert "OAUTH2_PROXY_PROVIDER=google" in txt
    assert "OAUTH2_PROXY_CLIENT_ID=cid" in txt
    assert "OAUTH2_PROXY_REDIRECT_URL=https://h.ts.net/oauth2/callback" in txt
    assert "OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:9400/" in txt
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
    argv = gateway.router_run_argv(root_abs="/abs/root", router_port=9400)
    assert argv[:7] == ["docker", "run", "-d", "--pull", "never",
                        "--name", "crew-gateway-router"]
    assert "--network" in argv and "host" in argv
    assert any(a == "/abs/root/instances:/crew/instances:ro" for a in argv)
    assert "CREW_ROUTER_PORT=9400" in argv
    assert "CREW_ROOT=/crew" in argv
    assert argv[-1] == gateway.ROUTER_IMAGE
