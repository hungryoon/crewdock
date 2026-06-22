import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .creds import parse_env_file
from .errors import CrewError, ExposeError, InstanceNotFoundError
from .ports import find_free_port
from . import paths

OAUTH2_IMAGE = "quay.io/oauth2-proxy/oauth2-proxy:v7.6.0"
AUTH_BASE_PORT = 9300
AUTH_MAX_PORT = 9399


@dataclass
class ExposeConfig:
    client_id: str
    client_secret: str
    cookie_secret: str
    allowed_emails: list[str]


_REQUIRED_SHARED = {
    "CREW_GOOGLE_CLIENT_ID": "client_id",
    "CREW_GOOGLE_CLIENT_SECRET": "client_secret",
    "CREW_OAUTH_COOKIE_SECRET": "cookie_secret",
}


def load_expose_config(root: Path, name: str) -> ExposeConfig:
    shared = parse_env_file(paths.shared_env_path(root))
    missing = [k for k in _REQUIRED_SHARED if not shared.get(k)]
    if missing:
        raise ExposeError(
            "missing Google OAuth config in instances/_shared.env: "
            + ", ".join(missing)
            + "\nadd CREW_GOOGLE_CLIENT_ID, CREW_GOOGLE_CLIENT_SECRET, and "
              "CREW_OAUTH_COOKIE_SECRET."
        )
    # The Google client/secret/cookie are shared, but the access whitelist is
    # per-instance ONLY: read from the instance's instance.env, never from
    # _shared.env — so a new instance can't silently inherit another's allow-list.
    inst = parse_env_file(paths.instance_env_path(root, name))
    emails = [
        e.strip()
        for e in inst.get("CREW_ALLOWED_EMAILS", "").split(",")
        if e.strip()
    ]
    if not emails:
        raise ExposeError(
            "CREW_ALLOWED_EMAILS is empty — refusing to expose with no access "
            f"whitelist. Set CREW_ALLOWED_EMAILS (comma-separated) in "
            f"instances/{name}/instance.env."
        )
    return ExposeConfig(
        client_id=shared["CREW_GOOGLE_CLIENT_ID"],
        client_secret=shared["CREW_GOOGLE_CLIENT_SECRET"],
        cookie_secret=shared["CREW_OAUTH_COOKIE_SECRET"],
        allowed_emails=emails,
    )


def auth_container_name(name: str) -> str:
    return f"{paths.project_name(name)}-auth"


def render_oauth2_env(cfg: ExposeConfig, authport: int, dashport: int,
                      redirect: str, cookie_name: str) -> str:
    lines = [
        "OAUTH2_PROXY_PROVIDER=google",
        f"OAUTH2_PROXY_CLIENT_ID={cfg.client_id}",
        f"OAUTH2_PROXY_CLIENT_SECRET={cfg.client_secret}",
        f"OAUTH2_PROXY_COOKIE_SECRET={cfg.cookie_secret}",
        # per-instance cookie name: all instances share one tailnet hostname, so
        # a shared name collides and breaks independent multi-instance sessions.
        f"OAUTH2_PROXY_COOKIE_NAME={cookie_name}",
        f"OAUTH2_PROXY_REDIRECT_URL={redirect}",
        f"OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:{dashport}/",
        f"OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:{authport}",
        # NO OAUTH2_PROXY_EMAIL_DOMAINS: a "*" wildcard is checked before the
        # emails file (OR logic) and would let ANY Google account in, bypassing
        # the whitelist. The authenticated-emails-file is the sole allowlist.
        "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/oauth2-proxy/emails.txt",
        "OAUTH2_PROXY_REVERSE_PROXY=true",
        "OAUTH2_PROXY_COOKIE_SECURE=true",
        # Rewrite the Host header to the upstream (127.0.0.1) instead of passing
        # the public tailnet hostname. Dashboards that validate the Host header
        # against their bind address (e.g. Hermes) otherwise reject the request.
        "OAUTH2_PROXY_PASS_HOST_HEADER=false",
    ]
    return "\n".join(lines) + "\n"


def oauth2_run_argv(name: str, env_file_abs: str, emails_file_abs: str) -> list[str]:
    return [
        "docker", "run", "-d", "--name", auth_container_name(name),
        "--network", "host", "--restart", "unless-stopped",
        "--env-file", env_file_abs,
        "-v", f"{emails_file_abs}:/etc/oauth2-proxy/emails.txt:ro",
        OAUTH2_IMAGE,
    ]


