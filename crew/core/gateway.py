from pathlib import Path

ROUTER_IMAGE = "crewdock-gateway-router:local"
ROUTER_CONTAINER = "crew-gateway-router"
GATEWAY_AUTH_CONTAINER = "crew-gateway-auth"
ROUTER_PORT = 9400
GATEWAY_AUTH_PORT = 9401
GATEWAY_HTTPS_PORT = 443


def render_gateway_oauth2_env(cfg, authport: int, routerport: int,
                              redirect: str) -> str:
    lines = [
        "OAUTH2_PROXY_PROVIDER=google",
        f"OAUTH2_PROXY_CLIENT_ID={cfg.client_id}",
        f"OAUTH2_PROXY_CLIENT_SECRET={cfg.client_secret}",
        f"OAUTH2_PROXY_COOKIE_SECRET={cfg.cookie_secret}",
        f"OAUTH2_PROXY_REDIRECT_URL={redirect}",
        f"OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:{routerport}/",
        f"OAUTH2_PROXY_HTTP_ADDRESS=127.0.0.1:{authport}",
        "OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/oauth2-proxy/emails.txt",
        "OAUTH2_PROXY_PASS_USER_HEADERS=true",
        "OAUTH2_PROXY_REVERSE_PROXY=true",
        "OAUTH2_PROXY_PROXY_WEBSOCKETS=true",
        "OAUTH2_PROXY_COOKIE_SECURE=true",
    ]
    return "\n".join(lines) + "\n"


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
