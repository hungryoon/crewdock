import re

import pytest

from crew.core import init as init_mod, ids
from crew.core.errors import CrewError, InvalidNameError
from crew.core.creds import parse_env_file
from crew.core.deployment import load_deployment


def test_init_scaffolds_root(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "_prefix_in_use", lambda c: False)
    monkeypatch.setattr(ids, "token", lambda: "3f9a2c")
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt", https_port=8443,
                  router_port=9500, auth_port=9501, local_port=9600)
    for sub in ("instances", "layers", "credentials"):
        assert (root / "data" / sub).is_dir()
    env = parse_env_file(root / "data" / "_shared.env")
    assert env["CREW_PROJECT"] == "synt-3f9a2c"
    assert env["CREW_GATEWAY_HTTPS_PORT"] == "8443"
    assert env["CREW_ROUTER_PORT"] == "9500"
    assert env["CREW_AUTH_PORT"] == "9501"
    assert env["CREW_GATEWAY_LOCAL_PORT"] == "9600"
    assert env["CREW_OAUTH_COOKIE_SECRET"]
    dep = load_deployment(root)
    assert dep.project == "synt-3f9a2c" and dep.https_port == 8443


def test_init_perms(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "_prefix_in_use", lambda c: False)
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt")
    import stat
    assert stat.S_IMODE((root / "data" / "_shared.env").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "data" / "credentials").stat().st_mode) == 0o700


def test_init_refuses_when_already_initialized(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "_prefix_in_use", lambda c: False)
    root = tmp_path / "deploy"
    init_mod.init(root, project="synt")
    with pytest.raises(CrewError, match="already initialized"):
        init_mod.init(root, project="synt2")


def test_init_validates_project_name(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "_prefix_in_use", lambda c: False)
    with pytest.raises(InvalidNameError):
        init_mod.init(tmp_path / "deploy", project="Bad_Name")


def test_init_assigns_unique_suffix(tmp_path, monkeypatch):
    from crew.core import init as init_mod
    from crew.core.creds import parse_env_file
    monkeypatch.setattr(init_mod, "_prefix_in_use", lambda c: False)
    init_mod.init(tmp_path, project="synt")
    proj = parse_env_file(tmp_path / "data" / "_shared.env")["CREW_PROJECT"]
    assert re.fullmatch(r"synt-[0-9a-f]{6}", proj), proj


def test_init_rerolls_when_prefix_taken(tmp_path, monkeypatch):
    from crew.core import init as init_mod, ids
    from crew.core.creds import parse_env_file
    seq = iter(["aaaaaa", "bbbbbb"])
    monkeypatch.setattr(ids, "token", lambda: next(seq))
    monkeypatch.setattr(init_mod, "_prefix_in_use", lambda c: c == "synt-aaaaaa")
    init_mod.init(tmp_path, project="synt")
    proj = parse_env_file(tmp_path / "data" / "_shared.env")["CREW_PROJECT"]
    assert proj == "synt-bbbbbb"


def test_init_rejects_too_long_label(tmp_path, monkeypatch):
    from crew.core import init as init_mod
    from crew.core.errors import CrewError
    import pytest
    monkeypatch.setattr(init_mod, "_prefix_in_use", lambda c: False)
    with pytest.raises(CrewError, match="too long"):
        init_mod.init(tmp_path, project="a" * 24)
