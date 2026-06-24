import pytest

from crew.core import init as init_mod
from crew.core.errors import CrewError, InvalidNameError
from crew.core.creds import parse_env_file
from crew.core.deployment import load_deployment


def _fake_repo(tmp_path):
    """Minimal source repo: agents/hermes.yaml + instances/_template/."""
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "hermes.yaml").write_text("type: hermes\n")
    (repo / "instances" / "_template").mkdir(parents=True)
    (repo / "instances" / "_template" / "config.yaml").write_text("seed: 1\n")
    return repo


def test_init_scaffolds_root(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(init_mod, "_repo_root", lambda: str(repo))
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt", https_port=8443,
                  router_port=9500, auth_port=9501, local_port=9600)
    for sub in ("instances", "agents", "layers", "credentials"):
        assert (root / sub).is_dir()
    assert (root / "agents" / "hermes.yaml").exists()
    assert (root / "instances" / "_template" / "config.yaml").exists()
    env = parse_env_file(root / "instances" / "_shared.env")
    assert env["CREW_PROJECT"] == "synt"
    assert env["CREW_GATEWAY_HTTPS_PORT"] == "8443"
    assert env["CREW_ROUTER_PORT"] == "9500"
    assert env["CREW_AUTH_PORT"] == "9501"
    assert env["CREW_GATEWAY_LOCAL_PORT"] == "9600"
    assert env["CREW_OAUTH_COOKIE_SECRET"]
    dep = load_deployment(root)
    assert dep.project == "synt" and dep.https_port == 8443


def test_init_perms(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(init_mod, "_repo_root", lambda: str(repo))
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt")
    import stat
    assert stat.S_IMODE((root / "instances" / "_shared.env").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "credentials").stat().st_mode) == 0o700


def test_init_refuses_when_already_initialized(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(init_mod, "_repo_root", lambda: str(repo))
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt")
    with pytest.raises(CrewError, match="already initialized"):
        init_mod.init(root, project="synt2")


def test_init_refuses_root_equal_repo(tmp_path, monkeypatch):
    # When CREW_ROOT resolves to the source checkout itself, init must error
    # clearly (not crash copying files onto themselves).
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(init_mod, "_repo_root", lambda: str(repo))
    with pytest.raises(CrewError, match="separate"):
        init_mod.init(repo, project="synt")


def test_init_validates_project_name(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(init_mod, "_repo_root", lambda: str(repo))
    with pytest.raises(InvalidNameError):
        init_mod.init(tmp_path / "deploy", project="Bad_Name")
