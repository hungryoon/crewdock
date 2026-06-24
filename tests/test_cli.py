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

    def fake_create(r, name, type, creds, layers, credentials, tz=None):
        captured.update(name=name, type=type, creds=creds, layers=layers)
        from crew.core.models import Instance
        return Instance(name=name, type=type, port=9120, image="img",
                        state="running")

    monkeypatch.setattr(manager, "create", fake_create)
    result = runner.invoke(
        cli.app,
        ["create", "alice", "--type", "hermes"],
    )
    assert result.exit_code == 0
    assert captured["name"] == "alice"
    assert "alice" in result.stdout
    assert "9120" in result.stdout


def test_create_passes_layers(monkeypatch, root):
    _patch(monkeypatch, root)
    captured = {}

    def fake_create(r, name, type, creds, layers, credentials, tz=None):
        captured["layers"] = layers
        from crew.core.models import Instance
        return Instance(name=name, type=type, port=9120, image="img")

    monkeypatch.setattr(manager, "create", fake_create)
    result = runner.invoke(
        cli.app,
        ["create", "alice",
         "--layer", "knowledge", "--layer", "brand-voice"],
    )
    assert result.exit_code == 0
    assert captured["layers"] == ["knowledge", "brand-voice"]


def test_layers_command_lists_pool(monkeypatch, root):
    _patch(monkeypatch, root)
    (root / "data" / "layers" / "knowledge").mkdir(parents=True)
    result = runner.invoke(cli.app, ["layers"])
    assert result.exit_code == 0
    assert "knowledge" in result.stdout


def test_gateway_up_invokes_core(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import gateway
    monkeypatch.setattr(gateway, "gateway_up", lambda r: {
        "url": "https://h.ts.net/",
        "redirect_uri": "https://h.ts.net/oauth2/callback",
        "local_url": "http://127.0.0.1:9402/",
        "no_whitelist": False})
    result = runner.invoke(cli.app, ["gateway", "up"])
    assert result.exit_code == 0
    assert "https://h.ts.net/" in result.stdout
    assert "oauth2/callback" in result.stdout
    assert "127.0.0.1:9402" in result.stdout
    assert "CREW_ALLOWED_EMAILS" not in result.stdout


def test_gateway_up_warns_without_whitelist(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import gateway
    monkeypatch.setattr(gateway, "gateway_up", lambda r: {
        "url": "https://h.ts.net/",
        "redirect_uri": "https://h.ts.net/oauth2/callback",
        "local_url": "http://127.0.0.1:9402/",
        "no_whitelist": True})
    result = runner.invoke(cli.app, ["gateway", "up"])
    assert result.exit_code == 0
    assert "CREW_ALLOWED_EMAILS" in result.stdout
    assert "팀 뷰" in result.stdout


def test_gateway_open_invokes_browser(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import gateway
    monkeypatch.setattr(gateway, "local_view_url", lambda r: "http://127.0.0.1:9402/")
    opened = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    result = runner.invoke(cli.app, ["gateway", "open"])
    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:9402/"]


def test_gateway_down_invokes_core(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import gateway
    called = []
    monkeypatch.setattr(gateway, "gateway_down", lambda r: called.append(True))
    result = runner.invoke(cli.app, ["gateway", "down"])
    assert result.exit_code == 0
    assert called == [True]


def test_gateway_reload_invokes_core(monkeypatch, root):
    _patch(monkeypatch, root)
    from crew.core import gateway
    called = []
    monkeypatch.setattr(gateway, "gateway_reload", lambda r: called.append(True))
    result = runner.invoke(cli.app, ["gateway", "reload"])
    assert result.exit_code == 0
    assert called == [True]


def test_create_passes_credentials(monkeypatch, root):
    _patch(monkeypatch, root)
    captured = {}

    def fake_create(r, name, type, creds, layers, credentials, tz=None):
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
    (root / "data" / "credentials").mkdir(parents=True)
    (root / "data" / "credentials" / "anthropic.env").write_text(
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
                    rollback=False, to_default=False, tz=None):
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
    assert "rollback" in result.stdout
    assert "img:latest" in result.stdout


def test_cli_create_timezone_forwarded(monkeypatch, tmp_path):
    from crew import cli
    from crew.core.models import Instance
    captured = {}
    def fake_create(root, name, type, creds, layers=None, credentials=None, tz=None):
        captured["tz"] = tz
        return Instance(name=name, type=type, port=9120, image="x")
    monkeypatch.setattr(cli.manager, "create", fake_create)
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)
    result = runner.invoke(cli.app, ["create", "alice", "--timezone", "UTC"])
    assert result.exit_code == 0
    assert captured["tz"] == "UTC"


def test_cli_update_timezone_forwarded(monkeypatch, tmp_path):
    from crew import cli
    captured = {}
    def fake_update(root, name, backup=False, image=None, rollback=False,
                    to_default=False, tz=None):
        captured["tz"] = tz
    monkeypatch.setattr(cli.manager, "update", fake_update)
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)
    result = runner.invoke(cli.app, ["update", "alice", "--tz", "UTC"])
    assert result.exit_code == 0
    assert captured["tz"] == "UTC"


def test_cli_status_shows_timezone(monkeypatch, tmp_path):
    from crew import cli
    from crew.core.models import Instance
    inst = Instance(name="alice", type="hermes", port=9120, image="img",
                    timezone="Asia/Seoul", state="running")
    monkeypatch.setattr(cli.manager, "status", lambda root, name: inst)
    monkeypatch.setattr(cli, "_root", lambda: tmp_path)
    result = runner.invoke(cli.app, ["status", "alice"])
    assert result.exit_code == 0
    assert "Asia/Seoul" in result.stdout


def test_root_walks_up_and_fails_cleanly(monkeypatch, tmp_path):
    # _root() must exit cleanly (nonzero) — not traceback — when no deployment found
    monkeypatch.setattr(cli, "_here", lambda: tmp_path)  # empty dir, no deployment
    # a command that calls _root without its own try/except is the real test:
    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code != 0
    assert "crewdock deployment" in result.stdout or "crewdock deployment" in str(result.output)


def test_init_invokes_core(monkeypatch, root):
    monkeypatch.setattr(cli, "_here", lambda: root)
    from crew.core import init as init_mod
    captured = {}
    def fake_init(r, project, https_port=443, router_port=9400, auth_port=9401,
                  local_port=9402):
        captured.update(project=project, https_port=https_port)
        return "synt-3f9a2c"
    monkeypatch.setattr(init_mod, "init", fake_init)
    result = runner.invoke(cli.app, ["init", "synt", "--https-port", "8443"])
    assert result.exit_code == 0
    assert captured == {"project": "synt", "https_port": 8443}
    assert "synt-3f9a2c" in result.stdout
