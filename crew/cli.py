import os
import subprocess
from pathlib import Path
from typing import NoReturn

import typer

from .core import manager
from .core.errors import CrewError

app = typer.Typer(help="Host a crew of isolated AI-assistant agent containers.")


def _root() -> Path:
    """Project root = $CREW_ROOT or the current working directory."""
    return Path(os.environ.get("CREW_ROOT", "."))


def _fail(exc: Exception) -> NoReturn:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command()
def create(
    name: str,
    type: str = typer.Option("hermes", help="agent type (manifest in agents/)"),
    bot_token: str = typer.Option(None, help="messenger bot token"),
    layer: list[str] = typer.Option([], "--layer",
                                    help="read-only data layer to mount (repeatable)"),
):
    """Create and start a new instance."""
    creds: dict[str, str] = {}
    if bot_token:
        creds["TELEGRAM_BOT_TOKEN"] = bot_token
    try:
        inst = manager.create(_root(), name, type=type, creds=creds, layers=layer)
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
    typer.echo(f"{i.name}: {i.state}  type={i.type}  image={i.image}  "
               f"{i.dashboard_url}")


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
def setup(name: str):
    """Run interactive setup (OAuth etc.) for an instance."""
    try:
        manager.setup(_root(), name)
    except CrewError as exc:
        _fail(exc)


@app.command()
def update(
    name: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all", help="update every instance"),
    backup: bool = typer.Option(False, help="snapshot data/ before recreate"),
):
    """Pull the pinned image and recreate (re-reads _shared.env)."""
    root = _root()
    if not all and not name:
        _fail(CrewError("give an instance name or --all"))
    targets = [i.name for i in manager.list(root)] if all else [name]
    failed = []
    for n in targets:
        try:
            manager.update(root, n, backup=backup)
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
