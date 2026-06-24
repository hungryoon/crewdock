import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .compose import render_compose
from .deployment import load_deployment
from .docker import run_compose, compose_argv
from .errors import (
    CrewError,
    InstanceExistsError,
    InstanceNotFoundError,
    LayerNotFoundError,
)
from .manifest import load_manifest
from .models import Instance
from .ports import find_free_port
from .tz import DEFAULT_TIMEZONE, validate_timezone
from . import paths
from . import credentials as _credentials


def _manifest_path(root: Path, type: str) -> Path:
    return root / "agents" / f"{type}.yaml"


def _reserved_ports(root: Path) -> set[int]:
    ports = set()
    for name in paths.list_instance_names(root):
        p = paths.read_port(root, name)
        if p:
            ports.add(p)
    return ports


def _env_files(root: Path, name: str) -> list[Path]:
    files = []
    shared = paths.shared_env_path(root)
    if shared.exists():
        files.append(shared)
    creds = paths.read_meta(root, name).get("credentials", [])
    for path in _credentials.credential_files(root, creds):
        if path.exists():
            files.append(path)
    files.append(paths.instance_env_path(root, name))
    return files


def _write_instance_env(root: Path, name: str, port: int, creds: dict,
                        host_user_env: dict | None = None) -> None:
    uid, gid = os.getuid(), os.getgid()
    # CREW_UID/CREW_GID are the canonical host identity. Agent images that start
    # as root and drop privileges read them under their own env names (mapped via
    # the manifest's host_user_env), so the bind-mounted data/ stays host-owned
    # and `rm --purge` never hits root-owned residue.
    lines = [f"CREW_PORT={port}", f"CREW_UID={uid}", f"CREW_GID={gid}"]
    if host_user_env:
        if host_user_env.get("uid"):
            lines.append(f"{host_user_env['uid']}={uid}")
        if host_user_env.get("gid"):
            lines.append(f"{host_user_env['gid']}={gid}")
    for key, value in creds.items():
        lines.append(f"{key}={value}")
    # Stable per-instance dashboard session token. The Hermes dashboard otherwise
    # mints a fresh random token on every (re)start, silently invalidating any
    # already-loaded browser SPA (events feed / chat then 403). Pinning it here
    # keeps the token stable across restarts/updates.
    lines.append(f"HERMES_DASHBOARD_SESSION_TOKEN={_new_session_token()}")
    # Pre-seed the access whitelist key (commented out, so the instance starts
    # closed — invisible and unreachable on the gateway). Uncomment + fill in to
    # grant gateway access; an empty/absent whitelist means no one can reach it.
    lines.append("")
    lines.append("# Uncomment + set Google accounts (comma-separated) to grant gateway access:")
    lines.append("# CREW_ALLOWED_EMAILS=you@example.com")
    paths.instance_env_path(root, name).write_text("\n".join(lines) + "\n")
    paths.instance_env_path(root, name).chmod(0o600)


def _new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _ensure_session_token(root: Path, name: str) -> None:
    """Add a stable HERMES_DASHBOARD_SESSION_TOKEN to an instance that predates
    this feature, so existing instances stop losing dashboard auth on restart.
    No-op when one is already present."""
    from .creds import parse_env_file
    env_path = paths.instance_env_path(root, name)
    if "HERMES_DASHBOARD_SESSION_TOKEN" in parse_env_file(env_path):
        return
    with env_path.open("a") as f:
        f.write(f"HERMES_DASHBOARD_SESSION_TOKEN={_new_session_token()}\n")


def _validate_layers(root: Path, layers: list[str]) -> None:
    available = set(paths.list_layers(root))
    for layer in layers:
        if layer not in available:
            raise LayerNotFoundError(f"no such layer in pool: {layer}")


