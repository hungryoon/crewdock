from crew.core import gateway


def test_router_image_and_build_argv():
    assert gateway.ROUTER_IMAGE == "crewdock-gateway-router:local"
    argv = gateway.router_build_argv("/repo")
    assert argv[:2] == ["docker", "build"]
    assert "-t" in argv and gateway.ROUTER_IMAGE in argv
    assert "-f" in argv
    assert argv[-1] == "/repo"


def test_router_run_argv():
    argv = gateway.router_run_argv(root_abs="/abs/root", router_port=9400)
    assert argv[:7] == ["docker", "run", "-d", "--pull", "never",
                        "--name", "crew-gateway-router"]
    assert "--network" in argv and "host" in argv
    assert any(a == "/abs/root/instances:/crew/instances:ro" for a in argv)
    assert "CREW_ROUTER_PORT=9400" in argv
    assert "CREW_ROOT=/crew" in argv
    assert argv[-1] == gateway.ROUTER_IMAGE
