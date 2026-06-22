import shutil
from pathlib import Path

from crew.core import paths
from crew.core.errors import ExposeError
from crew.core.expose import (
    OAUTH2_IMAGE, load_shared_oauth, _run, _run_quiet, _run_capture,
    tailnet_dns_name, check_tailscale_up, serve_argv, serve_off_argv,
)
from crew.gateway import discovery

ROUTER_IMAGE = "crewdock-gateway-router:local"
ROUTER_CONTAINER = "crew-gateway-router"
GATEWAY_AUTH_CONTAINER = "crew-gateway-auth"
ROUTER_PORT = 9400
GATEWAY_AUTH_PORT = 9401
GATEWAY_HTTPS_PORT = 443
ROUTER_SOCK_DIR_CONTAINER = "/run/crew-gw"
ROUTER_SOCK = "/run/crew-gw/router.sock"


def render_gateway_oauth2_env(cfg, authport: int, redirect: str) -> str:
    lines = [
        "OAUTH2_PROXY_PROVIDER=google",
        f"OAUTH2_PROXY_CLIENT_ID={cfg.client_id}",
        f"OAUTH2_PROXY_CLIENT_SECRET={cfg.client_secret}",
        f"OAUTH2_PROXY_COOKIE_SECRET={cfg.cookie_secret}",
        f"OAUTH2_PROXY_REDIRECT_URL={redirect}",
        f"OAUTH2_PROXY_UPSTREAMS=unix://{ROUTER_SOCK}",
        f"OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:{authport}",
        "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/oauth2-proxy/emails.txt",
        "OAUTH2_PROXY_PASS_USER_HEADERS=true",
        "OAUTH2_PROXY_REVERSE_PROXY=true",
        "OAUTH2_PROXY_PROXY_WEBSOCKETS=true",
        "OAUTH2_PROXY_COOKIE_SECURE=true",
    ]
    return "\n".join(lines) + "\n"


def router_build_argv(repo_root: str) -> list[str]:
    repo_root = str(repo_root)
    return [
        "docker", "build", "-t", ROUTER_IMAGE,
        "-f", f"{repo_root}/crew/gateway/Dockerfile", repo_root,
    ]


def router_run_argv(root_abs: str, sock_dir_host: str) -> list[str]:
    root_abs = str(root_abs)
    return [
        "docker", "run", "-d", "--pull", "never", "--name", ROUTER_CONTAINER,
        "--network", "host", "--restart", "unless-stopped",
        "-v", f"{root_abs}/instances:/crew/instances:ro",
        "-v", f"{sock_dir_host}:{ROUTER_SOCK_DIR_CONTAINER}",
        "-e", f"CREW_ROUTER_SOCK={ROUTER_SOCK}",
        "-e", "CREW_ROOT=/crew",
        ROUTER_IMAGE,
    ]


def _repo_root() -> str:
    # crewdock checkout root: crew/core/gateway.py -> repo root is 3 parents up.
    return str(Path(__file__).resolve().parent.parent.parent)


def gateway_up(root: Path) -> dict:
    cfg = load_shared_oauth(root)
    check_tailscale_up(run_capture=_run_capture)
    pubs = discovery.published_instances(root)
    if not pubs:
        raise ExposeError("no published instances — `crew expose <name>` first.")
    emails = discovery.union_emails(root)
    host = tailnet_dns_name(run_capture=_run_capture)
    redirect = f"https://{host}/oauth2/callback"

    gdir = paths.gateway_dir(root)
    gdir.mkdir(parents=True, exist_ok=True)
    gdir.chmod(0o700)
    emails_file = gdir / "emails.txt"
    emails_file.write_text("\n".join(emails) + "\n")
    emails_file.chmod(0o600)
    sock_dir = gdir / "run"
    sock_dir.mkdir(exist_ok=True)
    # 0711: oauth2-proxy runs as a non-root uid and must traverse this dir to
    # reach the socket; the parent gdir is 0700 and the dir is only bind-mounted
    # into the trusted router + auth containers. The socket itself is chmod 0666
    # by the router (see router.py main). If a live `crew gateway up` smoke test
    # shows oauth2-proxy cannot connect, the fallback is `--user 0:0` on the auth
    # container or 0o777 here. THIS WIRING IS UNVERIFIED IN CI — needs a live test.
    sock_dir.chmod(0o711)
    env_file = gdir / "oauth2.env"
    env_file.write_text(render_gateway_oauth2_env(cfg, GATEWAY_AUTH_PORT, redirect))
    env_file.chmod(0o600)

    # NOTE: This whole gateway wiring (router on a unix socket, oauth2-proxy
    # unix:// upstream, perms above) CANNOT be verified in CI — it needs a live
    # `crew gateway up` smoke test with real Tailscale + Docker + oauth2-proxy
    # v7.6.0 + Google OAuth. Verify the auth container can connect to the socket
    # there; see the perms fallbacks noted on sock_dir above.
    try:
        _run(router_build_argv(_repo_root()))
        _run_quiet(["docker", "rm", "-f", ROUTER_CONTAINER])
        _run(router_run_argv(str(root.resolve()), str(sock_dir.resolve())))
        _run_quiet(["docker", "rm", "-f", GATEWAY_AUTH_CONTAINER])
        _run([
            "docker", "run", "-d", "--name", GATEWAY_AUTH_CONTAINER,
            "--network", "host", "--restart", "unless-stopped",
            "--env-file", str(env_file.resolve()),
            "-v", f"{emails_file.resolve()}:/etc/oauth2-proxy/emails.txt:ro",
            "-v", f"{sock_dir.resolve()}:{ROUTER_SOCK_DIR_CONTAINER}",
            OAUTH2_IMAGE,
        ])
        _run(serve_argv(GATEWAY_HTTPS_PORT, GATEWAY_AUTH_PORT))
    except ExposeError:
        _run_quiet(serve_off_argv(GATEWAY_HTTPS_PORT))
        _run_quiet(["docker", "rm", "-f", GATEWAY_AUTH_CONTAINER])
        _run_quiet(["docker", "rm", "-f", ROUTER_CONTAINER])
        shutil.rmtree(gdir, ignore_errors=True)
        raise
    return {"url": f"https://{host}/", "redirect_uri": redirect}


def gateway_down(root: Path) -> None:
    _run_quiet(serve_off_argv(GATEWAY_HTTPS_PORT))
    _run_quiet(["docker", "rm", "-f", GATEWAY_AUTH_CONTAINER])
    _run_quiet(["docker", "rm", "-f", ROUTER_CONTAINER])
    gdir = paths.gateway_dir(root)
    if gdir.exists():
        shutil.rmtree(gdir, ignore_errors=True)


def regenerate_union_emails(root: Path) -> None:
    """Rewrite the union emails file if the gateway dir exists (oauth2-proxy watches it)."""
    f = paths.gateway_dir(root) / "emails.txt"
    if f.exists():
        f.write_text("\n".join(discovery.union_emails(root)) + "\n")


def gateway_running(run_capture=_run_capture) -> bool:
    out = run_capture(["docker", "ps", "-q", "-f", f"name=^{ROUTER_CONTAINER}$"])
    return bool(out.strip())
