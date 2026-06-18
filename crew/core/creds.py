from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE .env file. Ignores comments, blanks, malformed lines."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def merge_env(
    defaults: dict[str, str],
    shared: dict[str, str],
    instance: dict[str, str],
) -> dict[str, str]:
    """Merge with precedence: instance > shared > defaults. For inspection/validation."""
    merged = dict(defaults)
    merged.update(shared)
    merged.update(instance)
    return merged
