import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .creds import parse_env_file
from .errors import ExposeError
from . import paths

OAUTH2_IMAGE = "quay.io/oauth2-proxy/oauth2-proxy:v7.6.0"


@dataclass
class ExposeConfig:
    client_id: str
    client_secret: str
    cookie_secret: str
    allowed_emails: list[str]


_REQUIRED_SHARED = {
    "CREW_GOOGLE_CLIENT_ID": "client_id",
    "CREW_GOOGLE_CLIENT_SECRET": "client_secret",
    "CREW_OAUTH_COOKIE_SECRET": "cookie_secret",
}


def load_shared_oauth(root: Path) -> ExposeConfig:
    shared = parse_env_file(paths.shared_env_path(root))
    missing = [k for k in _REQUIRED_SHARED if not shared.get(k)]
    if missing:
        raise ExposeError(
            "missing Google OAuth config in data/_shared.env: "
            + ", ".join(missing)
            + "\nadd CREW_GOOGLE_CLIENT_ID, CREW_GOOGLE_CLIENT_SECRET, and "
              "CREW_OAUTH_COOKIE_SECRET."
        )
    return ExposeConfig(
        client_id=shared["CREW_GOOGLE_CLIENT_ID"],
        client_secret=shared["CREW_GOOGLE_CLIENT_SECRET"],
        cookie_secret=shared["CREW_OAUTH_COOKIE_SECRET"],
        allowed_emails=[],
    )



TAILSCALE_APP_BIN = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def tailscale_bin() -> str:
    """Path to the tailscale CLI. The macOS GUI app keeps it inside the bundle
    and never puts it on PATH, so fall back to the bundle path. It must be run
    by that real path — a symlink breaks the app's bundle-identifier lookup."""
    return shutil.which("tailscale") or (
        TAILSCALE_APP_BIN if os.path.exists(TAILSCALE_APP_BIN) else "tailscale")


def serve_argv(https_port: int, authport: int) -> list[str]:
    return [tailscale_bin(), "serve", "--bg", f"--https={https_port}",
            f"http://127.0.0.1:{authport}"]


def serve_off_argv(https_port: int) -> list[str]:
    return [tailscale_bin(), "serve", f"--https={https_port}", "off"]


def _run_capture(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, check=True, text=True,
                              capture_output=True).stdout
    except FileNotFoundError as exc:
        hint = (f" (the macOS app keeps it at {TAILSCALE_APP_BIN})"
                if sys.platform == "darwin" and argv[0] == "tailscale" else "")
        raise ExposeError(
            f"{argv[0]} not found — is it installed?{hint}") from exc
    except subprocess.CalledProcessError as exc:
        raise ExposeError(
            f"{' '.join(argv)} failed (exit {exc.returncode})") from exc


def tailnet_dns_name(run_capture=_run_capture) -> str:
    data = json.loads(run_capture([tailscale_bin(), "status", "--json"]))
    return data["Self"]["DNSName"].rstrip(".")


def check_tailscale_up(run_capture=_run_capture) -> None:
    data = json.loads(run_capture([tailscale_bin(), "status", "--json"]))
    if data.get("BackendState") != "Running":
        raise ExposeError(
            "tailscale is not connected — run `tailscale up` first "
            "(and enable HTTPS for your tailnet)."
        )


def _run(argv: list[str]) -> None:
    try:
        subprocess.run(argv, check=True)
    except FileNotFoundError as exc:
        raise ExposeError(f"{argv[0]} not found — is it installed?") from exc
    except subprocess.CalledProcessError as exc:
        raise ExposeError(
            f"{' '.join(argv)} failed (exit {exc.returncode})") from exc


def _run_quiet(argv: list[str]) -> None:
    """Best-effort command for teardown; never raises."""
    subprocess.run(argv, check=False, capture_output=True)
