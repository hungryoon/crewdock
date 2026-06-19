from typer.testing import CliRunner

from crew import cli
from crew.core import manager

runner = CliRunner()


def _patch(monkeypatch, root):
    # CLI resolves root from cwd; point it at the temp root
    monkeypatch.setattr(cli, "_root", lambda: root)


def test_list_empty(monkeypatch, root):
    _patch(monkeypatch, root)
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0
    assert "No instances" in result.stdout


def test_create_invokes_manager(monkeypatch, root):
    _patch(monkeypatch, root)
    captured = {}

    def fake_create(r, name, type, creds, layers):
        captured.update(name=name, type=type, creds=creds, layers=layers)
        from crew.core.models import Instance
        return Instance(name=name, type=type, port=9120, image="img",
                        state="running")

    monkeypatch.setattr(manager, "create", fake_create)
    result = runner.invoke(
        cli.app,
        ["create", "alice", "--type", "hermes", "--bot-token", "tok"],
    )
    assert result.exit_code == 0
    assert captured["name"] == "alice"
    assert captured["creds"]["TELEGRAM_BOT_TOKEN"] == "tok"
    assert "alice" in result.stdout
    assert "9120" in result.stdout


def test_create_passes_layers(monkeypatch, root):
    _patch(monkeypatch, root)
    captured = {}

    def fake_create(r, name, type, creds, layers):
        captured["layers"] = layers
        from crew.core.models import Instance
        return Instance(name=name, type=type, port=9120, image="img")

    monkeypatch.setattr(manager, "create", fake_create)
    result = runner.invoke(
        cli.app,
        ["create", "alice", "--bot-token", "t",
         "--layer", "knowledge", "--layer", "brand-voice"],
    )
    assert result.exit_code == 0
    assert captured["layers"] == ["knowledge", "brand-voice"]


def test_layers_command_lists_pool(monkeypatch, root):
    _patch(monkeypatch, root)
    (root / "layers" / "knowledge").mkdir(parents=True)
    result = runner.invoke(cli.app, ["layers"])
    assert result.exit_code == 0
    assert "knowledge" in result.stdout


def test_expose_invokes_core_and_prints_url(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import expose as expose_mod
    monkeypatch.setattr(expose_mod, "expose", lambda r, name: {
        "url": "https://box.ts.net:9120/",
        "redirect_uri": "https://box.ts.net:9120/oauth2/callback",
        "https_port": 9120,
    })
    result = runner.invoke(cli.app, ["expose", "alice"])
    assert result.exit_code == 0
    assert "https://box.ts.net:9120/" in result.stdout
    assert "oauth2/callback" in result.stdout


def test_unexpose_invokes_core(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import expose as expose_mod
    called = []
    monkeypatch.setattr(expose_mod, "unexpose", lambda r, name: called.append(name))
    result = runner.invoke(cli.app, ["unexpose", "alice"])
    assert result.exit_code == 0
    assert called == ["alice"]
