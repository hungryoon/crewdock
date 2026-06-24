import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from .core import manager
from .core import gateway as gateway_mod
from .core import credentials as credentials_mod
from .core import init as init_mod
from .core import paths
from .core.errors import CrewError

app = typer.Typer(help="Host a crew of isolated AI-assistant agent containers.")

# Wide width so long dashboard URLs are never truncated in non-tty capture.
_console = Console(width=120)


def _here() -> Path:
    return Path.cwd()


def _root() -> Path:
    """Deployment root: nearest ancestor of cwd with data/_shared.env."""
    try:
        return paths.find_root(_here())
    except CrewError as exc:
        _fail(exc)


def _ok(msg: str) -> None:
    """Print a green check success line."""
    _console.print(f"[green]✓[/green] {msg}")


def _kv(key: str, value: str, width: int = 11) -> None:
    """Print a dim-key / value detail line indented under a header."""
    _console.print(f"  [dim]{key:<{width}}[/dim] {value}")


def _state_style(state: str) -> str:
    """rich style name for an instance state."""
    if state == "running":
        return "green"
    if state == "stopped":
        return "yellow"
    return "red"


def _fail(exc: Exception) -> NoReturn:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command()
def init(
    project: str = typer.Argument(None, help="Deployment / project name."),
    https_port: int = typer.Option(443, "--https-port"),
    router_port: int = typer.Option(9400, "--router-port"),
    auth_port: int = typer.Option(9401, "--auth-port"),
    local_port: int = typer.Option(9402, "--local-port"),
):
    """Initialize the current directory as a new deployment (one-time setup)."""
    if not project:
        project = typer.prompt("project name")
    here = _here()
    try:
        project = init_mod.init(here, project=project, https_port=https_port,
                                router_port=router_port, auth_port=auth_port,
                                local_port=local_port)
    except CrewError as exc:
        _fail(exc)
    _ok(f"initialized deployment [bold]{project}[/bold]")
    _kv("root", f"[cyan]{here}[/cyan]")
    _kv("gateway", f":{https_port} team · :{local_port} local")
    _console.print()
    _console.print("next")
    _console.print("  [dim]1[/dim]  set CREW_GOOGLE_CLIENT_ID / "
                   "CREW_GOOGLE_CLIENT_SECRET in [cyan]data/_shared.env[/cyan]")
    _console.print("  [dim]2[/dim]  [cyan]crew create <name>[/cyan]")
    _console.print("  [dim]3[/dim]  [cyan]crew gateway up[/cyan]")


@app.command()
def create(
    name: str,
    type: str = typer.Option("hermes", help="agent type (manifest in agents/)"),
    layer: list[str] = typer.Option([], "--layer",
                                    help="read-only data layer to mount (repeatable)"),
    credential: list[str] = typer.Option([], "--credential",
                                         help="credential bundle to inject (repeatable)"),
    timezone: str = typer.Option("Asia/Seoul", "--timezone", "--tz",
                                 help="container timezone (IANA zone, e.g. Asia/Seoul); default KST"),
):
    """Create and start a new instance."""
    creds: dict[str, str] = {}
    try:
        inst = manager.create(_root(), name, type=type, creds=creds,
                              layers=layer, credentials=credential, tz=timezone)
    except CrewError as exc:
        _fail(exc)
    _ok(f"created [bold]{inst.name}[/bold]  [dim]({inst.type})[/dim]")
    _kv("dashboard", f"[cyan]{inst.dashboard_url}[/cyan]")
    _kv("port", str(inst.port))


@app.command()
def rm(name: str, purge: bool = typer.Option(False, help="also delete data/")):
    """Remove an instance (keeps data unless --purge)."""
    if purge and not typer.confirm(f"delete ALL data for {name}?"):
        raise typer.Abort()
    try:
        manager.remove(_root(), name, purge=purge)
    except CrewError as exc:
        _fail(exc)
    typer.echo(f"removed {name}" + (" (purged)" if purge else " (data kept)"))


gateway_app = typer.Typer(help="Single login gateway for all instance dashboards.")
app.add_typer(gateway_app, name="gateway")


def _interactive() -> bool:
    return sys.stdin.isatty()


def _resolve_https_conflict(root: Path) -> None:
    """If the configured tailnet HTTPS port is already served, prompt the
    operator to take it over, switch ports, or cancel. Non-interactive callers
    get an actionable error instead."""
    while gateway_mod.https_port_served(root):
        port = gateway_mod.https_port(root)
        if not _interactive():
            _fail(CrewError(
                f"tailnet HTTPS port {port} is already served — `crew gateway down` "
                f"first, set CREW_GATEWAY_HTTPS_PORT in data/_shared.env, or run "
                f"`crew gateway up` interactively to choose"))
        choice = typer.prompt(
            f"port {port} is already served on the tailnet (may be another service)\n"
            f"  [1] take it over  [2] use a different port  [3] cancel\nchoose",
            default="1")
        if choice == "1":
            gateway_mod.free_https_port(root)
            if gateway_mod.https_port_served(root):
                _fail(CrewError(
                    f"couldn't free port {port} — run `tailscale serve reset` then retry"))
            return
        elif choice == "2":
            newport = int(typer.prompt("new HTTPS port"))
            gateway_mod.set_https_port(root, newport)
        else:
            raise typer.Abort()


