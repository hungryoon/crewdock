from dataclasses import dataclass
from pathlib import Path

from crew.core import paths
from crew.core.creds import parse_env_file


@dataclass
class Published:
    name: str
    port: int
    allowed_emails: list[str]


def _emails(root: Path, name: str) -> list[str]:
    env = parse_env_file(paths.instance_env_path(root, name))
    return [e.strip() for e in env.get("CREW_ALLOWED_EMAILS", "").split(",")
            if e.strip()]


def published_instances(root: Path) -> list[Published]:
    out = []
    for name in paths.list_instance_names(root):
        if not paths.exposed_marker_path(root, name).exists():
            continue
        port = paths.read_port(root, name)
        if not port:
            continue
        out.append(Published(name=name, port=port,
                             allowed_emails=_emails(root, name)))
    return out


def union_emails(root: Path) -> list[str]:
    seen: list[str] = []
    for p in published_instances(root):
        for e in p.allowed_emails:
            if e not in seen:
                seen.append(e)
    return seen
