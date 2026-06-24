import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .manifest import Manifest
from .paths import project_name
from .tz import DEFAULT_TIMEZONE

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def render_compose(
    manifest: Manifest,
    name: str,
    port: int,
    layers: list[str] | None = None,
    credential_keys: list[str] | None = None,
    image: str | None = None,
    timezone: str | None = None,
    project: str = "crew",
) -> str:
    """Render docker-compose.yml text. `port` is recorded by the caller into
    instance.env as CREW_PORT; the compose file references it via ${CREW_PORT}.
    `layers` are mounted read-only under manifest.layers_mount.

    NOTE: `name` here is the instance_id (the hashed dir name, e.g. `ted-9b8c7d`);
    callers pass the full instance_id so container_name = `<project>-<name>-<hex>`."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    template = env.get_template("compose.yaml.j2")
    # In host networking the runtime listens on the allocated host port
    # (${CREW_PORT}); in bridge networking it listens on the in-container port
    # which Docker then maps to ${CREW_PORT} on the host.
    if manifest.network_mode == "host":
        dashboard_port_value = "${CREW_PORT}"
    else:
        dashboard_port_value = str(manifest.dashboard_port)
    passthrough = list(manifest.passthrough_env)
    for key in (credential_keys or []):
        if key not in passthrough:
            passthrough.append(key)
    return template.render(
        image=image or manifest.image,
        timezone=timezone or DEFAULT_TIMEZONE,
        container_name=project_name(project, name),
        data_mount=manifest.data_mount,
        layers_mount=manifest.layers_mount or "/opt/shared",
        layers=layers or [],
        network_mode=manifest.network_mode,
        dashboard_host=manifest.dashboard_host,
        dashboard_port=manifest.dashboard_port,
        dashboard_port_env=manifest.dashboard_port_env,
        dashboard_port_value=dashboard_port_value,
        static_env=manifest.static_env,
        passthrough_env=passthrough,
        shm_size=manifest.shm_size,
        mem_limit=manifest.mem_limit,
        cpus=manifest.cpus,
        run_command_json=json.dumps(manifest.run_command),
    )
