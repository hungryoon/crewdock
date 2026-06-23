import secrets
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
BROKER_IMAGE = "crewdock-gateway-broker:local"
BROKER_CONTAINER = "crew-gateway-broker"
BROKER_SOCK_DIR_CONTAINER = "/run/crew-broker"
BROKER_SOCK = "/run/crew-broker/broker.sock"


def render_gateway_oauth2_env(cfg, authport: int, routerport: int,
                              redirect: str, gateway_secret: str) -> str:
    lines = [
        "OAUTH2_PROXY_PROVIDER=google",
        f"OAUTH2_PROXY_CLIENT_ID={cfg.client_id}",
        f"OAUTH2_PROXY_CLIENT_SECRET={cfg.client_secret}",
        f"OAUTH2_PROXY_COOKIE_SECRET={cfg.cookie_secret}",
        f"OAUTH2_PROXY_REDIRECT_URL={redirect}",
        f"OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:{routerport}/",
        f"OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:{authport}",
        "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/oauth2-proxy/emails.txt",
        "OAUTH2_PROXY_PASS_USER_HEADERS=true",
        # Inject a shared secret as the Basic-auth password on every upstream
        # request; the router verifies it so a host-networked instance can't
        # bypass oauth2-proxy and spoof X-Forwarded-Email.
        "OAUTH2_PROXY_PASS_BASIC_AUTH=true",
        f"OAUTH2_PROXY_BASIC_AUTH_PASSWORD={gateway_secret}",
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


def broker_build_argv(repo_root: str) -> list[str]:
    repo_root = str(repo_root)
    return [
        "docker", "build", "-t", BROKER_IMAGE,
        "-f", f"{repo_root}/crew/gateway/broker.Dockerfile", repo_root,
    ]


def broker_run_argv(sock_dir_host: str, broker_secret: str) -> list[str]:
    return [
        "docker", "run", "-d", "--pull", "never", "--name", BROKER_CONTAINER,
        "--restart", "unless-stopped",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{sock_dir_host}:{BROKER_SOCK_DIR_CONTAINER}",
        "-e", f"CREW_BROKER_SECRET={broker_secret}",
        BROKER_IMAGE,
    ]


def router_run_argv(root_abs: str, router_port: int, gateway_secret: str,
                    broker_sock_dir_host: str, broker_secret: str) -> list[str]:
    root_abs = str(root_abs)
    return [
        "docker", "run", "-d", "--pull", "never", "--name", ROUTER_CONTAINER,
        "--network", "host", "--restart", "unless-stopped",
        "-v", f"{root_abs}/instances:/crew/instances:ro",
        "-v", f"{broker_sock_dir_host}:{BROKER_SOCK_DIR_CONTAINER}",
        "-e", f"CREW_ROUTER_PORT={router_port}",
        "-e", f"CREW_GATEWAY_SECRET={gateway_secret}",
        "-e", f"CREW_BROKER_SECRET={broker_secret}",
        "-e", f"CREW_BROKER_SOCK={BROKER_SOCK}",
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
    # Shared secret bridging oauth2-proxy and the router (anti-spoof). Generated
    # per gateway start; both processes come up together so they always agree.
    gateway_secret = secrets.token_urlsafe(32)
    broker_secret = secrets.token_urlsafe(32)
    broker_dir = gdir / "broker"
    broker_dir.mkdir(exist_ok=True)
    broker_dir.chmod(0o711)   # non-root broker/router uids traverse to the socket
    env_file = gdir / "oauth2.env"
    env_file.write_text(render_gateway_oauth2_env(
        cfg, GATEWAY_AUTH_PORT, ROUTER_PORT, redirect, gateway_secret))
    env_file.chmod(0o600)

    # SECURITY NOTE: the router listens on TCP 127.0.0.1:ROUTER_PORT and trusts
    # the X-Forwarded-Email oauth2-proxy sets. Instances run with host networking
    # and share this loopback, so a compromised instance could reach the router
    # directly and spoof that header. Acceptable for a single trusted operator on
    # a private tailnet; HARDEN before multi-user (e.g. a shared-secret header
    # only oauth2-proxy injects). A unix-socket upstream would close this, but
    # oauth2-proxy v7.6.0 cannot proxy WebSockets over a unix socket
    # ("unsupported protocol scheme unix" -> 502), which breaks chat/events.
    try:
        _run(router_build_argv(_repo_root()))
        _run(broker_build_argv(_repo_root()))
        _run_quiet(["docker", "rm", "-f", BROKER_CONTAINER])
        _run(broker_run_argv(str(broker_dir.resolve()), broker_secret))
        _run_quiet(["docker", "rm", "-f", ROUTER_CONTAINER])
        _run(router_run_argv(str(root.resolve()), ROUTER_PORT, gateway_secret,
                             str(broker_dir.resolve()), broker_secret))
        _run_quiet(["docker", "rm", "-f", GATEWAY_AUTH_CONTAINER])
        _run([
            "docker", "run", "-d", "--name", GATEWAY_AUTH_CONTAINER,
            "--network", "host", "--restart", "unless-stopped",
            "--env-file", str(env_file.resolve()),
            "-v", f"{emails_file.resolve()}:/etc/oauth2-proxy/emails.txt:ro",
            OAUTH2_IMAGE,
        ])
        _run(serve_argv(GATEWAY_HTTPS_PORT, GATEWAY_AUTH_PORT))
    except ExposeError:
        _run_quiet(serve_off_argv(GATEWAY_HTTPS_PORT))
        _run_quiet(["docker", "rm", "-f", GATEWAY_AUTH_CONTAINER])
        _run_quiet(["docker", "rm", "-f", ROUTER_CONTAINER])
        _run_quiet(["docker", "rm", "-f", BROKER_CONTAINER])
        shutil.rmtree(gdir, ignore_errors=True)
        raise
    return {"url": f"https://{host}/", "redirect_uri": redirect}


def gateway_down(root: Path) -> None:
    _run_quiet(serve_off_argv(GATEWAY_HTTPS_PORT))
    _run_quiet(["docker", "rm", "-f", GATEWAY_AUTH_CONTAINER])
    _run_quiet(["docker", "rm", "-f", ROUTER_CONTAINER])
    _run_quiet(["docker", "rm", "-f", BROKER_CONTAINER])
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