@gateway_app.command("up")
def gateway_up():
    """Start the login gateway (one URL for all published instances)."""
    root = _root()
    try:
        _resolve_https_conflict(root)
        info = gateway_mod.gateway_up(root)
    except CrewError as exc:
        _fail(exc)
    _ok("gateway up")
    _kv("team", f"[cyan]{info['url']}[/cyan]  [dim](Google SSO)[/dim]", width=6)
    _kv("local", f"[cyan]{info['local_url']}[/cyan]  [dim](all instances)[/dim]", width=6)
    _console.print()
    _console.print("register this redirect URI in your Google OAuth client (once):")
    _console.print(f"  [cyan]{info['redirect_uri']}[/cyan]")
    if info.get("no_whitelist"):
        _console.print(
            "[yellow]⚠ 아직 허용된 이메일이 없습니다 — 팀 뷰(SSO)는 아무도 들이지 않습니다.[/yellow]\n"
            "  data/instances/<name>/instance.env 에 CREW_ALLOWED_EMAILS 설정 후 "
            "`crew gateway reload`. (로컬 뷰는 지금 사용 가능)")


@gateway_app.command("down")
def gateway_down():
    """Stop the login gateway."""
    try:
        gateway_mod.gateway_down(_root())
    except CrewError as exc:
        _fail(exc)
    typer.echo("gateway down")


@gateway_app.command("reload")
def gateway_reload():
    """Refresh the gateway allowlist after editing CREW_ALLOWED_EMAILS."""
    try:
        gateway_mod.gateway_reload(_root())
    except CrewError as exc:
        _fail(exc)
    typer.echo("gateway allowlist reloaded")


@gateway_app.command("open")
def gateway_open():
    """Open the gateway's local view (all instances) in your browser."""
    try:
        url = gateway_mod.local_view_url(_root())
    except CrewError as exc:
        _fail(exc)
    import webbrowser
    webbrowser.open(url)
    typer.echo(f"opening {url}")


@app.command(name="list")
def list_():
    """List instances."""
    instances = manager.list(_root())
    if not instances:
        _console.print("[dim]No instances.[/dim]")
        return
    table = Table(box=box.SIMPLE)
    table.add_column("NAME")
    table.add_column("TYPE")
    table.add_column("STATE")
    table.add_column("DASHBOARD", overflow="fold")
    for i in instances:
        table.add_row(
            i.name, i.type,
            f"[{_state_style(i.state)}]{i.state}[/{_state_style(i.state)}]",
            i.dashboard_url,
        )
    _console.print(table)


@app.command()
def status(name: str):
    """Show one instance's status."""
    try:
        i = manager.status(_root(), name)
    except CrewError as exc:
        _fail(exc)
    style = _state_style(i.state)
    _console.print(f"[bold]{i.name}[/bold]  [{style}]●[/{style}] {i.state}")
    _kv("type", i.type)
    _kv("image", i.image)
    _kv("timezone", i.timezone)
    _kv("dashboard", f"[cyan]{i.dashboard_url}[/cyan]")
    if i.previous_image:
        _kv("rollback", i.previous_image)


@app.command()
def logs(name: str, follow: bool = typer.Option(False, "-f", "--follow")):
    """Stream an instance's logs."""
    try:
        manager.logs(_root(), name, follow=follow)
    except CrewError as exc:
        _fail(exc)


@app.command()
def start(name: str):
    """Start a stopped instance."""
    _lifecycle(name, "start")


@app.command()
def stop(name: str):
    """Stop a running instance."""
    _lifecycle(name, "stop")


@app.command()
def restart(name: str):
    """Restart an instance."""
    _lifecycle(name, "restart")


def _lifecycle(name: str, action: str):
    try:
        manager.lifecycle(_root(), name, action)
    except CrewError as exc:
        _fail(exc)
    typer.echo(f"{action} {name}")


@app.command()
def update(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="update every instance"),
    backup: bool = typer.Option(False, help="snapshot data/ before recreate"),
    image: str = typer.Option(None, "--image",
                              help="repin this instance to an image ref (tag or @sha256:...)"),
    rollback: bool = typer.Option(False, "--rollback",
                                  help="roll back to the previous image pin"),
    to_default: bool = typer.Option(False, "--to-default",
                                    help="repin to the manifest's default image"),
    timezone: str = typer.Option(None, "--timezone", "--tz",
                                 help="change the instance timezone (IANA zone)"),
):
    """Pull the instance's image and recreate (re-reads _shared.env).

    Bare: refresh config, keep the version. --image/--rollback/--to-default
    change the pin (mutually exclusive)."""
    root = _root()
    if not all and not name:
        _fail(CrewError("give an instance name or --all"))
    targets = [i.name for i in manager.list(root)] if all else [name]
    failed = []
    for n in targets:
        try:
            manager.update(root, n, backup=backup, image=image,
                           rollback=rollback, to_default=to_default, tz=timezone)
            typer.echo(f"updated {n}")
        except CrewError as exc:
            typer.secho(f"error updating {n}: {exc}", fg=typer.colors.RED, err=True)
            failed.append(n)
    if failed:
        raise typer.Exit(1)


@app.command()
def shell(name: str):
    """Open a shell inside an instance container."""
    try:
        argv = manager.shell_argv(_root(), name)
    except CrewError as exc:
        _fail(exc)
    subprocess.run(argv, check=False)


@app.command()
def layers():
    """List available read-only data layers in the pool."""
    from .core import paths
    names = paths.list_layers(_root())
    if not names:
        typer.echo("No layers.")
        return
    for n in names:
        typer.echo(n)


@app.command()
def credentials():
    """List credential bundles in the pool (key names only — never values)."""
    names = credentials_mod.list_credentials(_root())
    if not names:
        typer.echo("No credentials.")
        return
    for name in names:
        keys = credentials_mod.credential_keys(_root(), [name])
        typer.echo(f"{name:20} {', '.join(keys) or '(empty)'}")
