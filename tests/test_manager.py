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


def test_create_seeds_commented_allowed_emails_hint(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    env_path = paths.instance_env_path(root, "alice")
    text = env_path.read_text()
    # the key is pre-seeded as a hint, but commented out so it stays inactive
    assert "# CREW_ALLOWED_EMAILS=" in text
    from crew.core.creds import parse_env_file
    assert "CREW_ALLOWED_EMAILS" not in parse_env_file(env_path)


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


def test_create_injects_host_uid_gid_env(root, calls):
    """Prevention: write the host uid/gid into instance.env so the agent
    container (which starts as root) drops privileges to the host user and
    never leaves root-owned files in the bind-mounted data/."""
    import os
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    env = paths.instance_env_path(root, "alice").read_text()
    assert f"CREW_UID={os.getuid()}" in env
    assert f"CREW_GID={os.getgid()}" in env
    # manifest's host_user_env maps the canonical ids onto image-specific names
    assert f"HERMES_UID={os.getuid()}" in env
    assert f"HERMES_GID={os.getgid()}" in env


def test_remove_purge_repairs_unwritable_dirs_on_host(root, calls, monkeypatch):
    """Recovery (common case): agents create dirs without the write bit, which
    blocks plain rmtree. Purge must chmod-repair and finish on the host alone —
    no root container needed."""
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    inst = paths.instance_dir(root, "alice")
    locked = inst / "data" / "skills" / "media"
    locked.mkdir(parents=True)
    (locked / "f").write_text("x")
    locked.chmod(0o500)  # owner loses write -> rmtree can't unlink f

    container_called = []
    monkeypatch.setattr(manager, "_root_delete_contents",
                        lambda p: container_called.append(p))

    manager.remove(root, "alice", purge=True)
    assert not inst.exists()
    assert container_called == []  # host repaired it without the container


def test_remove_purge_falls_back_to_root_container(root, calls, monkeypatch):
    """Recovery (root-owned residue): when the host genuinely can't delete the
    files, purge falls back to a root container instead of silently succeeding."""
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    inst = paths.instance_dir(root, "alice")

    # Host removal fails on the first pass; the container clears it; pass two wins.
    outcomes = iter([False, True])
    monkeypatch.setattr(manager, "_try_rmtree", lambda p: next(outcomes))
    container_called = []
    monkeypatch.setattr(manager, "_root_delete_contents",
                        lambda p: container_called.append(p))

    manager.remove(root, "alice", purge=True)
    assert container_called == [inst]


def test_remove_purge_raises_when_residue_survives(root, calls, monkeypatch):
    """Never silently succeed: if residue survives even the container fallback,
    purge surfaces a CrewError with a manual-cleanup hint."""
    from crew.core.errors import CrewError
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    monkeypatch.setattr(manager, "_try_rmtree", lambda p: False)
    monkeypatch.setattr(manager, "_root_delete_contents", lambda p: None)
    with pytest.raises(CrewError, match="sudo rm -rf"):
        manager.remove(root, "alice", purge=True)


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


def test_remove_unpublishes_if_exposed(root, calls, monkeypatch):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    import crew.core.expose as expose
    paths.exposed_marker_path(root, "alice").write_text("")
    unexposed = []
    monkeypatch.setattr(expose, "unexpose", lambda r, n: unexposed.append(n))
    manager.remove(root, "alice")
    assert unexposed == ["alice"]


def test_remove_skips_unpublish_when_not_exposed(root, calls, monkeypatch):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    import crew.core.expose as expose
    unexposed = []
    monkeypatch.setattr(expose, "unexpose", lambda r, n: unexposed.append(n))
    manager.remove(root, "alice")   # no marker written -> not exposed
    assert unexposed == []


def test_create_validates_and_records_credentials(root, calls):
    _agents_dir(root)
    (root / "credentials").mkdir()
    (root / "credentials" / "anthropic.env").write_text("ANTHROPIC_API_KEY=secret\n")
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["anthropic"])
    assert paths.read_meta(root, "alice")["credentials"] == ["anthropic"]
    compose = paths.compose_path(root, "alice").read_text()
    assert "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" in compose
    assert "secret" not in compose


