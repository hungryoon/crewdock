from crew.core.models import Instance


def test_instance_dashboard_url_built_from_host_and_port():
    inst = Instance(name="alice", type="hermes", port=9120,
                    image="nousresearch/hermes-agent:latest")
    assert inst.dashboard_url == "http://127.0.0.1:9120/"


def test_instance_defaults_to_unknown_state():
    inst = Instance(name="bob", type="hermes", port=9121, image="img")
    assert inst.state == "unknown"
    assert inst.health == "unknown"
