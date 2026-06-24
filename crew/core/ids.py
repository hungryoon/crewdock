import secrets


def token() -> str:
    """Short hex id, docker-short-id style (6 hex chars)."""
    return secrets.token_hex(3)
