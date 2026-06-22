from pathlib import Path

ROUTER_IMAGE = "crewdock-gateway-router:local"
ROUTER_CONTAINER = "crew-gateway-router"
GATEWAY_AUTH_CONTAINER = "crew-gateway-auth"
ROUTER_PORT = 9400
GATEWAY_AUTH_PORT = 9401
GATEWAY_HTTPS_PORT = 443


def router_build_argv(repo_root: str) -> list[str]:
    repo_root = str(repo_root)
    return [
        "docker", "build", "-t", ROUTER_IMAGE,
        "-f", f"{repo_root}/crew/gateway/Dockerfile", repo_root,
    ]


def router_run_argv(root_abs: str, router_port: int) -> list[str]:
    root_abs = str(root_abs)
    return [
        "docker", "run", "-d", "--pull", "never", "--name", ROUTER_CONTAINER,
        "--network", "host", "--restart", "unless-stopped",
        "-v", f"{root_abs}/instances:/crew/instances:ro",
        "-e", f"CREW_ROUTER_PORT={router_port}",
        "-e", "CREW_ROOT=/crew",
        ROUTER_IMAGE,
    ]
