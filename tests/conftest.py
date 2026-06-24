from pathlib import Path

import pytest


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A temp project root, initialized as deployment 'test'."""
    (tmp_path / "data" / "instances").mkdir(parents=True)
    (tmp_path / "data" / "_shared.env").write_text("CREW_PROJECT=test\n")
    return tmp_path


SAMPLE_MANIFEST = """\
type: hermes
image: nousresearch/hermes-agent:latest
run_command: ["gateway", "run"]
data_mount: /opt/data
layers_mount: /opt/shared
dashboard:
  container_port: 9119
  host: 127.0.0.1
  path: /
env:
  HERMES_DASHBOARD: "1"
  HERMES_DASHBOARD_HOST: "127.0.0.1"
  HERMES_DASHBOARD_PORT: "9119"
passthrough_env:
  - HERMES_UID
  - HERMES_GID
  - HERMES_DASHBOARD_SESSION_TOKEN
host_user_env:
  uid: HERMES_UID
  gid: HERMES_GID
credentials:
  llm:
    inherit_from_shared: true
resources:
  mem_limit: 4g
  cpus: 2
  shm_size: 1g
seed_config: seed/config.yaml
"""


@pytest.fixture
def manifest_file(tmp_path: Path) -> Path:
    path = tmp_path / "hermes.yaml"
    path.write_text(SAMPLE_MANIFEST)
    return path
