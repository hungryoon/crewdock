import json
import secrets
import shutil
import socket
from pathlib import Path

from crew.core import paths
from crew.core.deployment import load_deployment
from crew.core.errors import ExposeError
from crew.core.expose import (
    OAUTH2_IMAGE, load_shared_oauth, _run, _run_quiet, _run_capture,
    tailnet_dns_name, check_tailscale_up, serve_argv, serve_off_argv,
)
from crew.gateway import discovery

BROKER_SOCK_DIR_CONTAINER = "/run/crew-broker"
BROKER_SOCK = "/run/crew-broker/broker.sock"


def _container_exists(name: str) -> bool:
    out = _run_capture(["docker", "ps", "-a", "-q", "-f", f"name=^{name}$"])
    return bool((out or "").strip())


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _https_port_served(port: int) -> bool:
    try:
        data = json.loads(_run_capture(["tailscale", "serve", "status", "--json"]))
    except Exception:
        return False
    return str(port) in (data.get("TCP") or {})


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


def router_build_argv(repo_root: str, image: str) -> list[str]:
    repo_root = str(repo_root)
    return [
        "docker", "build", "-t", image,
        "-f", f"{repo_root}/crew/gateway/Dockerfile", repo_root,
    ]


def broker_build_argv(repo_root: str, image: str) -> list[str]:
    repo_root = str(repo_root)
    return [
        "docker", "build", "-t", image,
        "-f", f"{repo_root}/crew/gateway/broker.Dockerfile", repo_root,
    ]


def broker_run_argv(sock_dir_host: str, broker_secret: str,
                    container: str, image: str, project: str) -> list[str]:
    return [
        "docker", "run", "-d", "--pull", "never", "--name", container,
        "--restart", "unless-stopped",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{sock_dir_host}:{BROKER_SOCK_DIR_CONTAINER}",
        "-e", f"CREW_BROKER_SECRET={broker_secret}",
        "-e", f"CREW_PROJECT={project}",
        image,
    ]


def router_run_argv(root_abs: str, router_port: int, gateway_secret: str,
                    broker_sock_dir_host: str, broker_secret: str,
                    container: str, image: str) -> list[str]:
    root_abs = str(root_abs)
    return [
        "docker", "run", "-d", "--pull", "never", "--name", container,
        "--network", "host", "--restart", "unless-stopped",
        "-v", f"{root_abs}/data/instances:/crew/data/instances:ro",
        "-v", f"{broker_sock_dir_host}:{BROKER_SOCK_DIR_CONTAINER}",
        "-e", f"CREW_ROUTER_PORT={router_port}",
        "-e", f"CREW_GATEWAY_SECRET={gateway_secret}",
        "-e", f"CREW_BROKER_SECRET={broker_secret}",
        "-e", f"CREW_BROKER_SOCK={BROKER_SOCK}",
        "-e", "CREW_ROOT=/crew",
        image,
    ]


def local_run_argv(root_abs: str, local_port: int, broker_sock_dir_host: str,
                   broker_secret: str, container: str, image: str) -> list[str]:
    root_abs = str(root_abs)
    return [
        "docker", "run", "-d", "--pull", "never", "--name", container,
        "--network", "host", "--restart", "unless-stopped",
        "-v", f"{root_abs}/data/instances:/crew/data/instances:ro",
        "-v", f"{broker_sock_dir_host}:{BROKER_SOCK_DIR_CONTAINER}",
        "-e", f"CREW_ROUTER_PORT={local_port}",
        "-e", "CREW_LOCAL_MODE=1",
        "-e", f"CREW_BROKER_SECRET={broker_secret}",
        "-e", f"CREW_BROKER_SOCK={BROKER_SOCK}",
        "-e", "CREW_ROOT=/crew",
        image,
    ]


def _repo_root() -> str:
    # crewdock checkout root: crew/core/gateway.py -> repo root is 3 parents up.
    return str(Path(__file__).resolve().parent.parent.parent)


def _require_build_context(repo_root: str) -> None:
    df = Path(repo_root) / "crew" / "gateway" / "Dockerfile"
    if not df.exists():
        raise ExposeError(
            "gateway build context not found — run crewdock from a source "
            "checkout (`uv sync` + `uv run crew ...`), not an installed package")


