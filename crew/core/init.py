import secrets
from pathlib import Path

from .creds import parse_env_file
from .errors import CrewError
from . import paths


def init(root: Path, project: str, https_port: int = 443,
         router_port: int = 9400, auth_port: int = 9401,
         local_port: int = 9402) -> None:
    paths.validate_name(project)
    shared = paths.shared_env_path(root)
    if shared.exists() and parse_env_file(shared).get("CREW_PROJECT"):
        existing = parse_env_file(shared)["CREW_PROJECT"]
        raise CrewError(f"already initialized (project '{existing}')")

    data = paths.data_dir(root)
    for sub in ("instances", "layers", "credentials"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    data.chmod(0o700)
    (data / "credentials").chmod(0o700)

    cookie = secrets.token_urlsafe(32)
    shared.write_text(
        f"CREW_PROJECT={project}\n"
        f"CREW_GATEWAY_HTTPS_PORT={https_port}\n"
        f"CREW_ROUTER_PORT={router_port}\n"
        f"CREW_AUTH_PORT={auth_port}\n"
        f"CREW_GATEWAY_LOCAL_PORT={local_port}\n"
        f"CREW_OAUTH_COOKIE_SECRET={cookie}\n"
        "CREW_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com\n"
        "CREW_GOOGLE_CLIENT_SECRET=your-client-secret\n"
    )
    shared.chmod(0o600)
