import pytest

from crew.core import manager, paths
from crew.core.errors import InstanceExistsError


@pytest.fixture(autouse=True)
def deterministic_ports(monkeypatch):
    """Make port allocation depend only on the reserved set, not real host port state.

    This keeps the create tests hermetic even when a live crew instance is
    holding a host port (e.g. 9120) that find_free_port would otherwise skip.
    """
    import crew.core.ports as ports
    monkeypatch.setattr(ports, "_is_free", lambda p: True)


@pytest.fixture
def calls(monkeypatch):
    """Capture run_compose calls so tests never touch real docker."""
    recorded = []

    def fake_run(project, compose_file, env_files, args, capture=False):
        recorded.append((project, args))
        class R:
            stdout = ""
        return R()

    monkeypatch.setattr(manager, "run_compose", fake_run)
    return recorded


def _agents_dir(root):
    # place a hermes manifest at <root>/agents/hermes.yaml
    from tests.conftest import SAMPLE_MANIFEST
    d = root / "agents"
    d.mkdir(exist_ok=True)
    (d / "hermes.yaml").write_text(SAMPLE_MANIFEST)
    return d


def test_create_builds_instance_and_runs_up(root, calls):
    _agents_dir(root)
    inst = manager.create(root, "alice", type="hermes",
                          creds={"TELEGRAM_BOT_TOKEN": "tok"})
    assert inst.name == "alice"
    assert inst.port == 9120
    # filesystem artifacts exist
    assert paths.compose_path(root, "alice").exists()
    env = (paths.instance_env_path(root, "alice")).read_text()
    assert "CREW_PORT=9120" in env
    assert "TELEGRAM_BOT_TOKEN=tok" in env
    # docker up -d was invoked for this project
    assert ("crew-alice", ["up", "-d"]) in calls


def test_create_rejects_duplicate(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    with pytest.raises(InstanceExistsError):
        manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})


def test_create_second_instance_gets_next_port(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    bob = manager.create(root, "bob", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    assert bob.port == 9121


def test_create_rollback_on_up_failure(root, monkeypatch):
    _agents_dir(root)

    def boom(*a, **k):
        raise RuntimeError("docker down")

    monkeypatch.setattr(manager, "run_compose", boom)
    with pytest.raises(RuntimeError):
        manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    # directory cleaned up
    assert not paths.instance_dir(root, "alice").exists()


def test_create_with_layers_mounts_and_records_them(root, calls):
    _agents_dir(root)
    (root / "layers" / "knowledge").mkdir(parents=True)
    inst = manager.create(root, "alice", type="hermes",
                          creds={"TELEGRAM_BOT_TOKEN": "t"}, layers=["knowledge"])
    assert inst.name == "alice"
    compose = paths.compose_path(root, "alice").read_text()
    assert "../../layers/knowledge:/opt/shared/knowledge:ro" in compose
    assert paths.read_meta(root, "alice")["layers"] == ["knowledge"]


def test_create_unknown_layer_rejected(root, calls):
    _agents_dir(root)
    from crew.core.errors import LayerNotFoundError
    with pytest.raises(LayerNotFoundError):
        manager.create(root, "alice", type="hermes",
                       creds={"TELEGRAM_BOT_TOKEN": "t"}, layers=["ghost"])
    assert not paths.instance_dir(root, "alice").exists()


def test_remove_keeps_data_by_default(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.remove(root, "alice")
    # container down was called
    assert ("crew-alice", ["down"]) in calls
    # data preserved
    assert (paths.instance_dir(root, "alice") / "data").exists()


def test_remove_purge_deletes_data(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.remove(root, "alice", purge=True)
    assert not paths.instance_dir(root, "alice").exists()


def test_remove_missing_raises(root, calls):
    _agents_dir(root)
    from crew.core.errors import InstanceNotFoundError
    with pytest.raises(InstanceNotFoundError):
        manager.remove(root, "ghost")


def test_status_reads_state_from_docker(root, monkeypatch):
    _agents_dir(root)

    def fake_run(project, compose_file, env_files, args, capture=False):
        class R:
            stdout = ""
        return R()

    monkeypatch.setattr(manager, "run_compose", fake_run)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})

    # ps reports a running container
    monkeypatch.setattr(manager, "_compose_state",
                        lambda root, name: "running")
    inst = manager.status(root, "alice")
    assert inst.name == "alice"
    assert inst.port == 9120
    assert inst.state == "running"
    assert inst.image == "nousresearch/hermes-agent:latest"


def test_list_returns_all_instances(root, monkeypatch):
    _agents_dir(root)

    def fake_run(project, compose_file, env_files, args, capture=False):
        class R:
            stdout = ""
        return R()

    monkeypatch.setattr(manager, "run_compose", fake_run)
    monkeypatch.setattr(manager, "_compose_state", lambda root, name: "running")
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.create(root, "bob", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    names = sorted(i.name for i in manager.list(root))
    assert names == ["alice", "bob"]


def test_lifecycle_start_stop_restart(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.lifecycle(root, "alice", "start")
    manager.lifecycle(root, "alice", "stop")
    manager.lifecycle(root, "alice", "restart")
    assert ("crew-alice", ["start"]) in calls
    assert ("crew-alice", ["stop"]) in calls
    assert ("crew-alice", ["restart"]) in calls


def test_update_pulls_and_recreates(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.update(root, "alice")
    assert ("crew-alice", ["pull"]) in calls
    assert ("crew-alice", ["up", "-d"]) in calls


def test_update_backup_snapshots_data(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    (paths.instance_dir(root, "alice") / "data" / "marker.txt").write_text("x")
    manager.update(root, "alice", backup=True)
    backups = list((paths.instance_dir(root, "alice")).glob("data.bak-*"))
    assert backups and (backups[0] / "marker.txt").exists()


def test_update_rerenders_compose_for_layer_changes(root, calls):
    _agents_dir(root)
    (root / "layers" / "knowledge").mkdir(parents=True)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    # operator adds a layer by editing meta.json, then updates
    meta = paths.read_meta(root, "alice")
    meta["layers"] = ["knowledge"]
    paths.write_meta(root, "alice", meta)
    manager.update(root, "alice")
    compose = paths.compose_path(root, "alice").read_text()
    assert "../../layers/knowledge:/opt/shared/knowledge:ro" in compose


def test_create_env_file_order_shared_then_instance(root, monkeypatch):
    _agents_dir(root)
    (root / "instances" / "_shared.env").write_text("HERMES_UID=501\n")
    recorded = {}

    def fake_run(project, compose_file, env_files, args, capture=False):
        recorded["env_files"] = [p.name for p in env_files]
        class R:
            stdout = ""
        return R()

    monkeypatch.setattr(manager, "run_compose", fake_run)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    assert recorded["env_files"] == ["_shared.env", "instance.env"]


def test_shell_argv_uses_exec(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    argv = manager.shell_argv(root, "alice")
    assert argv[:2] == ["docker", "compose"]
    assert "exec" in argv
    assert "agent" in argv
