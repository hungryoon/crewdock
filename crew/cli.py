import os
import subprocess
from pathlib import Path
from typing import NoReturn

import typer

from .core import manager
from .core import gateway as gateway_mod
from .core import credentials as credentials_mod
from .core import init as init_mod
from .core.errors import CrewError

app = typer.Typer(help="Host a crew of isolated AI-assistant agent containers.")


def _root() -> Path:
    """Project root = $CREW_ROOT or the current working directory."""
    return Path(os.environ.get("CREW_ROOT", "."))


def _fail(exc: Exception) -> NoReturn:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command()
def init(
    project: str = typer.Argument(None, help="Deployment / project name."),
    https_port: int = typer.Option(443, "--https-port"),
    router_port: int = typer.Option(9400, "--router-port"),
    auth_port: int = typer.Option(9401, "--auth-port"),
):
    """Initialize CREW_ROOT as a new deployment (one-time setup)."""
    if not project:
        project = typer.prompt("project name")
    try:
        init_mod.init(_root(), project=project, https_port=https_port,
                      router_port=router_port, auth_port=auth_port)
    except CrewError as exc:
        _fail(exc)
    typer.echo(f"initialized deployment '{project}' at {_root()}")
    typer.echo("  next: set CREW_GOOGLE_CLIENT_ID/SECRET in "
               "instances/_shared.env, then `crew create` + `crew gateway up`")


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
    typer.echo(f"created {inst.name} ({inst.type}) -> {inst.dashboard_url} "
               f"[port {inst.port}]")


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


@gateway_app.command("up")
def gateway_up():
    """Start the login gateway (one URL for all published instances)."""
    try:
        info = gateway_mod.gateway_up(_root())
    except CrewError as exc:
        _fail(exc)
    typer.echo(f"gateway up -> {info['url']}")
    typer.echo("  add this redirect URI to your Google OAuth client (once):")
    typer.echo(f"    {info['redirect_uri']}")


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


@app.command(name="list")
def list_():
    """List instances."""
    instances = manager.list(_root())
    if not instances:
        typer.echo("No instances.")
        return
    for i in instances:
        typer.echo(f"{i.name:20} {i.type:10} {i.state:9} {i.dashboard_url}")


@app.command()
def status(name: str):
    """Show one instance's status."""
    try:
        i = manager.status(_root(), name)
    except CrewError as exc:
        _fail(exc)
    line = (f"{i.name}: {i.state}  type={i.type}  image={i.image}  "
            f"tz={i.timezone}  {i.dashboard_url}")
    if i.previous_image:
        line += f"\n  rollback available: {i.previous_image}"
    typer.echo(line)


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
