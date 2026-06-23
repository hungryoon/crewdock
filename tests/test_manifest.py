import pytest

from crew.core.errors import ManifestError
from crew.core.manifest import load_manifest


def test_load_manifest_parses_all_fields(manifest_file):
    m = load_manifest(manifest_file)
    assert m.type == "hermes"
    assert m.image == "nousresearch/hermes-agent:latest"
    assert m.run_command == ["gateway", "run"]
    assert m.data_mount == "/opt/data"
    assert m.layers_mount == "/opt/shared"
    assert m.dashboard_port == 9119
    assert m.dashboard_host == "127.0.0.1"
    assert m.static_env["HERMES_DASHBOARD"] == "1"
    assert m.passthrough_env == ["HERMES_UID", "HERMES_GID", "TELEGRAM_BOT_TOKEN",
                                 "HERMES_DASHBOARD_SESSION_TOKEN"]
    assert m.bot_token_env == "TELEGRAM_BOT_TOKEN"
    assert m.bot_token_required is True
    assert m.mem_limit == "4g"
    assert m.cpus == 2
    assert m.seed_config == "_template/config.yaml"


def test_load_manifest_network_defaults(manifest_file):
    # SAMPLE_MANIFEST omits network_mode and dashboard.port_env -> defaults
    m = load_manifest(manifest_file)
    assert m.network_mode == "bridge"
    assert m.dashboard_port_env is None


HOST_MODE_MANIFEST = """\
type: hermes
image: nousresearch/hermes-agent:latest
run_command: ["gateway", "run"]
data_mount: /opt/data
layers_mount: /opt/shared
network_mode: host
dashboard:
  container_port: 9119
  host: 127.0.0.1
  path: /
  port_env: HERMES_DASHBOARD_PORT
env:
  HERMES_DASHBOARD: "1"
  HERMES_DASHBOARD_HOST: "127.0.0.1"
credentials:
  bot_token:
    required: true
    env: TELEGRAM_BOT_TOKEN
"""


def test_load_manifest_parses_network_host_and_port_env(tmp_path):
    path = tmp_path / "host.yaml"
    path.write_text(HOST_MODE_MANIFEST)
    m = load_manifest(path)
    assert m.network_mode == "host"
    assert m.dashboard_port_env == "HERMES_DASHBOARD_PORT"


def test_load_manifest_missing_file_raises(tmp_path):
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path / "nope.yaml")


def test_load_manifest_missing_required_field_raises(tmp_path):
    (tmp_path / "bad.yaml").write_text("type: x\n")
    with pytest.raises(ManifestError, match="missing required field 'image'"):
        load_manifest(tmp_path / "bad.yaml")
