from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
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


def _container_exists(name: str) -> bool:
    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "-q", "-f", f"name=^{name}$"],
            capture_output=True, text=True, check=False)
    except Exception:
        return False
    return bool((out.stdout or "").strip())


def _validate_layers(root: Path, layers: list[str]) -> None:
    available = set(paths.list_layers(root))
    for layer in layers:
        if layer not in available:
            raise LayerNotFoundError(
                f"layer {layer!r} not found in data/layers/ — copy it there "
                f"or recreate the instance without it")


def create(root: Path, name: str, type: str, creds: dict,
           layers: list[str] | None = None, credentials: list[str] | None = None,
           tz: str | None = None) -> Instance:
    layers = layers or []
    credentials = credentials or []
    tz = tz or DEFAULT_TIMEZONE
    paths.validate_name(name)
    validate_timezone(tz)
    dep = load_deployment(root)
    manifest = load_manifest(_manifest_path(root, type))
    _validate_layers(root, layers)
    _credentials.validate_credentials(root, credentials)

    with paths.lock(root):
        if paths.resolve_instance_id(root, name) is not None:
            raise InstanceExistsError(f"instance already exists: {name}")
        iid = paths.new_instance_id(name)
        inst_dir = paths.instance_dir(root, iid)
        if _container_exists(dep.instance_project(iid)):
            raise CrewError(
                f"container {dep.instance_project(iid)} already exists — "
                f"project name '{dep.project}' may be used by another deployment")
        port = find_free_port(reserved=_reserved_ports(root))
        try:
            (inst_dir / "data").mkdir(parents=True)
            inst_dir.chmod(0o700)
            if manifest.seed_config:
                tmpl = paths.seed_config_path(root)
                if tmpl.exists():
                    shutil.copy(tmpl, inst_dir / "data" / "config.yaml")
            _write_instance_env(root, iid, port, creds,
                                host_user_env=manifest.host_user_env)
            cred_keys = _credentials.credential_keys(root, credentials)
            paths.compose_path(root, iid).write_text(
                render_compose(manifest, iid, port, layers=layers,
                               credential_keys=cred_keys, image=manifest.image,
                               timezone=tz, project=dep.project)
            )
            paths.write_meta(root, iid, {
                "name": name, "type": type, "port": port, "image": manifest.image,
                "layers": layers, "credentials": credentials,
                "timezone": tz,
                "created_at": _stamp(),
            })
            run_compose(
                dep.instance_project(iid),
                paths.compose_path(root, iid),
                _env_files(root, iid),
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


def _resolve(root: Path, name: str) -> str:
    """Resolve a user-facing identifier to an instance_id (dir name), raising
    InstanceNotFoundError if absent."""
    iid = paths.resolve_instance_id(root, name)
    if iid is None:
        raise InstanceNotFoundError(f"no such instance: {name}")
    return iid


def remove(root: Path, name: str, purge: bool = False) -> None:
    iid = _resolve(root, name)
    dep = load_deployment(root)
    run_compose(
        dep.instance_project(iid),
        paths.compose_path(root, iid),
        _env_files(root, iid),
        ["down"],
    )
    if purge:
        _purge_dir(paths.instance_dir(root, iid))
    # Keep the gateway SSO allowlist in sync with the surviving instances'
    # whitelists (no-op when the gateway is down — emails.txt won't exist).
    from crew.core import gateway
    gateway.regenerate_union_emails(root)


def _on_rm_error(func, path, _exc):
    """rmtree error handler: agents create dirs without the write bit, which
    blocks unlinking their contents even for the owner. Restore write/exec on
    the entry and its parent, then retry — re-raises if genuinely un-permitted
    (e.g. a root-owned file), which routes _purge_dir to the container fallback.

    The third arg is the exception instance on Python >=3.12 (`onexc`) and an
    exc_info tuple on <3.12 (`onerror`); we ignore it, so the same handler works
    for both."""
    for target in (os.path.dirname(path), path):
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
    func(path)


# shutil.rmtree renamed `onerror` -> `onexc` in 3.12 (the handler's 3rd arg also
# changed from an exc_info tuple to the exception). Pick the right keyword so
# purge works on every supported Python (>=3.11), not just our 3.14 dev box.
_RMTREE_HANDLER_KW = "onexc" if sys.version_info >= (3, 12) else "onerror"


def _try_rmtree(path: Path) -> bool:
    """Remove `path`, repairing unwritable dirs as it goes. Returns True if the
    tree is gone, False if residue the host can't touch remains."""
    try:
        shutil.rmtree(path, **{_RMTREE_HANDLER_KW: _on_rm_error})
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
    iid = _resolve(root, name)
    dep = load_deployment(root)
    meta = paths.read_meta(root, iid)
    port = paths.read_port(root, iid) or 0
    return Instance(
        name=paths.instance_base_name(root, iid),
        type=meta.get("type", "unknown"),
        port=port,
        image=meta.get("image", "unknown"),
        previous_image=meta.get("previous_image", ""),
        timezone=meta.get("timezone", DEFAULT_TIMEZONE),
        state=_compose_state(root, iid, dep.project),
        created_at=meta.get("created_at", ""),
    )


def list(root: Path) -> list[Instance]:
    # A single corrupt instance (e.g. unparseable meta.json) must not abort the
    # whole list — skip it rather than blowing up `crew list` for everything.
    # Build each Instance directly from its instance_id (dir name) to avoid a
    # base-name -> id round-trip through status().
    dep = load_deployment(root)
    out = []
    for iid in paths.list_instance_names(root):
        try:
            meta = paths.read_meta(root, iid)
            out.append(Instance(
                name=paths.instance_base_name(root, iid),
                type=meta.get("type", "unknown"),
                port=paths.read_port(root, iid) or 0,
                image=meta.get("image", "unknown"),
                previous_image=meta.get("previous_image", ""),
                timezone=meta.get("timezone", DEFAULT_TIMEZONE),
                state=_compose_state(root, iid, dep.project),
                created_at=meta.get("created_at", ""),
            ))
        except CrewError:
            continue
    return out


_LIFECYCLE = {"start", "stop", "restart"}


def lifecycle(root: Path, name: str, action: str) -> None:
    iid = _resolve(root, name)
    dep = load_deployment(root)
    if action not in _LIFECYCLE:
        raise ValueError(f"unknown lifecycle action: {action}")
    run_compose(
        dep.instance_project(iid),
        paths.compose_path(root, iid),
        _env_files(root, iid),
        [action],
    )


def logs(root: Path, name: str, follow: bool = False) -> None:
    """Stream logs by exec-ing docker compose directly (inherits stdio)."""
    iid = _resolve(root, name)
    dep = load_deployment(root)
    args = ["logs"] + (["-f"] if follow else [])
    subprocess.run(
        compose_argv(dep.instance_project(iid), paths.compose_path(root, iid),
                     _env_files(root, iid), args),
        check=False,
    )


def shell_argv(root: Path, name: str) -> list[str]:
    iid = _resolve(root, name)
    dep = load_deployment(root)
    return compose_argv(
        dep.instance_project(iid),
        paths.compose_path(root, iid),
        _env_files(root, iid),
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
    iid = _resolve(root, name)
    dep = load_deployment(root)
    _exclusive = [f for f, v in (("--image", image is not None),
                                 ("--rollback", rollback),
                                 ("--to-default", to_default)) if v]
    if len(_exclusive) > 1:
        raise CrewError(
            "choose only one of --image / --rollback / --to-default")
    _ensure_session_token(root, iid)
    if backup:
        src = paths.instance_dir(root, iid) / "data"
        dst = paths.instance_dir(root, iid) / f"data.bak-{_stamp()}"
        shutil.copytree(src, dst)
    meta = paths.read_meta(root, iid)
    # Every bring-up path below (bare re-render, --image/--rollback/--to-default
    # repins) re-mounts meta["layers"]. If a referenced layer was removed from
    # data/layers/, Docker would silently auto-create an empty source dir for the
    # bind mount and the agent would lose that knowledge — fail loudly instead.
    _validate_layers(root, meta.get("layers", []))
    manifest = load_manifest(_manifest_path(root, meta.get("type", "")))
    current = meta.get("image", manifest.image)
    if tz is not None:
        validate_timezone(tz)
        meta["timezone"] = tz
        paths.write_meta(root, iid, meta)
    project = dep.instance_project(iid)
    compose_file = paths.compose_path(root, iid)
    env_files = _env_files(root, iid)

    if rollback:
        prev = meta.get("previous_image")
        if not prev:
            raise CrewError("no previous image to roll back to")
        _repin(root, iid, meta, manifest, target=prev, new_previous=current,
               project=dep.project)
        return

    if to_default:
        _repin(root, iid, meta, manifest,
               target=manifest.image, new_previous=current, project=dep.project)
        return

    if image is None:
        _render_instance(root, iid, meta, manifest, current, dep.project)
        run_compose(project, compose_file, env_files, ["pull"])
        run_compose(project, compose_file, env_files, ["up", "-d"])
        return

    _repin(root, iid, meta, manifest, target=image, new_previous=current,
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
