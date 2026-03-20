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
    """Initialize a new Orchestra project with convention-based structure.

    Creates a ready-to-run project with example agent, tool, workflow,
    and orchestra.yaml configuration. Run ``orchestra up`` to start.
    """
    from pathlib import Path

    project_dir = Path(directory) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / "agents").mkdir(exist_ok=True)
    (project_dir / "tools").mkdir(exist_ok=True)
    (project_dir / "workflows").mkdir(exist_ok=True)
    (project_dir / "lib").mkdir(exist_ok=True)

    # orchestra.yaml
    (project_dir / "orchestra.yaml").write_text(
        f"""\
# Orchestra project configuration
project:
  name: {project_name}

defaults:
  model: claude-sonnet-4-20250514
  temperature: 0.7
  max_iterations: 10

server:
  host: 0.0.0.0
  port: 8000
""",
        encoding="utf-8",
    )

    # .env template
    (project_dir / ".env").write_text(
        """\
# Add your API key here
# ANTHROPIC_API_KEY=sk-ant-...
""",
        encoding="utf-8",
    )

    # Example agent
    (project_dir / "agents" / "assistant.yaml").write_text(
        """\
name: assistant
system_prompt: |
  You are a helpful assistant. Answer questions clearly and concisely.
tools:
  - greet
temperature: 0.7
max_iterations: 5
""",
        encoding="utf-8",
    )

    # Example tool
    (project_dir / "tools" / "greet.py").write_text(
        '''\
"""Example tool for the Orchestra project."""

from orchestra.tools.base import tool


@tool
async def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}! Welcome to Orchestra."
''',
        encoding="utf-8",
    )

    # Example workflow
    (project_dir / "workflows" / "hello.yaml").write_text(
        """\
name: hello
state:
  input: str
  output: str
nodes:
  assistant:
    type: agent
    ref: assistant
    output_key: output
edges:
  - source: assistant
    target: __end__
entry_point: assistant
""",
        encoding="utf-8",
    )

    console.print(f"[green]Created project:[/green] {project_dir}")
    console.print("  orchestra.yaml")
    console.print("  .env")
    console.print("  agents/assistant.yaml")
    console.print("  tools/greet.py")
    console.print("  workflows/hello.yaml")
    console.print("  lib/")
    console.print(f"\nRun: [bold]cd {project_name} && orchestra up[/bold]")


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


@app.command()
def up(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(False, help="Enable YAML hot-reload"),
    project_dir: str = typer.Option(".", "--dir", help="Project directory to scan"),
) -> None:
    """Auto-discover agents, tools, and workflows, then start the server.

    Scans the project directory for convention-based definitions:
    - tools/     Python files with @tool functions
    - agents/    YAML agent definitions
    - workflows/ YAML workflow graphs

    Registers all discovered workflows and starts the HTTP server.
    """
    from pathlib import Path

    try:
        import uvicorn

        from orchestra.server.app import create_app
        from orchestra.server.config import ServerConfig
        from orchestra.server.lifecycle import GraphRegistry
    except ImportError:
        console.print("[red]Error:[/red] Server dependencies not installed.")
        console.print("Install with: pip install orchestra-agents[server]")
        raise typer.Exit(1)

    from orchestra.discovery.scanner import ProjectScanner

    root = Path(project_dir).resolve()
    console.print(f"[bold]Scanning project:[/bold] {root}")

    scanner = ProjectScanner()
    result = scanner.scan(root)

    # Report discoveries
    console.print(f"  Tools:     {len(result.tools)}")
    console.print(f"  Agents:    {len(result.agents)}")
    console.print(f"  Workflows: {len(result.workflows)}")

    # Report warnings
    for warning in result.warnings:
        console.print(f"  [yellow]Warning:[/yellow] {warning}")

    # Report errors and exit if any
    if result.errors:
        for error in result.errors:
            console.print(f"  [red]Error:[/red] {error}")
        console.print(f"\n[red]{len(result.errors)} error(s) found. Fix them and try again.[/red]")
        raise typer.Exit(1)

    # Use config from orchestra.yaml for server settings
    srv = result.config.server
    effective_host = host if host != "0.0.0.0" else srv.host
    effective_port = port if port != 8000 else srv.port

    # Create app and pre-register discovered workflows
    server_config = ServerConfig(
        host=effective_host,
        port=effective_port,
        cors_origins=srv.cors_origins,
    )
    app_instance = create_app(server_config)

    # Store scan result on app state so the lifespan can register graphs
    app_instance.state.discovery_result = result

    # Register workflows into a GraphRegistry attached to app state
    # The lifespan creates its own registry; we register after creation
    # by hooking into the startup. Since create_app uses a lifespan,
    # we register directly before uvicorn starts.
    _original_graph_registry = GraphRegistry()
    for wf_name, compiled in result.workflows.items():
        _original_graph_registry.register(wf_name, compiled)
        console.print(f"  [green]Registered workflow:[/green] {wf_name}")

    app_instance.state._discovery_registry = _original_graph_registry

    console.print(
        f"\n[green]Starting Orchestra server on {effective_host}:{effective_port}[/green]"
    )
    uvicorn.run(app_instance, host=effective_host, port=effective_port, reload=False)


@app.command()
def validate(
    project_dir: str = typer.Option(".", "--dir", help="Project directory to validate"),
) -> None:
    """Validate a project without starting the server.

    Discovers all tools, agents, and workflows, checks cross-references,
    and reports any errors. Exits non-zero if problems are found.
    """
    from pathlib import Path
    from orchestra.discovery.validation import validate_project, format_validation_report

    root = Path(project_dir).resolve()
    result = validate_project(root)
    report = format_validation_report(result)
    console.print(report)

    if result.errors:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
