import json
import os
import re
import tempfile
from pathlib import Path

from filelock import FileLock

from .creds import parse_env_file
from .errors import CrewError, InvalidNameError

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
_HASH_RE = re.compile(r"-[0-9a-f]{6}$")


def new_instance_id(name: str) -> str:
    from . import ids
    return f"{name}-{ids.token()}"


def resolve_instance_id(root: Path, name: str) -> str | None:
    """Resolve a user identifier to an instance_id (dir name): an exact dir name
    (full id) wins; else the single dir whose meta `name` matches. Raises
    CrewError if ambiguous (>1 base-name match). None if absent."""
    idir = instances_dir(root)
    if not idir.exists():
        return None
    if (idir / name).is_dir():
        return name
    matches = [d.name for d in idir.iterdir()
               if d.is_dir() and not d.name.startswith("_")
               and read_meta(root, d.name).get("name") == name]
    if len(matches) > 1:
        raise CrewError(
            f"ambiguous instance {name!r} — multiple match "
            f"({', '.join(sorted(matches))}); use the full id")
    return matches[0] if matches else None


def instance_base_name(root: Path, instance_id: str) -> str:
    m = read_meta(root, instance_id)
    return m.get("name") or _HASH_RE.sub("", instance_id)


def validate_name(name: str) -> None:
    if name.startswith("_"):
        raise InvalidNameError(f"name may not start with '_': {name!r}")
    if not NAME_RE.match(name):
        raise InvalidNameError(
            f"invalid name {name!r}: must match ^[a-z][a-z0-9-]{{0,29}}$"
        )


def find_root(start: Path) -> Path:
    """Nearest ancestor of `start` (inclusive) that is an initialized crewdock
    deployment (has data/_shared.env). Raises CrewError if none."""
    cur = start.resolve()
    for d in (cur, *cur.parents):
        if (d / "data" / "_shared.env").is_file():
            return d
    raise CrewError(
        "no crewdock deployment here — run `crew init <project>` in your "
        "deployment directory, or cd into one")


def data_dir(root: Path) -> Path:
    return root / "data"


def instances_dir(root: Path) -> Path:
    return data_dir(root) / "instances"


def instance_dir(root: Path, name: str) -> Path:
    return instances_dir(root) / name


def project_name(project: str, name: str) -> str:
    return f"{project}-{name}"


def shared_env_path(root: Path) -> Path:
    return data_dir(root) / "_shared.env"


def gateway_dir(root: Path) -> Path:
    return data_dir(root) / "_gateway"


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
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CrewError(
            f"corrupt meta.json for instance (could not parse {path}): {exc}"
        ) from exc


def atomic_write_text(path: Path, text: str) -> None:
    """Write text durably: write to a temp file in the same dir, then os.replace.
    A crash mid-write leaves the original intact rather than a truncated file."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_meta(root: Path, name: str, meta: dict) -> None:
    path = instance_dir(root, name) / "meta.json"
    atomic_write_text(path, json.dumps(meta, indent=2))


def read_port(root: Path, name: str) -> int | None:
    env = parse_env_file(instance_env_path(root, name))
    val = env.get("CREW_PORT")
    return int(val) if val else None


def layers_dir(root: Path) -> Path:
    return data_dir(root) / "layers"


def list_layers(root: Path) -> list[str]:
    d = layers_dir(root)
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def credentials_dir(root: Path) -> Path:
    return data_dir(root) / "credentials"


def credential_path(root: Path, name: str) -> Path:
    return credentials_dir(root) / f"{name}.env"


def seed_config_path(root: Path) -> Path:
    return root / "seed" / "config.yaml"
