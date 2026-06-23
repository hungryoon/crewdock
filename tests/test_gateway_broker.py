import pytest
from crew.gateway import broker


def test_build_argv_ok():
    assert broker.build_argv("alice", "add", "openai-codex") == [
        "docker", "exec", "-i", "crew-alice",
        "hermes", "auth", "add", "openai-codex", "--no-browser"]


@pytest.mark.parametrize("inst,action,prov", [
    ("../etc", "add", "openai-codex"),
    ("alice;rm", "add", "openai-codex"),
    ("alice", "shell", "openai-codex"),
    ("alice", "add", "evil-provider"),
    ("", "add", "openai-codex"),
])
def test_build_argv_rejects(inst, action, prov):
    with pytest.raises(ValueError):
        broker.build_argv(inst, action, prov)


def test_strip_ansi():
    assert broker.strip_ansi("\x1b[94mhttps://x\x1b[0m") == "https://x"
