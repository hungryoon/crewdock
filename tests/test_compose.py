import yaml

from crew.core.compose import render_compose
from crew.core.manifest import load_manifest

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
passthrough_env:
  - TELEGRAM_BOT_TOKEN
credentials:
  bot_token:
    required: true
    env: TELEGRAM_BOT_TOKEN
"""

PORT_ENV_BRIDGE_MANIFEST = """\
type: hermes
image: nousresearch/hermes-agent:latest
run_command: ["gateway", "run"]
data_mount: /opt/data
dashboard:
  container_port: 9119
  host: 127.0.0.1
  path: /
  port_env: HERMES_DASHBOARD_PORT
env:
  HERMES_DASHBOARD: "1"
"""


def test_render_produces_valid_compose_with_interpolated_secrets(manifest_file):
    m = load_manifest(manifest_file)
    text = render_compose(m, name="alice", port=9123)
    doc = yaml.safe_load(text)

    svc = doc["services"]["agent"]
    assert svc["image"] == "nousresearch/hermes-agent:latest"
    assert svc["container_name"] == "crew-alice"
    assert svc["restart"] == "unless-stopped"
    assert svc["volumes"] == ["./data:/opt/data"]
    # host port is interpolated, NOT baked
    assert svc["ports"] == ["127.0.0.1:${CREW_PORT}:9119"]
    assert svc["command"] == ["gateway", "run"]
    assert svc["mem_limit"] == "4g"
    # static env baked literally
    assert "HERMES_DASHBOARD=1" in svc["environment"]
    # passthrough secrets referenced, never baked
    assert "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}" in svc["environment"]
    assert "HERMES_UID=${HERMES_UID}" in svc["environment"]


def test_render_has_no_literal_secret_values(manifest_file):
    m = load_manifest(manifest_file)
    text = render_compose(m, name="alice", port=9123)
    # the only port literal is the container port (9119); host port stays a var
    assert "9123" not in text


def test_render_mounts_selected_layers_read_only(manifest_file):
    m = load_manifest(manifest_file)
    text = render_compose(m, name="alice", port=9123,
                          layers=["knowledge", "brand-voice"])
    doc = yaml.safe_load(text)
    vols = doc["services"]["agent"]["volumes"]
    assert "./data:/opt/data" in vols
    assert "../../layers/knowledge:/opt/shared/knowledge:ro" in vols
    assert "../../layers/brand-voice:/opt/shared/brand-voice:ro" in vols


def test_render_no_layers_mounts_only_data(manifest_file):
    m = load_manifest(manifest_file)
    doc = yaml.safe_load(render_compose(m, name="bob", port=9124))
    assert doc["services"]["agent"]["volumes"] == ["./data:/opt/data"]


def test_render_bridge_mode_no_network_mode_line(manifest_file):
    # default bridge manifest must not emit a network_mode key
    text = render_compose(load_manifest(manifest_file), name="alice", port=9123)
    doc = yaml.safe_load(text)
    assert "network_mode" not in doc["services"]["agent"]
    assert doc["services"]["agent"]["ports"] == ["127.0.0.1:${CREW_PORT}:9119"]


def test_render_bridge_mode_port_env_uses_container_port(tmp_path):
    path = tmp_path / "bridge.yaml"
    path.write_text(PORT_ENV_BRIDGE_MANIFEST)
    text = render_compose(load_manifest(path), name="alice", port=9123)
    doc = yaml.safe_load(text)
    svc = doc["services"]["agent"]
    assert svc["ports"] == ["127.0.0.1:${CREW_PORT}:9119"]
    assert "network_mode" not in svc
    assert "HERMES_DASHBOARD_PORT=9119" in svc["environment"]


def test_render_host_mode(tmp_path):
    path = tmp_path / "host.yaml"
    path.write_text(HOST_MODE_MANIFEST)
    text = render_compose(load_manifest(path), name="alice", port=9123,
                          layers=["knowledge"])
    doc = yaml.safe_load(text)
    svc = doc["services"]["agent"]
    # host networking declared
    assert svc["network_mode"] == "host"
    # ports block omitted entirely
    assert "ports" not in svc
    # dashboard port injected as the allocated host port var
    assert "HERMES_DASHBOARD_PORT=${CREW_PORT}" in svc["environment"]
    assert "HERMES_DASHBOARD_HOST=127.0.0.1" in svc["environment"]
    # volumes (RW data + RO layer) unchanged
    assert "./data:/opt/data" in svc["volumes"]
    assert "../../layers/knowledge:/opt/shared/knowledge:ro" in svc["volumes"]
    # allocated port literal never baked
    assert "9123" not in text


def test_render_compose_includes_credential_keys_as_passthrough(manifest_file):
    m = load_manifest(manifest_file)
    out = render_compose(m, "alice", 9120,
                         credential_keys=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
    assert "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" in out
    assert "OPENAI_API_KEY=${OPENAI_API_KEY}" in out


def test_render_compose_credential_keys_dedupe_against_passthrough(manifest_file):
    m = load_manifest(manifest_file)
    # a key already in manifest.passthrough_env must not be rendered twice
    dup = m.passthrough_env[0]
    out = render_compose(m, "alice", 9120, credential_keys=[dup])
    assert out.count(f"{dup}=${{{dup}}}") == 1


def test_render_compose_uses_image_override():
    from crew.core.compose import render_compose
    from crew.core.manifest import load_manifest
    from tests.conftest import SAMPLE_MANIFEST
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp()) / "hermes.yaml"
    d.write_text(SAMPLE_MANIFEST)
    manifest = load_manifest(d)
    out = render_compose(manifest, "alice", 9120,
                         image="nousresearch/hermes-agent@sha256:abc")
    assert "image: nousresearch/hermes-agent@sha256:abc" in out
    assert "image: nousresearch/hermes-agent:latest" not in out


def test_render_compose_falls_back_to_manifest_image():
    from crew.core.compose import render_compose
    from crew.core.manifest import load_manifest
    from tests.conftest import SAMPLE_MANIFEST
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp()) / "hermes.yaml"
    d.write_text(SAMPLE_MANIFEST)
    manifest = load_manifest(d)
    out = render_compose(manifest, "alice", 9120)
    assert "image: nousresearch/hermes-agent:latest" in out


def _load_sample_manifest():
    from crew.core.manifest import load_manifest
    from tests.conftest import SAMPLE_MANIFEST
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp()) / "hermes.yaml"
    d.write_text(SAMPLE_MANIFEST)
    return load_manifest(d)


def test_render_compose_includes_default_timezone():
    from crew.core.compose import render_compose
    out = render_compose(_load_sample_manifest(), "alice", 9120)
    assert "TZ=Asia/Seoul" in out


def test_render_compose_timezone_override():
    from crew.core.compose import render_compose
    out = render_compose(_load_sample_manifest(), "alice", 9120, timezone="UTC")
    assert "TZ=UTC" in out