def gateway_up(root: Path) -> dict:
    cfg = load_shared_oauth(root)
    dep = load_deployment(root)
    check_tailscale_up(run_capture=_run_capture)
    emails = discovery.union_emails(root)
    if not emails:
        raise ExposeError(
            "no instance has a whitelist — set CREW_ALLOWED_EMAILS "
            "(comma-separated Google accounts) in instances/<name>/instance.env "
            "for at least one instance first.")
    host = tailnet_dns_name(run_capture=_run_capture)
    redirect = f"https://{host}/oauth2/callback"

    for c in (dep.router_container(), dep.auth_container(),
              dep.broker_container(), dep.local_container()):
        if _container_exists(c):
            raise ExposeError(
                f"project '{dep.project}' gateway is already up — "
                f"`crew gateway down` first")
    for port in (dep.router_port, dep.auth_port, dep.local_port):
        if not _port_free(port):
            raise ExposeError(f"port {port} is already in use")
    if _https_port_served(dep.https_port):
        raise ExposeError(
            f"tailnet HTTPS port {dep.https_port} is already served — "
            f"pick another CREW_GATEWAY_HTTPS_PORT or stop the other gateway")

    _require_build_context(_repo_root())

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
        cfg, dep.auth_port, dep.router_port, redirect, gateway_secret))
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
        _run(router_build_argv(_repo_root(), dep.router_image()))
        _run(broker_build_argv(_repo_root(), dep.broker_image()))
        _run(broker_run_argv(str(broker_dir.resolve()), broker_secret,
                             dep.broker_container(), dep.broker_image(), dep.project))
        _run(router_run_argv(str(root.resolve()), dep.router_port, gateway_secret,
                             str(broker_dir.resolve()), broker_secret,
                             dep.router_container(), dep.router_image()))
        _run([
            "docker", "run", "-d", "--name", dep.auth_container(),
            "--network", "host", "--restart", "unless-stopped",
            "--env-file", str(env_file.resolve()),
            "-v", f"{emails_file.resolve()}:/etc/oauth2-proxy/emails.txt:ro",
            OAUTH2_IMAGE,
        ])
        _run(local_run_argv(str(root.resolve()), dep.local_port,
                            str(broker_dir.resolve()), broker_secret,
                            dep.local_container(), dep.router_image()))
        _run(serve_argv(dep.https_port, dep.auth_port))
    except ExposeError:
        _run_quiet(serve_off_argv(dep.https_port))
        _run_quiet(["docker", "rm", "-f", dep.auth_container()])
        _run_quiet(["docker", "rm", "-f", dep.router_container()])
        _run_quiet(["docker", "rm", "-f", dep.broker_container()])
        _run_quiet(["docker", "rm", "-f", dep.local_container()])
        shutil.rmtree(gdir, ignore_errors=True)
        raise
    return {"url": f"https://{host}/", "redirect_uri": redirect,
            "local_url": f"http://127.0.0.1:{dep.local_port}/"}


def gateway_down(root: Path) -> None:
    dep = load_deployment(root)
    _run_quiet(serve_off_argv(dep.https_port))
    _run_quiet(["docker", "rm", "-f", dep.auth_container()])
    _run_quiet(["docker", "rm", "-f", dep.router_container()])
    _run_quiet(["docker", "rm", "-f", dep.broker_container()])
    _run_quiet(["docker", "rm", "-f", dep.local_container()])
    gdir = paths.gateway_dir(root)
    if gdir.exists():
        shutil.rmtree(gdir, ignore_errors=True)


def regenerate_union_emails(root: Path) -> None:
    """Rewrite the union emails file if the gateway dir exists (oauth2-proxy watches it)."""
    f = paths.gateway_dir(root) / "emails.txt"
    if f.exists():
        f.write_text("\n".join(discovery.union_emails(root)) + "\n")


def gateway_reload(root: Path) -> None:
    """Re-derive the SSO allowlist from current instance whitelists. Use after
    hand-editing CREW_ALLOWED_EMAILS so oauth2-proxy picks up added/removed
    accounts (it watches emails.txt)."""
    dep = load_deployment(root)
    if not gateway_running(dep):
        raise ExposeError("gateway is not running — `crew gateway up` first.")
    regenerate_union_emails(root)


def local_view_url(root: Path) -> str:
    dep = load_deployment(root)
    if not gateway_running(dep):
        raise ExposeError("gateway is not up — `crew gateway up` first.")
    return f"http://127.0.0.1:{dep.local_port}/"


def gateway_running(dep, run_capture=_run_capture) -> bool:
    out = run_capture(
        ["docker", "ps", "-q", "-f", f"name=^{dep.router_container()}$"])
    return bool(out.strip())
