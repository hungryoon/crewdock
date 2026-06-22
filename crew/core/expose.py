import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .creds import parse_env_file
from .errors import ExposeError, InstanceNotFoundError
from . import paths

OAUTH2_IMAGE = "quay.io/oauth2-proxy/oauth2-proxy:v7.6.0"


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


def load_shared_oauth(root: Path) -> ExposeConfig:
    shared = parse_env_file(paths.shared_env_path(root))
    missing = [k for k in _REQUIRED_SHARED if not shared.get(k)]
    if missing:
        raise ExposeError(
            "missing Google OAuth config in instances/_shared.env: "
            + ", ".join(missing)
            + "\nadd CREW_GOOGLE_CLIENT_ID, CREW_GOOGLE_CLIENT_SECRET, and "
              "CREW_OAUTH_COOKIE_SECRET."
        )
    return ExposeConfig(
        client_id=shared["CREW_GOOGLE_CLIENT_ID"],
        client_secret=shared["CREW_GOOGLE_CLIENT_SECRET"],
        cookie_secret=shared["CREW_OAUTH_COOKIE_SECRET"],
        allowed_emails=[],
    )


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


def expose(root: Path, name: str) -> None:
    """Publish an instance to the gateway (mark it; require a whitelist)."""
    if not paths.instance_dir(root, name).exists():
        raise InstanceNotFoundError(f"no such instance: {name}")
    raw = parse_env_file(paths.instance_env_path(root, name)).get(
        "CREW_ALLOWED_EMAILS", "")
    if not [e for e in raw.split(",") if e.strip()]:
        raise ExposeError(
            "CREW_ALLOWED_EMAILS is empty — set it (comma-separated) in "
            f"instances/{name}/instance.env before exposing."
        )
    paths.exposed_marker_path(root, name).write_text("")
    from crew.core import gateway
    if gateway.gateway_running():
        gateway.regenerate_union_emails(root)


def unexpose(root: Path, name: str) -> None:
    marker = paths.exposed_marker_path(root, name)
    if marker.exists():
        marker.unlink()
    from crew.core import gateway
    if gateway.gateway_running():
        gateway.regenerate_union_emails(root)


def is_exposed_for(root: Path, name: str) -> bool:
    return paths.exposed_marker_path(root, name).exists()
