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


def load_expose_config(root: Path) -> ExposeConfig:
    env = parse_env_file(paths.shared_env_path(root))
    missing = [k for k in _REQUIRED_SHARED if not env.get(k)]
    if missing:
        raise ExposeError(
            "missing Google OAuth config in instances/_shared.env: "
            + ", ".join(missing)
            + "\nadd CREW_GOOGLE_CLIENT_ID, CREW_GOOGLE_CLIENT_SECRET, and "
              "CREW_OAUTH_COOKIE_SECRET (optionally CREW_ALLOWED_EMAILS)."
        )
    emails = [
        e.strip()
        for e in env.get("CREW_ALLOWED_EMAILS", "").split(",")
        if e.strip()
    ]
    return ExposeConfig(
        client_id=env["CREW_GOOGLE_CLIENT_ID"],
        client_secret=env["CREW_GOOGLE_CLIENT_SECRET"],
        cookie_secret=env["CREW_OAUTH_COOKIE_SECRET"],
        allowed_emails=emails,
    )


def auth_container_name(name: str) -> str:
    return f"{paths.project_name(name)}-auth"


def render_oauth2_env(cfg: ExposeConfig, authport: int, dashport: int,
                      redirect: str) -> str:
    lines = [
        "OAUTH2_PROXY_PROVIDER=google",
        f"OAUTH2_PROXY_CLIENT_ID={cfg.client_id}",
        f"OAUTH2_PROXY_CLIENT_SECRET={cfg.client_secret}",
        f"OAUTH2_PROXY_COOKIE_SECRET={cfg.cookie_secret}",
        f"OAUTH2_PROXY_REDIRECT_URL={redirect}",
        f"OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:{dashport}/",
        f"OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:{authport}",
        "OAUTH2_PROXY_EMAIL_DOMAINS=*",
        "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/oauth2-proxy/emails.txt",
        "OAUTH2_PROXY_REVERSE_PROXY=true",
        "OAUTH2_PROXY_COOKIE_SECURE=true",
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
