# CLI API Reference

Orchestra includes a CLI built with Typer. It is installed as the `orchestra` console script.

## Commands

### `orchestra version`

Print the installed Orchestra version.

```bash
$ orchestra version
orchestra 0.1.0
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

**Options:**

| Option | Description |
|--------|-------------|
| `--log-level` | Set log level (DEBUG, INFO, WARNING, ERROR) |
| `--log-format` | Output format: `console` (default) or `json` |

### `orchestra init <project_name>`

Scaffold a new Orchestra project with starter files.

```bash
$ orchestra init my_project
```

Creates a directory with:
- `pyproject.toml` — Package configuration
- Sample agent and workflow files
- Test file with ScriptedLLM example

## Module Reference

::: orchestra.cli.main
    options:
      show_source: false
      heading_level: 3
      members:
        - version
        - init
        - run
