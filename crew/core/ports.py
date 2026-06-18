import socket

from .errors import NoFreePortError

BASE_PORT = 9120
MAX_PORT = 9199


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_free_port(
    reserved: set[int],
    base: int = BASE_PORT,
    max_port: int = MAX_PORT,
) -> int:
    for port in range(base, max_port + 1):
        if port in reserved:
            continue
        if _is_free(port):
            return port
    raise NoFreePortError(f"no free port in range {base}-{max_port}")
