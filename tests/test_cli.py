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

    def fake_create(r, name, type, creds, layers, credentials):
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

    def fake_create(r, name, type, creds, layers, credentials):
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


def test_gateway_up_invokes_core(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import gateway
    monkeypatch.setattr(gateway, "gateway_up", lambda r: {
        "url": "https://h.ts.net/",
        "redirect_uri": "https://h.ts.net/oauth2/callback"})
    result = runner.invoke(cli.app, ["gateway", "up"])
    assert result.exit_code == 0
    assert "https://h.ts.net/" in result.stdout
    assert "oauth2/callback" in result.stdout


def test_gateway_down_invokes_core(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import gateway
    called = []
    monkeypatch.setattr(gateway, "gateway_down", lambda r: called.append(True))
    result = runner.invoke(cli.app, ["gateway", "down"])
    assert result.exit_code == 0
    assert called == [True]


def test_expose_marks_publish(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import expose as expose_mod
    called = []
    monkeypatch.setattr(expose_mod, "expose", lambda r, name: called.append(name))
    result = runner.invoke(cli.app, ["expose", "alice"])
    assert result.exit_code == 0
    assert called == ["alice"]


def test_create_passes_credentials(monkeypatch, root):
    _patch(monkeypatch, root)
    captured = {}

    def fake_create(r, name, type, creds, layers, credentials):
        captured.update(credentials=credentials)
        from crew.core.models import Instance
        return Instance(name=name, type=type, port=9120, image="img",
                        state="running")

    monkeypatch.setattr(manager, "create", fake_create)
    result = runner.invoke(
        cli.app,
        ["create", "alice", "--credential", "anthropic", "--credential", "openai"],
    )
    assert result.exit_code == 0
    assert captured["credentials"] == ["anthropic", "openai"]


def test_credentials_command_lists_names_and_keys(monkeypatch, root):
    _patch(monkeypatch, root)
    (root / "credentials").mkdir()
    (root / "credentials" / "anthropic.env").write_text(
        "ANTHROPIC_API_KEY=secret\nANTHROPIC_BASE=x\n")
    result = runner.invoke(cli.app, ["credentials"])
    assert result.exit_code == 0
    assert "anthropic" in result.stdout
    assert "ANTHROPIC_API_KEY" in result.stdout
    assert "secret" not in result.stdout


def test_cli_update_image_calls_manager(monkeypatch, tmp_path):
    from crew import cli
    captured = {}

    def fake_update(root, name, backup=False, image=None,
                    rollback=False, to_default=False):
        captured.update(name=name, image=image, rollback=rollback,
                        to_default=to_default)

    monkeypatch.setattr(cli.manager, "update", fake_update)
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)
    result = runner.invoke(
        cli.app, ["update", "alice", "--image",
                  "nousresearch/hermes-agent@sha256:x"])
    assert result.exit_code == 0
    assert captured["image"] == "nousresearch/hermes-agent@sha256:x"
    assert captured["rollback"] is False


def test_cli_status_shows_rollback_available(monkeypatch, tmp_path):
    from crew import cli
    from crew.core.models import Instance
    inst = Instance(name="alice", type="hermes", port=9120,
                    image="img@sha256:new", previous_image="img:latest",
                    state="running")
    monkeypatch.setattr(cli.manager, "status", lambda root, name: inst)
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)
    result = runner.invoke(cli.app, ["status", "alice"])
    assert result.exit_code == 0
    assert "rollback available: img:latest" in result.stdout
