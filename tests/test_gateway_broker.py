import pytest
from crew.gateway import broker


def test_require_secret_configured_raises_without_secret(monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", None)
    with pytest.raises(SystemExit):
        broker._require_secret_configured()


def test_require_secret_configured_ok_with_secret(monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", "x")
    broker._require_secret_configured()  # no raise


def test_build_argv_default_project():
    assert broker.build_argv("alice", "add", "openai-codex") == [
        "docker", "exec", "-i", "crew-alice",
        "hermes", "auth", "add", "openai-codex", "--no-browser"]


def test_build_argv_namespaced_project():
    assert broker.build_argv("alice", "add", "openai-codex", project="synt") == [
        "docker", "exec", "-i", "synt-alice",
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


async def test_exec_streams_lines_and_done(aiohttp_client, monkeypatch):
    # benign command instead of docker exec
    monkeypatch.setattr(broker, "build_argv",
        lambda i, a, p: ["sh", "-c", "printf 'l1\\nl2\\n'; exit 0"])
    monkeypatch.setattr(broker, "_SECRET", None)
    client = await aiohttp_client(broker.build_app())
    ws = await client.ws_connect("/exec?instance=alice&provider=openai-codex")
    lines, done = [], None
    async for msg in ws:
        d = msg.json()
        if d.get("done"):
            done = d
            break
        lines.append(d["line"])
    assert lines == ["l1", "l2"]
    assert done["code"] == 0


async def test_exec_rejects_bad_secret(aiohttp_client, monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", "S")
    client = await aiohttp_client(broker.build_app())
    resp = await client.get("/exec?instance=alice&provider=openai-codex")  # no secret hdr
    assert resp.status == 403


async def test_exec_rejects_bad_provider(aiohttp_client, monkeypatch):
    monkeypatch.setattr(broker, "_SECRET", None)
    client = await aiohttp_client(broker.build_app())
    ws = await client.ws_connect("/exec?instance=alice&provider=nope")
    seen = [msg.json() async for msg in ws]
    assert any(d.get("done") and d["code"] == 2 for d in seen)
    assert any("invalid provider" in d.get("line", "") for d in seen)
