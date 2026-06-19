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
