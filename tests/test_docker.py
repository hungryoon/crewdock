from pathlib import Path

from crew.core.docker import compose_argv


def test_compose_argv_includes_project_file_and_envfiles():
    argv = compose_argv(
        project="crew-alice",
        compose_file=Path("/x/docker-compose.yml"),
        env_files=[Path("/x/_shared.env"), Path("/x/instance.env")],
        args=["up", "-d"],
    )
    assert argv == [
        "docker", "compose",
        "-p", "crew-alice",
        "-f", "/x/docker-compose.yml",
        "--env-file", "/x/_shared.env",
        "--env-file", "/x/instance.env",
        "up", "-d",
    ]


def test_compose_argv_omits_no_envfiles():
    argv = compose_argv("crew-x", Path("/c.yml"), env_files=[], args=["ps"])
    assert "--env-file" not in argv
    assert argv[-1] == "ps"