def test_create_unknown_credential_rejected(root, calls):
    _agents_dir(root)
    from crew.core.errors import CredentialNotFoundError
    with pytest.raises(CredentialNotFoundError):
        manager.create(root, "alice", type="hermes",
                       creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["ghost"])
    assert not paths.instance_dir(root, "alice").exists()


def test_env_files_order_shared_then_credentials_then_instance(root, calls):
    _agents_dir(root)
    (root / "instances" / "_shared.env").write_text("HERMES_UID=501\n")
    (root / "credentials").mkdir()
    (root / "credentials" / "anthropic.env").write_text("ANTHROPIC_API_KEY=secret\n")
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["anthropic"])
    files = manager._env_files(root, "alice")
    assert files[0] == paths.shared_env_path(root)
    assert files[1] == paths.credential_path(root, "anthropic")
    assert files[-1] == paths.instance_env_path(root, "alice")


def test_update_reapplies_credentials(root, calls):
    _agents_dir(root)
    (root / "credentials").mkdir()
    (root / "credentials" / "anthropic.env").write_text("ANTHROPIC_API_KEY=secret\n")
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["anthropic"])
    paths.compose_path(root, "alice").write_text("stale\n")
    manager.update(root, "alice")
    compose = paths.compose_path(root, "alice").read_text()
    assert "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" in compose


def test_create_records_image_and_no_previous(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    meta = paths.read_meta(root, "alice")
    assert meta["image"] == "nousresearch/hermes-agent:latest"
    assert "previous_image" not in meta
    compose = paths.compose_path(root, "alice").read_text()
    assert "image: nousresearch/hermes-agent:latest" in compose


def test_bare_update_renders_from_instance_pin(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    meta = paths.read_meta(root, "alice")
    meta["image"] = "nousresearch/hermes-agent@sha256:pinned"
    paths.write_meta(root, "alice", meta)
    manager.update(root, "alice")
    compose = paths.compose_path(root, "alice").read_text()
    assert "image: nousresearch/hermes-agent@sha256:pinned" in compose
    meta2 = paths.read_meta(root, "alice")
    assert meta2["image"] == "nousresearch/hermes-agent@sha256:pinned"
    assert "previous_image" not in meta2
    assert ("crew-alice", ["pull"]) in calls
    assert ("crew-alice", ["up", "-d"]) in calls


def test_update_image_sets_pin_and_previous(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:new")
    meta = paths.read_meta(root, "alice")
    assert meta["image"] == "nousresearch/hermes-agent@sha256:new"
    assert meta["previous_image"] == "nousresearch/hermes-agent:latest"
    compose = paths.compose_path(root, "alice").read_text()
    assert "image: nousresearch/hermes-agent@sha256:new" in compose


def test_update_image_restores_on_pull_failure(root, monkeypatch):
    _agents_dir(root)
    def ok_run(project, compose_file, env_files, args, capture=False):
        class R: stdout = ""
        return R()
    monkeypatch.setattr(manager, "run_compose", ok_run)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    old_compose = paths.compose_path(root, "alice").read_text()
    def boom(project, compose_file, env_files, args, capture=False):
        if args == ["pull"]:
            raise RuntimeError("no such image")
        class R: stdout = ""
        return R()
    monkeypatch.setattr(manager, "run_compose", boom)
    import pytest
    with pytest.raises(RuntimeError):
        manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:typo")
    meta = paths.read_meta(root, "alice")
    assert meta["image"] == "nousresearch/hermes-agent:latest"
    assert "previous_image" not in meta
    assert paths.compose_path(root, "alice").read_text() == old_compose


def test_update_rollback_swaps_current_and_previous(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:v2")
    manager.update(root, "alice", rollback=True)
    meta = paths.read_meta(root, "alice")
    assert meta["image"] == "nousresearch/hermes-agent:latest"
    assert meta["previous_image"] == "nousresearch/hermes-agent@sha256:v2"


def test_update_rollback_twice_returns_to_original(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:v2")
    manager.update(root, "alice", rollback=True)
    manager.update(root, "alice", rollback=True)
    meta = paths.read_meta(root, "alice")
    assert meta["image"] == "nousresearch/hermes-agent@sha256:v2"


def test_update_rollback_without_previous_errors(root, calls):
    import pytest
    from crew.core.errors import CrewError
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    with pytest.raises(CrewError, match="no previous image"):
        manager.update(root, "alice", rollback=True)
