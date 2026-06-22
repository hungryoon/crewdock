from pathlib import Path

from . import paths
from .creds import parse_env_file
from .errors import CredentialNotFoundError


def list_credentials(root: Path) -> list[str]:
    d = paths.credentials_dir(root)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.iterdir()
                  if p.is_file() and p.suffix == ".env")


def validate_credentials(root: Path, names: list[str]) -> None:
    available = set(list_credentials(root))
    for name in names:
        if name not in available:
            raise CredentialNotFoundError(f"no such credential in pool: {name}")


def credential_files(root: Path, names: list[str]) -> list[Path]:
    return [paths.credential_path(root, name) for name in names]


def credential_keys(root: Path, names: list[str]) -> list[str]:
    keys: list[str] = []
    for name in names:
        for key in parse_env_file(paths.credential_path(root, name)):
            if key not in keys:
                keys.append(key)
    return keys