def create(root: Path, name: str, type: str, creds: dict,
           layers: list[str] | None = None, credentials: list[str] | None = None,
           tz: str | None = None) -> Instance:
    layers = layers or []
    credentials = credentials or []
    tz = tz or DEFAULT_TIMEZONE
    paths.validate_name(name)
    validate_timezone(tz)
    dep = load_deployment(root)
    inst_dir = paths.instance_dir(root, name)
    manifest = load_manifest(_manifest_path(root, type))
    _validate_layers(root, layers)
    _credentials.validate_credentials(root, credentials)

    with paths.lock(root):
        if inst_dir.exists():
            raise InstanceExistsError(f"instance already exists: {name}")
        port = find_free_port(reserved=_reserved_ports(root))
        try:
            (inst_dir / "data").mkdir(parents=True)
            inst_dir.chmod(0o700)
            if manifest.seed_config:
                tmpl = root / "instances" / "_template" / "config.yaml"
                if tmpl.exists():
                    shutil.copy(tmpl, inst_dir / "data" / "config.yaml")
            _write_instance_env(root, name, port, creds,
                                host_user_env=manifest.host_user_env)
            cred_keys = _credentials.credential_keys(root, credentials)
            paths.compose_path(root, name).write_text(
                render_compose(manifest, name, port, layers=layers,
                               credential_keys=cred_keys, image=manifest.image,
                               timezone=tz, project=dep.project)
            )
            paths.write_meta(root, name, {
                "type": type, "port": port, "image": manifest.image,
                "layers": layers, "credentials": credentials,
                "timezone": tz,
                "created_at": _stamp(),
            })
            run_compose(
                dep.instance_project(name),
                paths.compose_path(root, name),
                _env_files(root, name),
                ["up", "-d"],
            )
        except Exception:
            try:
                _purge_dir(inst_dir)
            except Exception:
                pass
            raise

    # New instance's whitelist (if any) joins the gateway SSO allowlist.
    # No-op when the gateway is down (emails.txt won't exist).
    from crew.core import gateway
    gateway.regenerate_union_emails(root)
    return Instance(name=name, type=type, port=port, image=manifest.image,
                    timezone=tz, state="running")


def _require_exists(root: Path, name: str) -> None:
    if not paths.instance_dir(root, name).exists():
        raise InstanceNotFoundError(f"no such instance: {name}")


def remove(root: Path, name: str, purge: bool = False) -> None:
    _require_exists(root, name)
    dep = load_deployment(root)
    run_compose(
        dep.instance_project(name),
        paths.compose_path(root, name),
        _env_files(root, name),
        ["down"],
    )
    if purge:
        _purge_dir(paths.instance_dir(root, name))
    # Keep the gateway SSO allowlist in sync with the surviving instances'
    # whitelists (no-op when the gateway is down — emails.txt won't exist).
    from crew.core import gateway
    gateway.regenerate_union_emails(root)


def _on_rm_error(func, path, exc):
    """rmtree (onexc) handler: agents create dirs without the write bit, which
    blocks unlinking their contents even for the owner. Restore write/exec on
    the entry and its parent, then retry — re-raises if genuinely un-permitted
    (e.g. a root-owned file), which routes _purge_dir to the container fallback."""
    for target in (os.path.dirname(path), path):
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
    func(path)


def _try_rmtree(path: Path) -> bool:
    """Remove `path`, repairing unwritable dirs as it goes. Returns True if the
    tree is gone, False if residue the host can't touch remains."""
    try:
        shutil.rmtree(path, onexc=_on_rm_error)
    except OSError:
        pass
    return not path.exists()


def _root_delete_contents(path: Path) -> None:
    """Last resort for genuinely root-owned residue: clear it from inside a
    throwaway root container mounted on the (absolute) instance dir."""
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{path.resolve()}:/target", "alpine:3",
         "sh", "-c", "rm -rf /target/* /target/.[!.]* /target/..?* 2>/dev/null || true"],
        check=False,
    )


def _purge_dir(path: Path) -> None:
    if _try_rmtree(path):
        return
    # Host couldn't finish (root-owned residue) — clear it as root, then retry.
    _root_delete_contents(path)
    if not _try_rmtree(path):
        raise CrewError(
            f"could not fully purge {path}\n"
            f"remove the leftovers manually with: sudo rm -rf {path}"
        )


def _compose_state(root: Path, name: str, project: str) -> str:
    """Runtime state from `docker compose ps`. running | stopped | absent."""
    try:
        result = run_compose(
            f"{project}-{name}",
            paths.compose_path(root, name),
            _env_files(root, name),
            ["ps", "--status", "running", "-q"],
            capture=True,
        )
    except Exception:
        return "absent"
    return "running" if (result.stdout or "").strip() else "stopped"


def status(root: Path, name: str) -> Instance:
    _require_exists(root, name)
    dep = load_deployment(root)
    meta = paths.read_meta(root, name)
    port = paths.read_port(root, name) or 0
    return Instance(
        name=name,
        type=meta.get("type", "unknown"),
        port=port,
        image=meta.get("image", "unknown"),
        previous_image=meta.get("previous_image", ""),
        timezone=meta.get("timezone", DEFAULT_TIMEZONE),
        state=_compose_state(root, name, dep.project),
        created_at=meta.get("created_at", ""),
    )


def list(root: Path) -> list[Instance]:
    return [status(root, name) for name in paths.list_instance_names(root)]


_LIFECYCLE = {"start", "stop", "restart"}


