import stat

import pytest

from crew.core import manager, paths
from crew.core.errors import CrewError, InstanceExistsError


def _iid(root, name="alice"):
    """The instance_id (hashed dir name) for a created base name."""
    iid = paths.resolve_instance_id(root, name)
    assert iid is not None and iid.startswith(f"{name}-")
    return iid


def _proj(root, name="alice"):
    """The compose project / container name = test-<instance_id>."""
    return f"test-{_iid(root, name)}"


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
    iid = _iid(root)
    # filesystem artifacts exist under the hashed dir
    assert paths.compose_path(root, iid).exists()
    env = (paths.instance_env_path(root, iid)).read_text()
    assert "CREW_PORT=9120" in env
    assert "TELEGRAM_BOT_TOKEN=tok" in env
    # docker up -d was invoked for this project (test-<iid>)
    assert (_proj(root), ["up", "-d"]) in calls


def test_create_stores_base_name_in_meta(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    assert paths.read_meta(root, iid)["name"] == "alice"


def test_create_dir_is_name_hex(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    import re
    assert re.fullmatch(r"alice-[0-9a-f]{6}", iid)
    assert paths.instance_dir(root, iid).is_dir()


def test_create_seeds_commented_allowed_emails_hint(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    env_path = paths.instance_env_path(root, _iid(root))
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


def test_recreate_after_purge_yields_new_instance_id(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    first = _iid(root)
    manager.remove(root, "alice", purge=True)
    assert paths.resolve_instance_id(root, "alice") is None
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    second = _iid(root)
    assert second.startswith("alice-")
    assert second != first


def test_create_errors_on_existing_namespaced_container(root, calls, monkeypatch):
    _agents_dir(root)
    import crew.core.manager as m
    # the container check sees test-<name>-<hex>; any test-alice-* exists
    monkeypatch.setattr(m, "_container_exists",
                        lambda name: name.startswith("test-alice-"))
    with pytest.raises(CrewError, match="already exists"):
        manager.create(root, "alice", type="hermes", creds={})


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
    assert paths.resolve_instance_id(root, "alice") is None


def test_create_with_layers_mounts_and_records_them(root, calls):
    _agents_dir(root)
    (root / "data" / "layers" / "knowledge").mkdir(parents=True)
    inst = manager.create(root, "alice", type="hermes",
                          creds={"TELEGRAM_BOT_TOKEN": "t"}, layers=["knowledge"])
    assert inst.name == "alice"
    iid = _iid(root)
    compose = paths.compose_path(root, iid).read_text()
    assert "../../layers/knowledge:/opt/shared/knowledge:ro" in compose
    assert paths.read_meta(root, iid)["layers"] == ["knowledge"]


def test_create_unknown_layer_rejected(root, calls):
    _agents_dir(root)
    from crew.core.errors import LayerNotFoundError
    with pytest.raises(LayerNotFoundError):
        manager.create(root, "alice", type="hermes",
                       creds={"TELEGRAM_BOT_TOKEN": "t"}, layers=["ghost"])
    assert paths.resolve_instance_id(root, "alice") is None


def test_remove_keeps_data_by_default(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    proj = _proj(root)
    manager.remove(root, "alice")
    # container down was called
    assert (proj, ["down"]) in calls
    # data preserved
    assert (paths.instance_dir(root, iid) / "data").exists()


def test_remove_purge_deletes_data(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.remove(root, "alice", purge=True)
    assert paths.resolve_instance_id(root, "alice") is None


def test_create_injects_host_uid_gid_env(root, calls):
    """Prevention: write the host uid/gid into instance.env so the agent
    container (which starts as root) drops privileges to the host user and
    never leaves root-owned files in the bind-mounted data/."""
    import os
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    env = paths.instance_env_path(root, _iid(root)).read_text()
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
    inst = paths.instance_dir(root, _iid(root))
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
    inst = paths.instance_dir(root, _iid(root))

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
                        lambda root, name, project: "running")
    inst = manager.status(root, "alice")
    assert inst.name == "alice"   # displays the base name, not the hashed id
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
    monkeypatch.setattr(manager, "_compose_state", lambda root, name, project: "running")
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.create(root, "bob", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    names = sorted(i.name for i in manager.list(root))
    assert names == ["alice", "bob"]   # base names, not hashed dirs


def test_list_survives_corrupt_instance(root, monkeypatch):
    _agents_dir(root)
    monkeypatch.setattr(manager, "_compose_state", lambda root, name, project: "running")
    # good instance: valid meta.json + instance.env with CREW_PORT
    good = paths.instance_dir(root, "alice-aaaaaa")
    good.mkdir(parents=True)
    paths.write_meta(root, "alice-aaaaaa", {"name": "alice", "type": "hermes", "image": "img:1"})
    paths.instance_env_path(root, "alice-aaaaaa").write_text("CREW_PORT=9120\n")
    # bad instance: corrupt meta.json makes read_meta raise CrewError
    bad = paths.instance_dir(root, "zombie-bbbbbb")
    bad.mkdir(parents=True)
    (bad / "meta.json").write_text("{ not json")
    paths.instance_env_path(root, "zombie-bbbbbb").write_text("CREW_PORT=9121\n")

    names = [i.name for i in manager.list(root)]
    assert names == ["alice"]


def test_lifecycle_start_stop_restart(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    proj = _proj(root)
    manager.lifecycle(root, "alice", "start")
    manager.lifecycle(root, "alice", "stop")
    manager.lifecycle(root, "alice", "restart")
    assert (proj, ["start"]) in calls
    assert (proj, ["stop"]) in calls
    assert (proj, ["restart"]) in calls


def test_update_pulls_and_recreates(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    proj = _proj(root)
    manager.update(root, "alice")
    assert (proj, ["pull"]) in calls
    assert (proj, ["up", "-d"]) in calls


def test_update_backup_snapshots_data(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    (paths.instance_dir(root, iid) / "data" / "marker.txt").write_text("x")
    manager.update(root, "alice", backup=True)
    backups = list((paths.instance_dir(root, iid)).glob("data.bak-*"))
    assert backups and (backups[0] / "marker.txt").exists()


def test_update_rerenders_compose_for_layer_changes(root, calls):
    _agents_dir(root)
    (root / "data" / "layers" / "knowledge").mkdir(parents=True)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    # operator adds a layer by editing meta.json, then updates
    meta = paths.read_meta(root, iid)
    meta["layers"] = ["knowledge"]
    paths.write_meta(root, iid, meta)
    manager.update(root, "alice")
    compose = paths.compose_path(root, iid).read_text()
    assert "../../layers/knowledge:/opt/shared/knowledge:ro" in compose


def test_create_env_file_order_shared_then_instance(root, monkeypatch):
    _agents_dir(root)
    (root / "data" / "_shared.env").write_text("CREW_PROJECT=test\nHERMES_UID=501\n")
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


def test_remove_regenerates_union(root, calls, monkeypatch):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={})
    import crew.core.gateway as gateway
    regen = []
    monkeypatch.setattr(gateway, "regenerate_union_emails", lambda r: regen.append(r))
    manager.remove(root, "alice")
    assert regen == [root]


def test_create_regenerates_union(root, calls, monkeypatch):
    _agents_dir(root)
    import crew.core.gateway as gateway
    regen = []
    monkeypatch.setattr(gateway, "regenerate_union_emails", lambda r: regen.append(r))
    manager.create(root, "bob", type="hermes", creds={})
    assert regen == [root]


def test_create_validates_and_records_credentials(root, calls):
    _agents_dir(root)
    (root / "data" / "credentials").mkdir(parents=True)
    (root / "data" / "credentials" / "anthropic.env").write_text("ANTHROPIC_API_KEY=secret\n")
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["anthropic"])
    iid = _iid(root)
    assert paths.read_meta(root, iid)["credentials"] == ["anthropic"]
    compose = paths.compose_path(root, iid).read_text()
    assert "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}" in compose
    assert "secret" not in compose


def test_create_unknown_credential_rejected(root, calls):
    _agents_dir(root)
    from crew.core.errors import CredentialNotFoundError
    with pytest.raises(CredentialNotFoundError):
        manager.create(root, "alice", type="hermes",
                       creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["ghost"])
    assert paths.resolve_instance_id(root, "alice") is None


def test_env_files_order_shared_then_credentials_then_instance(root, calls):
    _agents_dir(root)
    (root / "data" / "_shared.env").write_text("CREW_PROJECT=test\nHERMES_UID=501\n")
    (root / "data" / "credentials").mkdir(parents=True)
    (root / "data" / "credentials" / "anthropic.env").write_text("ANTHROPIC_API_KEY=secret\n")
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["anthropic"])
    iid = _iid(root)
    files = manager._env_files(root, iid)
    assert files[0] == paths.shared_env_path(root)
    assert files[1] == paths.credential_path(root, "anthropic")
    assert files[-1] == paths.instance_env_path(root, iid)


def test_update_reapplies_credentials(root, calls):
    _agents_dir(root)
    (root / "data" / "credentials").mkdir(parents=True)
    (root / "data" / "credentials" / "anthropic.env").write_text("ANTHROPIC_API_KEY=secret\n")
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, credentials=["anthropic"])
    iid = _iid(root)
    paths.compose_path(root, iid).write_text("stale\n")
    manager.update(root, "alice")
    compose = paths.compose_path(root, iid).read_text()
    assert "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}" in compose


def test_create_records_image_and_no_previous(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    meta = paths.read_meta(root, iid)
    assert meta["image"] == "nousresearch/hermes-agent:latest"
    assert "previous_image" not in meta
    compose = paths.compose_path(root, iid).read_text()
    assert "image: nousresearch/hermes-agent:latest" in compose


def test_bare_update_renders_from_instance_pin(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    proj = _proj(root)
    meta = paths.read_meta(root, iid)
    meta["image"] = "nousresearch/hermes-agent@sha256:pinned"
    paths.write_meta(root, iid, meta)
    manager.update(root, "alice")
    compose = paths.compose_path(root, iid).read_text()
    assert "image: nousresearch/hermes-agent@sha256:pinned" in compose
    meta2 = paths.read_meta(root, iid)
    assert meta2["image"] == "nousresearch/hermes-agent@sha256:pinned"
    assert "previous_image" not in meta2
    assert (proj, ["pull"]) in calls
    assert (proj, ["up", "-d"]) in calls


def test_update_image_sets_pin_and_previous(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:new")
    meta = paths.read_meta(root, iid)
    assert meta["image"] == "nousresearch/hermes-agent@sha256:new"
    assert meta["previous_image"] == "nousresearch/hermes-agent:latest"
    compose = paths.compose_path(root, iid).read_text()
    assert "image: nousresearch/hermes-agent@sha256:new" in compose


def test_update_image_restores_on_pull_failure(root, monkeypatch):
    _agents_dir(root)
    def ok_run(project, compose_file, env_files, args, capture=False):
        class R: stdout = ""
        return R()
    monkeypatch.setattr(manager, "run_compose", ok_run)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    old_compose = paths.compose_path(root, iid).read_text()
    def boom(project, compose_file, env_files, args, capture=False):
        if args == ["pull"]:
            raise RuntimeError("no such image")
        class R: stdout = ""
        return R()
    monkeypatch.setattr(manager, "run_compose", boom)
    import pytest
    with pytest.raises(RuntimeError):
        manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:typo")
    meta = paths.read_meta(root, iid)
    assert meta["image"] == "nousresearch/hermes-agent:latest"
    assert "previous_image" not in meta
    assert paths.compose_path(root, iid).read_text() == old_compose


def test_update_rollback_swaps_current_and_previous(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:v2")
    manager.update(root, "alice", rollback=True)
    meta = paths.read_meta(root, iid)
    assert meta["image"] == "nousresearch/hermes-agent:latest"
    assert meta["previous_image"] == "nousresearch/hermes-agent@sha256:v2"


def test_update_rollback_twice_returns_to_original(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:v2")
    manager.update(root, "alice", rollback=True)
    manager.update(root, "alice", rollback=True)
    meta = paths.read_meta(root, iid)
    assert meta["image"] == "nousresearch/hermes-agent@sha256:v2"


def test_update_rollback_without_previous_errors(root, calls):
    import pytest
    from crew.core.errors import CrewError
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    with pytest.raises(CrewError, match="no previous image"):
        manager.update(root, "alice", rollback=True)


def test_update_to_default_repins_to_manifest(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:old")
    manager.update(root, "alice", to_default=True)
    meta = paths.read_meta(root, iid)
    assert meta["image"] == "nousresearch/hermes-agent:latest"
    assert meta["previous_image"] == "nousresearch/hermes-agent@sha256:old"


def test_update_rejects_combined_version_flags(root, calls):
    import pytest
    from crew.core.errors import CrewError
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    with pytest.raises(CrewError, match="only one of"):
        manager.update(root, "alice", image="x:1", rollback=True)


def test_status_reports_previous_image(root, calls, monkeypatch):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.update(root, "alice", image="nousresearch/hermes-agent@sha256:v2")
    monkeypatch.setattr(manager, "_compose_state", lambda root, name, project: "running")
    inst = manager.status(root, "alice")
    assert inst.image == "nousresearch/hermes-agent@sha256:v2"
    assert inst.previous_image == "nousresearch/hermes-agent:latest"


def test_write_meta_atomic_no_temp_left(root):
    from crew.core import paths
    d = paths.instance_dir(root, "alice"); d.mkdir(parents=True)
    paths.write_meta(root, "alice", {"image": "x:1"})
    assert paths.read_meta(root, "alice") == {"image": "x:1"}
    # no leftover temp files
    assert not [p for p in d.iterdir() if p.name.endswith(".tmp")]


def test_instance_env_is_0600(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    mode = stat.S_IMODE(paths.instance_env_path(root, _iid(root)).stat().st_mode)
    assert mode == 0o600


def test_create_failure_cleans_up_instance_dir(root, monkeypatch):
    _agents_dir(root)
    def boom(*a, **k): raise RuntimeError("up failed")
    monkeypatch.setattr(manager, "run_compose", boom)
    with pytest.raises(RuntimeError):
        manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    assert paths.resolve_instance_id(root, "alice") is None


def test_create_default_timezone_kst(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    assert paths.read_meta(root, iid)["timezone"] == "Asia/Seoul"
    assert "TZ=Asia/Seoul" in paths.compose_path(root, iid).read_text()


def test_create_custom_timezone(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, tz="America/New_York")
    iid = _iid(root)
    assert paths.read_meta(root, iid)["timezone"] == "America/New_York"
    assert "TZ=America/New_York" in paths.compose_path(root, iid).read_text()


def test_create_invalid_timezone_rejected(root, calls):
    import pytest
    from crew.core.errors import CrewError
    _agents_dir(root)
    with pytest.raises(CrewError, match="invalid timezone"):
        manager.create(root, "alice", type="hermes",
                       creds={"TELEGRAM_BOT_TOKEN": "t"}, tz="Mars/Phobos")
    assert paths.resolve_instance_id(root, "alice") is None


def test_update_timezone_changes_it(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    manager.update(root, "alice", tz="UTC")
    assert paths.read_meta(root, iid)["timezone"] == "UTC"
    assert "TZ=UTC" in paths.compose_path(root, iid).read_text()


def test_update_invalid_timezone_rejected(root, calls):
    import pytest
    from crew.core.errors import CrewError
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    with pytest.raises(CrewError, match="invalid timezone"):
        manager.update(root, "alice", tz="Nope/Nope")


def test_render_backcompat_defaults_timezone(root, calls):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    meta = paths.read_meta(root, iid)
    del meta["timezone"]
    paths.write_meta(root, iid, meta)
    manager.update(root, "alice")
    assert "TZ=Asia/Seoul" in paths.compose_path(root, iid).read_text()


def test_status_reports_timezone(root, calls, monkeypatch):
    _agents_dir(root)
    manager.create(root, "alice", type="hermes",
                   creds={"TELEGRAM_BOT_TOKEN": "t"}, tz="Europe/London")
    monkeypatch.setattr(manager, "_compose_state", lambda root, name, project: "running")
    assert manager.status(root, "alice").timezone == "Europe/London"


def test_create_writes_stable_session_token(root, calls):
    from crew.core.creds import parse_env_file
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    env = parse_env_file(paths.instance_env_path(root, _iid(root)))
    assert len(env.get("HERMES_DASHBOARD_SESSION_TOKEN", "")) >= 20


def test_session_token_passed_through_not_inlined(root, calls):
    from crew.core.creds import parse_env_file
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    tok = parse_env_file(paths.instance_env_path(root, iid))["HERMES_DASHBOARD_SESSION_TOKEN"]
    compose = paths.compose_path(root, iid).read_text()
    assert "HERMES_DASHBOARD_SESSION_TOKEN=${HERMES_DASHBOARD_SESSION_TOKEN:-}" in compose
    assert tok not in compose


def test_each_instance_gets_distinct_session_token(root, calls):
    from crew.core.creds import parse_env_file
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    manager.create(root, "bob", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    a = parse_env_file(paths.instance_env_path(root, _iid(root, "alice")))["HERMES_DASHBOARD_SESSION_TOKEN"]
    b = parse_env_file(paths.instance_env_path(root, _iid(root, "bob")))["HERMES_DASHBOARD_SESSION_TOKEN"]
    assert a != b


def test_update_adds_session_token_to_legacy_instance(root, calls):
    from crew.core.creds import parse_env_file
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    env_path = paths.instance_env_path(root, _iid(root))
    lines = [ln for ln in env_path.read_text().splitlines()
             if not ln.startswith("HERMES_DASHBOARD_SESSION_TOKEN=")]
    env_path.write_text("\n".join(lines) + "\n")
    assert "HERMES_DASHBOARD_SESSION_TOKEN" not in parse_env_file(env_path)
    manager.update(root, "alice")
    assert "HERMES_DASHBOARD_SESSION_TOKEN" in parse_env_file(env_path)


def test_update_keeps_existing_session_token(root, calls):
    from crew.core.creds import parse_env_file
    _agents_dir(root)
    manager.create(root, "alice", type="hermes", creds={"TELEGRAM_BOT_TOKEN": "t"})
    iid = _iid(root)
    before = parse_env_file(paths.instance_env_path(root, iid))["HERMES_DASHBOARD_SESSION_TOKEN"]
    manager.update(root, "alice")
    after = parse_env_file(paths.instance_env_path(root, iid))["HERMES_DASHBOARD_SESSION_TOKEN"]
    assert before == after
