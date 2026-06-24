import json
from dataclasses import dataclass
from pathlib import Path

from crew.core import paths
from crew.core.creds import parse_env_file


def instance_model(root: Path, instance_id: str) -> dict:
    """{'provider': <active LLM provider or ''>, 'connected': bool} from the
    instance's data/auth.json (host-readable via the ro mount). `connected` means
    the active provider has a credential in the pool. {'','False'} if absent.
    Takes the instance_id (dir name)."""
    path = paths.instance_dir(root, instance_id) / "data" / "auth.json"
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"provider": "", "connected": False}
    provider = d.get("active_provider") or ""
    pool = d.get("credential_pool") or []
    return {"provider": provider, "connected": bool(provider) and provider in pool}


@dataclass
class Published:
    name: str          # base name (display, proxy /i/<name>/, authorize)
    instance_id: str   # dir/container suffix (for broker exec)
    port: int
    allowed_emails: list[str]


def _emails(root: Path, instance_id: str) -> list[str]:
    env = parse_env_file(paths.instance_env_path(root, instance_id))
    return [e.strip() for e in env.get("CREW_ALLOWED_EMAILS", "").split(",")
            if e.strip()]


def published_instances(root: Path) -> list[Published]:
    out = []
    for iid in paths.list_instance_names(root):
        port = paths.read_port(root, iid)
        if not port:
            continue
        out.append(Published(name=paths.instance_base_name(root, iid),
                             instance_id=iid, port=port,
                             allowed_emails=_emails(root, iid)))
    return out


def union_emails(root: Path) -> list[str]:
    seen: list[str] = []
    for p in published_instances(root):
        for e in p.allowed_emails:
            if e not in seen:
                seen.append(e)
    return seen


def instance_emails(root: Path, instance_id: str) -> list[str]:
    """Allowed emails for one instance (its CREW_ALLOWED_EMAILS)."""
    return _emails(root, instance_id)


def set_instance_emails(root: Path, instance_id: str,
                        emails: list[str]) -> list[str]:
    """Rewrite CREW_ALLOWED_EMAILS in the instance's instance.env, preserving
    every other key (mirrors core.gateway.set_https_port). Strips blanks and
    dedupes (order-preserving). Returns the list as stored."""
    clean: list[str] = []
    for e in emails:
        e = e.strip()
        if e and e not in clean:
            clean.append(e)
    p = paths.instance_env_path(root, instance_id)
    lines = p.read_text().splitlines() if p.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.startswith("CREW_ALLOWED_EMAILS="):
            out.append("CREW_ALLOWED_EMAILS=" + ",".join(clean))
            found = True
        else:
            out.append(ln)
    if not found:
        out.append("CREW_ALLOWED_EMAILS=" + ",".join(clean))
    paths.atomic_write_text(p, "\n".join(out) + "\n")
    return clean


def write_union_emails(root: Path) -> None:
    """Write the cross-instance email union to data/_gateway/emails.txt (the file
    oauth2-proxy watches). No-op when the gateway dir is absent (gateway down)."""
    gdir = paths.gateway_dir(root)
    if gdir.exists():
        (gdir / "emails.txt").write_text("\n".join(union_emails(root)) + "\n")
