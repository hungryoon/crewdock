import pytest

from crew.core.deployment import Deployment, load_deployment
from crew.core.errors import NotInitializedError, CrewError, InvalidNameError


def _shared(root, body):
    (root / "instances").mkdir(parents=True, exist_ok=True)
    (root / "instances" / "_shared.env").write_text(body)


def test_load_defaults_ports(tmp_path):
    _shared(tmp_path, "CREW_PROJECT=synt\n")
    dep = load_deployment(tmp_path)
    assert dep.project == "synt"
    assert (dep.https_port, dep.router_port, dep.auth_port) == (443, 9400, 9401)


def test_load_reads_custom_ports(tmp_path):
    _shared(tmp_path,
        "CREW_PROJECT=smoke\nCREW_GATEWAY_HTTPS_PORT=8443\n"
        "CREW_ROUTER_PORT=9500\nCREW_AUTH_PORT=9501\n")
    dep = load_deployment(tmp_path)
    assert (dep.project, dep.https_port, dep.router_port, dep.auth_port) \
        == ("smoke", 8443, 9500, 9501)


def test_missing_project_raises_not_initialized(tmp_path):
    _shared(tmp_path, "CREW_GOOGLE_CLIENT_ID=x\n")
    with pytest.raises(NotInitializedError, match="crew init"):
        load_deployment(tmp_path)


def test_no_shared_env_raises_not_initialized(tmp_path):
    (tmp_path / "instances").mkdir()
    with pytest.raises(NotInitializedError):
        load_deployment(tmp_path)


def test_bad_project_name_rejected(tmp_path):
    _shared(tmp_path, "CREW_PROJECT=Bad_Name\n")
    with pytest.raises(InvalidNameError):
        load_deployment(tmp_path)


def test_non_integer_port_raises(tmp_path):
    _shared(tmp_path, "CREW_PROJECT=synt\nCREW_ROUTER_PORT=abc\n")
    with pytest.raises(CrewError):
        load_deployment(tmp_path)


def test_derived_names():
    dep = Deployment(project="synt", https_port=443, router_port=9400, auth_port=9401)
    assert dep.router_container() == "synt-gateway-router"
    assert dep.auth_container() == "synt-gateway-auth"
    assert dep.broker_container() == "synt-gateway-broker"
    assert dep.router_image() == "synt-gateway-router:local"
    assert dep.broker_image() == "synt-gateway-broker:local"
    assert dep.instance_project("alice") == "synt-alice"


def test_two_projects_have_distinct_names():
    a = Deployment(project="synt", https_port=443, router_port=9400, auth_port=9401)
    b = Deployment(project="smoke", https_port=8443, router_port=9500, auth_port=9501)
    assert a.router_container() != b.router_container()
    assert a.instance_project("alice") != b.instance_project("alice")
    assert a.instance_project("alice") == "synt-alice"
    assert b.instance_project("alice") == "smoke-alice"
