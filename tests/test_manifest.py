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
    assert m.passthrough_env == ["HERMES_UID", "HERMES_GID",
                                 "HERMES_DASHBOARD_SESSION_TOKEN"]
    assert m.mem_limit == "4g"
    assert m.cpus == 2
    assert m.seed_config == "seed/config.yaml"


def test_load_manifest_network_defaults(manifest_file):
    # SAMPLE_MANIFEST omits network_mode and dashboard.port_env -> defaults
    m = load_manifest(manifest_file)
    assert m.network_mode == "bridge"
    assert m.dashboard_port_env is None


def test_shipped_hermes_manifest_is_bridge_isolated():
    # The real shipped default manifest must be bridge-networked (isolated from
    # the host router) with the dashboard bound 0.0.0.0 inside the container
    # (safe: loopback-only host publish + per-instance bridge + gateway SSO).
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    m = load_manifest(repo_root / "agents" / "hermes.yaml")
    assert m.network_mode == "bridge"
    assert m.static_env["HERMES_DASHBOARD_HOST"] == "0.0.0.0"


def test_shipped_hermes_manifest_keeps_insecure_for_pre_hardening_images():
    # Instances still pinned to a pre-June-2026 image open their dashboard ONLY
    # via --insecure, which docker/s6-rc.d/dashboard/run derives from this var.
    # Current images accept-and-ignore it (they just warn), so keeping it is a
    # no-op there -- but drop it and every still-pinned instance loses its
    # dashboard with no provider configured.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    m = load_manifest(repo_root / "agents" / "hermes.yaml")
    assert m.static_env["HERMES_DASHBOARD_INSECURE"] == "1"


def test_shipped_hermes_manifest_satisfies_the_auth_gate():
    # A 0.0.0.0 bind engages Hermes' auth gate, which needs a registered
    # provider or the dashboard refuses to start. The basic provider's
    # username+password is what opens it, and it is deliberately NOT the OIDC
    # provider: an OIDC redirect_uri is derived per instance, so every new
    # instance would need its callback registered by hand on the Google client.
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    m = load_manifest(repo_root / "agents" / "hermes.yaml")
    for key in ("HERMES_DASHBOARD_BASIC_AUTH_USERNAME",
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"):
        assert key in m.passthrough_env, key
    # No per-instance OAuth surface: nothing to register anywhere.
    assert not [k for k in m.passthrough_env if "OIDC" in k or "PUBLIC_URL" in k]


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
