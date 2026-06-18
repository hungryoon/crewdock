import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .compose import render_compose
from .docker import run_compose, compose_argv
from .errors import InstanceExistsError, InstanceNotFoundError, LayerNotFoundError
from .manifest import load_manifest
from .models import Instance
from .ports import find_free_port
from . import paths


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
    files.append(paths.instance_env_path(root, name))
    return files


def _write_instance_env(root: Path, name: str, port: int, creds: dict) -> None:
    lines = [f"CREW_PORT={port}"]
    for key, value in creds.items():
        lines.append(f"{key}={value}")
    paths.instance_env_path(root, name).write_text("\n".join(lines) + "\n")


def _validate_layers(root: Path, layers: list[str]) -> None:
    available = set(paths.list_layers(root))
    for layer in layers:
        if layer not in available:
            raise LayerNotFoundError(f"no such layer in pool: {layer}")


def create(root: Path, name: str, type: str, creds: dict,
           layers: list[str] | None = None) -> Instance:
    layers = layers or []
    paths.validate_name(name)
    inst_dir = paths.instance_dir(root, name)
    manifest = load_manifest(_manifest_path(root, type))
    _validate_layers(root, layers)

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
            _write_instance_env(root, name, port, creds)
            paths.compose_path(root, name).write_text(
                render_compose(manifest, name, port, layers=layers)
            )
            paths.write_meta(root, name, {
                "type": type, "port": port, "image": manifest.image,
                "layers": layers, "created_at": _stamp(),
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
    run_compose(
        paths.project_name(name),
        paths.compose_path(root, name),
        _env_files(root, name),
        ["down"],
    )
    if purge:
        shutil.rmtree(paths.instance_dir(root, name), ignore_errors=True)


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
    paths.compose_path(root, name).write_text(
        render_compose(manifest, name, port, layers=meta.get("layers", []))
    )
    project = paths.project_name(name)
    compose_file = paths.compose_path(root, name)
    env_files = _env_files(root, name)
    run_compose(project, compose_file, env_files, ["pull"])
    run_compose(project, compose_file, env_files, ["up", "-d"])
