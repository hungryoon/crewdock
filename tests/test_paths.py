import re

import pytest

from crew.core.errors import CrewError, InvalidNameError
from crew.core import paths


def test_new_instance_id_shape():
    for _ in range(20):
        iid = paths.new_instance_id("ted")
        assert re.fullmatch(r"ted-[0-9a-f]{6}", iid)


def test_resolve_instance_id_by_meta_name(root):
    d = root / "data" / "instances" / "ted-aaaaaa"
    d.mkdir(parents=True)
    paths.write_meta(root, "ted-aaaaaa", {"name": "ted"})
    assert paths.resolve_instance_id(root, "ted") == "ted-aaaaaa"


def test_resolve_instance_id_full_id_exact_match(root):
    d = root / "data" / "instances" / "ted-aaaaaa"
    d.mkdir(parents=True)
    paths.write_meta(root, "ted-aaaaaa", {"name": "ted"})
    assert paths.resolve_instance_id(root, "ted-aaaaaa") == "ted-aaaaaa"


def test_resolve_instance_id_none_when_absent(root):
    assert paths.resolve_instance_id(root, "ghost") is None


def test_resolve_instance_id_ambiguous_raises(root):
    for hexid in ("aaaaaa", "bbbbbb"):
        d = root / "data" / "instances" / f"ted-{hexid}"
        d.mkdir(parents=True)
        paths.write_meta(root, f"ted-{hexid}", {"name": "ted"})
    with pytest.raises(CrewError, match="ambiguous"):
        paths.resolve_instance_id(root, "ted")


def test_instance_base_name_returns_meta_name(root):
    d = root / "data" / "instances" / "ted-aaaaaa"
    d.mkdir(parents=True)
    paths.write_meta(root, "ted-aaaaaa", {"name": "ted"})
    assert paths.instance_base_name(root, "ted-aaaaaa") == "ted"


def test_validate_name_accepts_kebab(root):
    paths.validate_name("alice-1")  # no raise


@pytest.mark.parametrize("bad", ["_x", "Alice", "1abc", "a" * 31, "a_b", ""])
def test_validate_name_rejects(bad):
    with pytest.raises(InvalidNameError):
        paths.validate_name(bad)


def test_list_instance_names_ignores_underscore_dirs(root):
    (root / "data" / "instances" / "alice").mkdir()
    (root / "data" / "instances" / "_template").mkdir()
    (root / "data" / "instances" / "bob").mkdir()
    assert paths.list_instance_names(root) == ["alice", "bob"]


def test_meta_roundtrip(root):
    (root / "data" / "instances" / "alice").mkdir()
    paths.write_meta(root, "alice", {"type": "hermes", "port": 9120})
    assert paths.read_meta(root, "alice")["port"] == 9120


def test_read_port_from_instance_env(root):
    d = root / "data" / "instances" / "alice"
    d.mkdir()
    (d / "instance.env").write_text("CREW_PORT=9123\n")
    assert paths.read_port(root, "alice") == 9123


def test_project_name(root):
    assert paths.project_name("crew", "alice") == "crew-alice"


def test_list_layers(root):
    (root / "data" / "layers" / "knowledge").mkdir(parents=True)
    (root / "data" / "layers" / "brand-voice").mkdir()
    assert paths.list_layers(root) == ["brand-voice", "knowledge"]


def test_list_layers_empty_when_no_dir(root):
    assert paths.list_layers(root) == []


def test_instances_dir(tmp_path):
    from crew.core import paths
    assert paths.instances_dir(tmp_path) == tmp_path / "data" / "instances"


def test_shared_env_path(tmp_path):
    from crew.core import paths
    assert paths.shared_env_path(tmp_path) == tmp_path / "data" / "_shared.env"


def test_gateway_dir(tmp_path):
    from crew.core import paths
    assert paths.gateway_dir(tmp_path) == tmp_path / "data" / "_gateway"


def test_layers_dir(tmp_path):
    from crew.core import paths
    assert paths.layers_dir(tmp_path) == tmp_path / "data" / "layers"


def test_seed_config_path(tmp_path):
    from crew.core import paths
    assert paths.seed_config_path(tmp_path) == tmp_path / "seed" / "config.yaml"


def test_read_meta_corrupt_raises_crewerror(tmp_path):
    from crew.core import paths
    from crew.core.errors import CrewError
    d = tmp_path / "data" / "instances" / "alice"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{ not json")
    with pytest.raises(CrewError):
        paths.read_meta(tmp_path, "alice")


def test_credentials_dir_and_path(tmp_path):
    from crew.core import paths
    assert paths.credentials_dir(tmp_path) == tmp_path / "data" / "credentials"
    assert paths.credential_path(tmp_path, "anthropic") == \
        tmp_path / "data" / "credentials" / "anthropic.env"


def test_find_root_at_cwd(tmp_path):
    from crew.core import paths
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "_shared.env").write_text("CREW_PROJECT=x\n")
    assert paths.find_root(tmp_path) == tmp_path.resolve()


def test_find_root_from_subdir(tmp_path):
    from crew.core import paths
    (tmp_path / "data" / "instances").mkdir(parents=True)
    (tmp_path / "data" / "_shared.env").write_text("CREW_PROJECT=x\n")
    sub = tmp_path / "data" / "instances" / "ted"
    sub.mkdir()
    assert paths.find_root(sub) == tmp_path.resolve()


def test_find_root_none_raises(tmp_path):
    from crew.core import paths
    from crew.core.errors import CrewError
    import pytest
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(CrewError, match="crewdock deployment"):
        paths.find_root(d)
