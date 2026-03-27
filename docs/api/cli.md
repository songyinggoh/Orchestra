# CLI API Reference

Orchestra includes a CLI built with Typer. It is installed as the `orchestra` console script.

## Commands

### `orchestra version`

Print the installed Orchestra version.

```bash
$ orchestra version
Orchestra v0.1.0
```

### `orchestra run <workflow_file>`

Execute a workflow from a Python file.

```bash
$ orchestra run examples/sequential.py
```

The command:

1. Loads the Python file as a module
2. Looks for a `main()` async function
3. Executes it with structured logging enabled
4. Prints the workflow results

### `orchestra init <project_name>`

Scaffold a new Orchestra project with convention-based structure.

```bash
$ orchestra init my_project
```

**Options:**

| Option | Description |
|--------|-------------|
| `--directory` | Directory to create project in (default: `.`) |

Creates a directory with:
- `orchestra.yaml` — Project configuration
- `.env` — Environment variable template
- `agents/` — YAML agent definitions (includes an example `assistant.yaml`)
- `tools/` — Python tool files (includes an example `greet.py`)
- `workflows/` — YAML workflow graphs (includes an example `hello.yaml`)
- `lib/` — Shared library code

### `orchestra resume <run_id>`

Resume an interrupted workflow from its latest checkpoint.

```bash
$ orchestra resume abc123
$ orchestra resume abc123 --set approved=true --set score=0.9
```

**Options:**

| Option | Description |
|--------|-------------|
| `--set`, `-s` | State overrides as key=value pairs (can be repeated) |

### `orchestra serve`

Start the Orchestra HTTP server.

```bash
$ orchestra serve --host 0.0.0.0 --port 8000
```

**Options:**

| Option | Description |
|--------|-------------|
| `--host` | Host to bind to (default: `0.0.0.0`) |
| `--port` | Port to bind to (default: `8000`) |
| `--reload` | Enable auto-reload (default: off) |

### `orchestra up`

Auto-discover agents, tools, and workflows from the project directory, then start the server.

```bash
$ orchestra up
$ orchestra up --dir ./my_project --port 9000
```

Scans the project directory for convention-based definitions:
- `tools/` — Python files with `@tool` functions
- `agents/` — YAML agent definitions
- `workflows/` — YAML workflow graphs

Registers all discovered workflows and starts the HTTP server.

**Options:**

| Option | Description |
|--------|-------------|
| `--host` | Host to bind to (default: `0.0.0.0`) |
| `--port` | Port to bind to (default: `8000`) |
| `--reload` | Enable YAML hot-reload (default: off) |
| `--dir` | Project directory to scan (default: `.`) |

### `orchestra validate`

Validate a project without starting the server. Discovers all tools, agents, and workflows, checks cross-references, and reports any errors. Exits non-zero if problems are found.

```bash
$ orchestra validate
$ orchestra validate --dir ./my_project
```

**Options:**

| Option | Description |
|--------|-------------|
| `--dir` | Project directory to validate (default: `.`) |

## Module Reference

::: orchestra.cli.main
    options:
      show_source: false
      heading_level: 3
      members:
        - version
        - init
        - run
        - resume
        - serve
        - up
        - validate
