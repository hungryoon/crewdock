import pytest

from crew.core.errors import InvalidNameError
from crew.core import paths


def test_validate_name_accepts_kebab(root):
    paths.validate_name("alice-1")  # no raise


@pytest.mark.parametrize("bad", ["_x", "Alice", "1abc", "a" * 31, "a_b", ""])
def test_validate_name_rejects(bad):
    with pytest.raises(InvalidNameError):
        paths.validate_name(bad)


def test_list_instance_names_ignores_underscore_dirs(root):
    (root / "instances" / "alice").mkdir()
    (root / "instances" / "_template").mkdir()
    (root / "instances" / "bob").mkdir()
    assert paths.list_instance_names(root) == ["alice", "bob"]


def test_meta_roundtrip(root):
    (root / "instances" / "alice").mkdir()
    paths.write_meta(root, "alice", {"type": "hermes", "port": 9120})
    assert paths.read_meta(root, "alice")["port"] == 9120


def test_read_port_from_instance_env(root):
    d = root / "instances" / "alice"
    d.mkdir()
    (d / "instance.env").write_text("CREW_PORT=9123\n")
    assert paths.read_port(root, "alice") == 9123


def test_project_name(root):
    assert paths.project_name("alice") == "crew-alice"


def test_list_layers(root):
    (root / "layers" / "knowledge").mkdir(parents=True)
    (root / "layers" / "brand-voice").mkdir()
    assert paths.list_layers(root) == ["brand-voice", "knowledge"]


def test_list_layers_empty_when_no_dir(root):
    assert paths.list_layers(root) == []