def serve_argv(https_port: int, authport: int) -> list[str]:
    return ["tailscale", "serve", "--bg", f"--https={https_port}",
            f"http://127.0.0.1:{authport}"]


def serve_off_argv(https_port: int) -> list[str]:
    return ["tailscale", "serve", f"--https={https_port}", "off"]


def _run_capture(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, check=True, text=True,
                              capture_output=True).stdout
    except FileNotFoundError as exc:
        raise ExposeError(f"{argv[0]} not found — is it installed?") from exc
    except subprocess.CalledProcessError as exc:
        raise ExposeError(
            f"{' '.join(argv)} failed (exit {exc.returncode})") from exc


def tailnet_dns_name(run_capture=_run_capture) -> str:
    data = json.loads(run_capture(["tailscale", "status", "--json"]))
    return data["Self"]["DNSName"].rstrip(".")


def redirect_url(host: str, https_port: int) -> str:
    return f"https://{host}:{https_port}/oauth2/callback"


def dashboard_url(host: str, https_port: int) -> str:
    return f"https://{host}:{https_port}/"


def check_tailscale_up(run_capture=_run_capture) -> None:
    data = json.loads(run_capture(["tailscale", "status", "--json"]))
    if data.get("BackendState") != "Running":
        raise ExposeError(
            "tailscale is not connected — run `tailscale up` first "
            "(and enable HTTPS for your tailnet)."
        )


def _run(argv: list[str]) -> None:
    try:
        subprocess.run(argv, check=True)
    except FileNotFoundError as exc:
        raise ExposeError(f"{argv[0]} not found — is it installed?") from exc
    except subprocess.CalledProcessError as exc:
        raise ExposeError(
            f"{' '.join(argv)} failed (exit {exc.returncode})") from exc


def _run_quiet(argv: list[str]) -> None:
    """Best-effort command for teardown; never raises."""
    subprocess.run(argv, check=False, capture_output=True)


def expose(root: Path, name: str) -> dict:
    if not paths.instance_dir(root, name).exists():
        raise InstanceNotFoundError(f"no such instance: {name}")
    cfg = load_expose_config(root, name)
    check_tailscale_up(run_capture=_run_capture)
    dashport = paths.read_port(root, name)
    if not dashport:
        raise ExposeError(f"no dashboard port recorded for {name}")
    host = tailnet_dns_name(run_capture=_run_capture)
    https_port = dashport
    redirect = redirect_url(host, https_port)
    authport = find_free_port(set(), base=AUTH_BASE_PORT, max_port=AUTH_MAX_PORT)

    edir = paths.expose_dir(root, name)
    edir.mkdir(parents=True, exist_ok=True)
    edir.chmod(0o700)
    emails_file = edir / "emails.txt"
    emails_file.write_text("\n".join(cfg.allowed_emails) + "\n")
    emails_file.chmod(0o600)
    env_file = edir / "oauth2.env"
    env_file.write_text(
        render_oauth2_env(cfg, authport, dashport, redirect,
                          cookie_name=f"_crew_{name}"))
    env_file.chmod(0o600)

    _run_quiet(["docker", "rm", "-f", auth_container_name(name)])
    _run(oauth2_run_argv(name, str(env_file.resolve()),
                         str(emails_file.resolve())))
    try:
        _run(serve_argv(https_port, authport))
    except CrewError:
        _run_quiet(["docker", "rm", "-f", auth_container_name(name)])
        raise

    return {
        "url": dashboard_url(host, https_port),
        "redirect_uri": redirect,
        "https_port": https_port,
    }


def unexpose(root: Path, name: str) -> None:
    dashport = paths.read_port(root, name)
    if dashport:
        _run_quiet(serve_off_argv(dashport))
    _run_quiet(["docker", "rm", "-f", auth_container_name(name)])
    edir = paths.expose_dir(root, name)
    if edir.exists():
        shutil.rmtree(edir, ignore_errors=True)


def is_exposed(name: str, run_capture=None) -> bool:
    # None sentinel (not a =_run_capture default) so it resolves at call time —
    # lets tests `monkeypatch.setattr(expose, "_run_capture", ...)` take effect.
    if run_capture is None:
        run_capture = _run_capture
    out = run_capture(
        ["docker", "ps", "-q", "-f", f"name=^{auth_container_name(name)}$"])
    return bool(out.strip())