def lifecycle(root: Path, name: str, action: str) -> None:
    _require_exists(root, name)
    dep = load_deployment(root)
    if action not in _LIFECYCLE:
        raise ValueError(f"unknown lifecycle action: {action}")
    run_compose(
        dep.instance_project(name),
        paths.compose_path(root, name),
        _env_files(root, name),
        [action],
    )


def logs(root: Path, name: str, follow: bool = False) -> None:
    """Stream logs by exec-ing docker compose directly (inherits stdio)."""
    _require_exists(root, name)
    dep = load_deployment(root)
    args = ["logs"] + (["-f"] if follow else [])
    subprocess.run(
        compose_argv(dep.instance_project(name), paths.compose_path(root, name),
                     _env_files(root, name), args),
        check=False,
    )


def shell_argv(root: Path, name: str) -> list[str]:
    _require_exists(root, name)
    dep = load_deployment(root)
    return compose_argv(
        dep.instance_project(name),
        paths.compose_path(root, name),
        _env_files(root, name),
        ["exec", "agent", "sh"],
    )


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _render_instance(root: Path, name: str, meta: dict, manifest, image: str,
                     project: str) -> None:
    """Re-render an instance's compose file using a specific image."""
    port = paths.read_port(root, name) or 0
    cred_keys = _credentials.credential_keys(root, meta.get("credentials", []))
    paths.compose_path(root, name).write_text(
        render_compose(manifest, name, port, layers=meta.get("layers", []),
                       credential_keys=cred_keys, image=image,
                       timezone=meta.get("timezone", DEFAULT_TIMEZONE),
                       project=project)
    )


def update(root: Path, name: str, backup: bool = False,
           image: str | None = None, rollback: bool = False,
           to_default: bool = False, tz: str | None = None) -> None:
    """Re-render compose, pull the instance's image, and recreate.
    Bare (no image) keeps the pin; image=<ref> repins atomically
    (restores meta+compose if pull/up fails). rollback=True swaps
    current/previous. to_default=True repins to the manifest image.
    With backup=True, snapshot data/ first."""
    _require_exists(root, name)
    dep = load_deployment(root)
    _exclusive = [f for f, v in (("--image", image is not None),
                                 ("--rollback", rollback),
                                 ("--to-default", to_default)) if v]
    if len(_exclusive) > 1:
        raise CrewError(
            "choose only one of --image / --rollback / --to-default")
    _ensure_session_token(root, name)
    if backup:
        src = paths.instance_dir(root, name) / "data"
        dst = paths.instance_dir(root, name) / f"data.bak-{_stamp()}"
        shutil.copytree(src, dst)
    meta = paths.read_meta(root, name)
    manifest = load_manifest(_manifest_path(root, meta.get("type", "")))
    current = meta.get("image", manifest.image)
    if tz is not None:
        validate_timezone(tz)
        meta["timezone"] = tz
        paths.write_meta(root, name, meta)
    project = dep.instance_project(name)
    compose_file = paths.compose_path(root, name)
    env_files = _env_files(root, name)

    if rollback:
        prev = meta.get("previous_image")
        if not prev:
            raise CrewError("no previous image to roll back to")
        _repin(root, name, meta, manifest, target=prev, new_previous=current,
               project=dep.project)
        return

    if to_default:
        _repin(root, name, meta, manifest,
               target=manifest.image, new_previous=current, project=dep.project)
        return

    if image is None:
        _render_instance(root, name, meta, manifest, current, dep.project)
        run_compose(project, compose_file, env_files, ["pull"])
        run_compose(project, compose_file, env_files, ["up", "-d"])
        return

    _repin(root, name, meta, manifest, target=image, new_previous=current,
           project=dep.project)


def _repin(root: Path, name: str, meta: dict, manifest, target: str,
           new_previous: str, project: str) -> None:
    """Atomically switch an instance to `target` image. Records
    previous_image=new_previous. Restores meta+compose if pull/up fails."""
    old_meta = dict(meta)
    old_compose = paths.compose_path(root, name).read_text()
    new_meta = dict(meta)
    new_meta["image"] = target
    new_meta["previous_image"] = new_previous
    paths.write_meta(root, name, new_meta)
    _render_instance(root, name, new_meta, manifest, target, project)
    project = paths.project_name(project, name)
    compose_file = paths.compose_path(root, name)
    env_files = _env_files(root, name)
    try:
        run_compose(project, compose_file, env_files, ["pull"])
        run_compose(project, compose_file, env_files, ["up", "-d"])
    except Exception:
        # Restore meta FIRST (intentional: meta is the source of truth;
        # compose is regenerated from meta on the next update).
        paths.write_meta(root, name, old_meta)
        paths.atomic_write_text(paths.compose_path(root, name), old_compose)
        raise
