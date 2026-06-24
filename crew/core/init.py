import secrets
import shutil
from pathlib import Path

from .creds import parse_env_file
from .errors import CrewError
from . import paths


def _repo_root() -> str:
    # crewdock checkout root: crew/core/init.py -> repo root is 3 parents up.
    return str(Path(__file__).resolve().parent.parent.parent)


def init(root: Path, project: str, https_port: int = 443,
         router_port: int = 9400, auth_port: int = 9401,
         local_port: int = 9402) -> None:
    paths.validate_name(project)
    shared = paths.shared_env_path(root)
    if shared.exists() and parse_env_file(shared).get("CREW_PROJECT"):
        existing = parse_env_file(shared)["CREW_PROJECT"]
        raise CrewError(f"already initialized (project '{existing}')")

    for sub in ("instances", "agents", "layers", "credentials"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    (root / "credentials").chmod(0o700)

    repo = Path(_repo_root())
    for manifest in (repo / "agents").glob("*.yaml"):
        shutil.copy(manifest, root / "agents" / manifest.name)
    src_tmpl = repo / "instances" / "_template"
    dst_tmpl = root / "instances" / "_template"
    if src_tmpl.exists() and not dst_tmpl.exists():
        shutil.copytree(src_tmpl, dst_tmpl)

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
