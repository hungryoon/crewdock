from dataclasses import dataclass
from pathlib import Path

from .creds import parse_env_file
from .errors import CrewError, NotInitializedError
from . import paths


@dataclass(frozen=True)
class Deployment:
    project: str
    https_port: int
    router_port: int
    auth_port: int

    def router_container(self) -> str: return f"{self.project}-gateway-router"
    def auth_container(self) -> str:   return f"{self.project}-gateway-auth"
    def broker_container(self) -> str: return f"{self.project}-gateway-broker"
    def router_image(self) -> str:     return f"{self.project}-gateway-router:local"
    def broker_image(self) -> str:     return f"{self.project}-gateway-broker:local"

    def instance_project(self, name: str) -> str:
        return f"{self.project}-{name}"


def _port(env: dict, key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise CrewError(f"{key} must be an integer, got {raw!r}") from exc


def load_deployment(root: Path) -> Deployment:
    env = parse_env_file(paths.shared_env_path(root))
    project = env.get("CREW_PROJECT", "").strip()
    if not project:
        raise NotInitializedError(
            "not initialized — run `crew init <project>` first")
    paths.validate_name(project)
    return Deployment(
        project=project,
        https_port=_port(env, "CREW_GATEWAY_HTTPS_PORT", 443),
        router_port=_port(env, "CREW_ROUTER_PORT", 9400),
        auth_port=_port(env, "CREW_AUTH_PORT", 9401),
    )
