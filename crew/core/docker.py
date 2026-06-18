import subprocess
from pathlib import Path

from .errors import CrewError


def compose_argv(
    project: str,
    compose_file: Path,
    env_files: list[Path],
    args: list[str],
) -> list[str]:
    argv = ["docker", "compose", "-p", project, "-f", str(compose_file)]
    for ef in env_files:
        argv += ["--env-file", str(ef)]
    argv += list(args)
    return argv


def run_compose(
    project: str,
    compose_file: Path,
    env_files: list[Path],
    args: list[str],
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a docker compose subcommand. Raises CrewError on failure."""
    argv = compose_argv(project, compose_file, env_files, args)
    try:
        return subprocess.run(argv, check=True, text=True, capture_output=capture)
    except FileNotFoundError as exc:
        raise CrewError("docker not found — is Docker installed and on PATH?") from exc
    except subprocess.CalledProcessError as exc:
        raise CrewError(f"docker compose {' '.join(args)} failed (exit {exc.returncode})") from exc
