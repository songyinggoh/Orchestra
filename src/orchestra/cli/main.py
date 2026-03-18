"""Orchestra CLI.

Usage:
    orchestra version            Show version
    orchestra init my-project    Scaffold a new project
    orchestra run workflow.py    Run a workflow file
"""

from __future__ import annotations

import typer
from rich.console import Console

from orchestra import __version__

app = typer.Typer(
    name="orchestra",
    help="Orchestra: Python-first multi-agent orchestration framework",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Show Orchestra version."""
    console.print(f"Orchestra v{__version__}")


@app.command()
def init(
    project_name: str = typer.Argument(..., help="Name of the project to create"),
    directory: str = typer.Option(".", help="Directory to create project in"),
) -> None:
    """Initialize a new Orchestra project with scaffolding."""
    from pathlib import Path

    project_dir = Path(directory) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / "agents").mkdir(exist_ok=True)
    (project_dir / "tools").mkdir(exist_ok=True)
    (project_dir / "workflows").mkdir(exist_ok=True)

    workflow_file = project_dir / "workflows" / "hello.py"
    workflow_file.write_text(
        '''\
"""Hello World Orchestra workflow."""

import asyncio
from orchestra.core.graph import WorkflowGraph
from orchestra.core.state import WorkflowState


class HelloState(WorkflowState):
    greeting: str = ""


async def greet(state: dict) -> dict:
    return {"greeting": "Hello from Orchestra!"}


async def main():
    graph = WorkflowGraph(state_schema=HelloState)
    graph.add_node("greeter", greet)
    graph.set_entry_point("greeter")

    compiled = graph.compile()
    result = await compiled.run({})
    print(result["greeting"])


if __name__ == "__main__":
    asyncio.run(main())
''',
        encoding="utf-8",
    )

    console.print(f"[green]Created project:[/green] {project_dir}")
    console.print("  agents/")
    console.print("  tools/")
    console.print("  workflows/hello.py")
    console.print(f"\nRun: [bold]cd {project_name} && python workflows/hello.py[/bold]")


@app.command()
def run(
    workflow_file: str = typer.Argument(..., help="Path to workflow Python file"),
) -> None:
    """Run a workflow file."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("workflow", workflow_file)
    if spec is None or spec.loader is None:
        console.print(f"[red]Error:[/red] Cannot load {workflow_file}")
        raise typer.Exit(1)

    module = importlib.util.module_from_spec(spec)
    sys.modules["workflow"] = module
    spec.loader.exec_module(module)

    if hasattr(module, "main"):
        import asyncio

        asyncio.run(module.main())
    else:
        console.print(f"[red]Error:[/red] {workflow_file} has no main() function")
        raise typer.Exit(1)


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Run ID of the interrupted workflow to resume"),
    set_state: list[str] = typer.Option(
        [], "--set", "-s",
        help="State overrides as key=value pairs (e.g. --set approved=true)",
    ),
) -> None:
    """Resume an interrupted workflow from its latest checkpoint."""
    import asyncio
    import json

    # Parse key=value overrides
    state_updates: dict[str, object] = {}
    for item in set_state:
        if "=" not in item:
            console.print(f"[red]Error:[/red] Invalid --set format: {item!r} (expected key=value)")
            raise typer.Exit(1)
        key, _, raw_value = item.partition("=")
        # Try JSON decode so booleans/numbers work; fall back to string
        try:
            state_updates[key.strip()] = json.loads(raw_value)
        except json.JSONDecodeError:
            state_updates[key.strip()] = raw_value

    async def _resume() -> None:
        from orchestra.core.graph import WorkflowGraph
        from orchestra.core.compiled import CompiledGraph

        # Build a minimal CompiledGraph with no nodes -- resume() only needs the store
        graph = WorkflowGraph()
        compiled = graph.compile()

        try:
            final_state = await compiled.resume(
                run_id,
                state_updates=state_updates or None,
            )
            console.print(f"[green]Resumed run:[/green] {run_id}")
            console.print(f"Final state: {final_state}")
        except Exception as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1)

    asyncio.run(_resume())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
) -> None:
    """Start the Orchestra HTTP server."""
    try:
        import uvicorn

        from orchestra.server.app import create_app
        from orchestra.server.config import ServerConfig
    except ImportError:
        console.print("[red]Error:[/red] Server dependencies not installed.")
        console.print("Install with: pip install orchestra-agents[server]")
        raise typer.Exit(1)

    config = ServerConfig(host=host, port=port)
    app_instance = create_app(config)
    console.print(f"[green]Starting Orchestra server on {host}:{port}[/green]")
    uvicorn.run(app_instance, host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
