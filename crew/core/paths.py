import json
import re
from pathlib import Path

from filelock import FileLock

from .creds import parse_env_file
from .errors import InvalidNameError

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,29}$")


def validate_name(name: str) -> None:
    if name.startswith("_"):
        raise InvalidNameError(f"name may not start with '_': {name!r}")
    if not NAME_RE.match(name):
        raise InvalidNameError(
            f"invalid name {name!r}: must match ^[a-z][a-z0-9-]{{0,29}}$"
        )


def instances_dir(root: Path) -> Path:
    return root / "instances"


def instance_dir(root: Path, name: str) -> Path:
    return instances_dir(root) / name


def project_name(name: str) -> str:
    return f"crew-{name}"


def shared_env_path(root: Path) -> Path:
    return instances_dir(root) / "_shared.env"


def gateway_dir(root: Path) -> Path:
    return instances_dir(root) / "_gateway"


def exposed_marker_path(root: Path, name: str) -> Path:
    return instance_dir(root, name) / "exposed"


def instance_env_path(root: Path, name: str) -> Path:
    return instance_dir(root, name) / "instance.env"


def compose_path(root: Path, name: str) -> Path:
    return instance_dir(root, name) / "docker-compose.yml"


def lock(root: Path) -> FileLock:
    """Host-wide lock that serializes create (TOCTOU port safety)."""
    return FileLock(str(instances_dir(root) / ".lock"))


def list_instance_names(root: Path) -> list[str]:
    d = instances_dir(root)
    if not d.exists():
        return []
    return sorted(
        p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith("_")
    )


def read_meta(root: Path, name: str) -> dict:
    path = instance_dir(root, name) / "meta.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_meta(root: Path, name: str, meta: dict) -> None:
    path = instance_dir(root, name) / "meta.json"
    path.write_text(json.dumps(meta, indent=2))


def read_port(root: Path, name: str) -> int | None:
    env = parse_env_file(instance_env_path(root, name))
    val = env.get("CREW_PORT")
    return int(val) if val else None


def layers_dir(root: Path) -> Path:
    return root / "layers"


def list_layers(root: Path) -> list[str]:
    d = layers_dir(root)
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def credentials_dir(root: Path) -> Path:
    return root / "credentials"


def credential_path(root: Path, name: str) -> Path:
    return credentials_dir(root) / f"{name}.env"
