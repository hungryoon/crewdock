from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import ManifestError

REQUIRED = ["type", "image", "run_command", "data_mount", "dashboard"]


@dataclass
class Manifest:
    type: str
    image: str
    run_command: list[str]
    data_mount: str
    layers_mount: str | None
    network_mode: str
    dashboard_port: int
    dashboard_host: str
    dashboard_path: str
    dashboard_port_env: str | None
    setup_command: list[str]
    setup_interactive: bool
    static_env: dict[str, str]
    passthrough_env: list[str]
    bot_token_env: str
    bot_token_required: bool
    llm_inherit_from_shared: bool
    mem_limit: str
    cpus: float
    shm_size: str
    seed_config: str | None
    raw: dict = field(repr=False)


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ManifestError(f"manifest must be a mapping: {path}")
    for key in REQUIRED:
        if key not in data:
            raise ManifestError(f"manifest missing required field '{key}': {path}")

    dash = data["dashboard"]
    creds = data.get("credentials", {})
    bot = creds.get("bot_token", {})
    llm = creds.get("llm", {})
    res = data.get("resources", {})
    setup = data.get("setup", {})

    return Manifest(
        type=data["type"],
        image=data["image"],
        run_command=list(data["run_command"]),
        data_mount=data["data_mount"],
        layers_mount=data.get("layers_mount"),
        network_mode=data.get("network_mode", "bridge"),
        dashboard_port=int(dash["container_port"]),
        dashboard_host=dash.get("host", "127.0.0.1"),
        dashboard_path=dash.get("path", "/"),
        dashboard_port_env=dash.get("port_env"),
        setup_command=list(setup.get("command", [])),
        setup_interactive=bool(setup.get("interactive", False)),
        static_env={k: str(v) for k, v in data.get("env", {}).items()},
        passthrough_env=list(data.get("passthrough_env", [])),
        bot_token_env=bot.get("env", ""),
        bot_token_required=bool(bot.get("required", False)),
        llm_inherit_from_shared=bool(llm.get("inherit_from_shared", True)),
        mem_limit=res.get("mem_limit", "4g"),
        cpus=res.get("cpus", 2),
        shm_size=res.get("shm_size", "1g"),
        seed_config=data.get("seed_config"),
        raw=data,
    )
