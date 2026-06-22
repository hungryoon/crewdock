import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .compose import render_compose
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
from . import paths
from . import expose as _expose
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
    # Pre-seed the expose whitelist key (commented out, so inactive) so enabling
    # `crew expose` is just "uncomment and fill in" — no need to recall the key.
    lines.append("")
    lines.append("# Uncomment + set Google accounts (comma-separated) to allow `crew expose`:")
    lines.append("# CREW_ALLOWED_EMAILS=you@example.com")
    paths.instance_env_path(root, name).write_text("\n".join(lines) + "\n")


def _validate_layers(root: Path, layers: list[str]) -> None:
    available = set(paths.list_layers(root))
    for layer in layers:
        if layer not in available:
            raise LayerNotFoundError(f"no such layer in pool: {layer}")


def create(root: Path, name: str, type: str, creds: dict,
           layers: list[str] | None = None, credentials: list[str] | None = None) -> Instance:
    layers = layers or []
    credentials = credentials or []
    paths.validate_name(name)
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
            if manifest.seed_config:
                tmpl = root / "instances" / "_template" / "config.yaml"
                if tmpl.exists():
                    shutil.copy(tmpl, inst_dir / "data" / "config.yaml")
            _write_instance_env(root, name, port, creds,
                                host_user_env=manifest.host_user_env)
            cred_keys = _credentials.credential_keys(root, credentials)
            paths.compose_path(root, name).write_text(
                render_compose(manifest, name, port, layers=layers,
                               credential_keys=cred_keys, image=manifest.image)
            )
            paths.write_meta(root, name, {
                "type": type, "port": port, "image": manifest.image,
                "layers": layers, "credentials": credentials,
                "created_at": _stamp(),
            })
            run_compose(
                paths.project_name(name),
                paths.compose_path(root, name),
                _env_files(root, name),
                ["up", "-d"],
            )
        except Exception:
            shutil.rmtree(inst_dir, ignore_errors=True)
            raise

    return Instance(name=name, type=type, port=port, image=manifest.image,
                    state="running")


def _require_exists(root: Path, name: str) -> None:
    if not paths.instance_dir(root, name).exists():
        raise InstanceNotFoundError(f"no such instance: {name}")


def remove(root: Path, name: str, purge: bool = False) -> None:
    _require_exists(root, name)
    if _expose.is_exposed_for(root, name):
        _expose.unexpose(root, name)
    run_compose(
        paths.project_name(name),
        paths.compose_path(root, name),
        _env_files(root, name),
        ["down"],
    )
    if purge:
        _purge_dir(paths.instance_dir(root, name))


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


def _compose_state(root: Path, name: str) -> str:
    """Runtime state from `docker compose ps`. running | stopped | absent."""
    try:
        result = run_compose(
            paths.project_name(name),
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
    meta = paths.read_meta(root, name)
    port = paths.read_port(root, name) or 0
    return Instance(
        name=name,
        type=meta.get("type", "unknown"),
        port=port,
        image=meta.get("image", "unknown"),
        state=_compose_state(root, name),
        created_at=meta.get("created_at", ""),
    )


def list(root: Path) -> list[Instance]:
    return [status(root, name) for name in paths.list_instance_names(root)]


_LIFECYCLE = {"start", "stop", "restart"}


def lifecycle(root: Path, name: str, action: str) -> None:
    _require_exists(root, name)
    if action not in _LIFECYCLE:
        raise ValueError(f"unknown lifecycle action: {action}")
    run_compose(
        paths.project_name(name),
        paths.compose_path(root, name),
        _env_files(root, name),
        [action],
    )


def logs(root: Path, name: str, follow: bool = False) -> None:
    """Stream logs by exec-ing docker compose directly (inherits stdio)."""
    _require_exists(root, name)
    args = ["logs"] + (["-f"] if follow else [])
    subprocess.run(
        compose_argv(paths.project_name(name), paths.compose_path(root, name),
                     _env_files(root, name), args),
        check=False,
    )


def setup(root: Path, name: str) -> None:
    """Re-runnable interactive init (OAuth etc.). Overwrites existing creds."""
    _require_exists(root, name)
    meta = paths.read_meta(root, name)
    manifest = load_manifest(_manifest_path(root, meta.get("type", "")))
    subprocess.run(
        compose_argv(paths.project_name(name), paths.compose_path(root, name),
                     _env_files(root, name), ["run", "--rm", "agent"] + manifest.setup_command),
        check=False,
    )


def shell_argv(root: Path, name: str) -> list[str]:
    _require_exists(root, name)
    return compose_argv(
        paths.project_name(name),
        paths.compose_path(root, name),
        _env_files(root, name),
        ["exec", "agent", "sh"],
    )


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def update(root: Path, name: str, backup: bool = False) -> None:
    """Re-render compose (applies layer/manifest changes), pull the pinned image,
    and recreate. Re-reads both env-files so _shared.env changes propagate.
    With backup=True, snapshot data/ first."""
    _require_exists(root, name)
    if backup:
        src = paths.instance_dir(root, name) / "data"
        dst = paths.instance_dir(root, name) / f"data.bak-{_stamp()}"
        shutil.copytree(src, dst)
    meta = paths.read_meta(root, name)
    manifest = load_manifest(_manifest_path(root, meta.get("type", "")))
    port = paths.read_port(root, name) or 0
    cred_keys = _credentials.credential_keys(root, meta.get("credentials", []))
    paths.compose_path(root, name).write_text(
        render_compose(manifest, name, port, layers=meta.get("layers", []),
                       credential_keys=cred_keys)
    )
    project = paths.project_name(name)
    compose_file = paths.compose_path(root, name)
    env_files = _env_files(root, name)
    run_compose(project, compose_file, env_files, ["pull"])
    run_compose(project, compose_file, env_files, ["up", "-d"])
