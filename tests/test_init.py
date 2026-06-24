import pytest

from crew.core import init as init_mod
from crew.core.errors import CrewError, InvalidNameError
from crew.core.creds import parse_env_file
from crew.core.deployment import load_deployment


def test_init_scaffolds_root(tmp_path):
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt", https_port=8443,
                  router_port=9500, auth_port=9501, local_port=9600)
    for sub in ("instances", "layers", "credentials"):
        assert (root / "data" / sub).is_dir()
    env = parse_env_file(root / "data" / "_shared.env")
    assert env["CREW_PROJECT"] == "synt"
    assert env["CREW_GATEWAY_HTTPS_PORT"] == "8443"
    assert env["CREW_ROUTER_PORT"] == "9500"
    assert env["CREW_AUTH_PORT"] == "9501"
    assert env["CREW_GATEWAY_LOCAL_PORT"] == "9600"
    assert env["CREW_OAUTH_COOKIE_SECRET"]
    dep = load_deployment(root)
    assert dep.project == "synt" and dep.https_port == 8443


def test_init_perms(tmp_path):
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt")
    import stat
    assert stat.S_IMODE((root / "data" / "_shared.env").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "data" / "credentials").stat().st_mode) == 0o700


def test_init_refuses_when_already_initialized(tmp_path):
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt")
    with pytest.raises(CrewError, match="already initialized"):
        init_mod.init(root, project="synt2")


def test_init_validates_project_name(tmp_path):
    with pytest.raises(InvalidNameError):
        init_mod.init(tmp_path / "deploy", project="Bad_Name")
