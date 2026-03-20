"""Validation and error reporting for discovered projects.

Provides ``validate_project()`` for the ``orchestra validate`` CLI command,
including did-you-mean suggestions via Levenshtein edit distance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from orchestra.discovery.scanner import ProjectScanner, ScanResult

logger = structlog.get_logger(__name__)


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(b)]


def did_you_mean(name: str, candidates: list[str], max_distance: int = 3) -> str | None:
    """Find the closest candidate to *name* within *max_distance*.

    Returns the suggestion string or None if nothing is close enough.
    """
    if not candidates:
        return None
    best = min(candidates, key=lambda c: _edit_distance(name, c))
    if _edit_distance(name, best) <= max_distance:
        return best
    return None


def validate_project(project_dir: Path) -> ScanResult:
    """Run a full discovery scan and return the result.

    This is the backend for ``orchestra validate``. The CLI command
    formats the result for terminal output.
    """
    scanner = ProjectScanner()
    return scanner.scan(project_dir)


def format_validation_report(result: ScanResult) -> str:
    """Format a ScanResult into a human-readable report string."""
    lines: list[str] = []

    lines.append("Discovery Report")
    lines.append("=" * 40)

    # Tools
    lines.append(f"\nTools ({len(result.tools)}):")
    if result.tools:
        for name, tool in sorted(result.tools.items()):
            desc = tool.description[:60] if tool.description else "(no description)"
            lines.append(f"  - {name}: {desc}")
    else:
        lines.append("  (none)")

    # Agents
    lines.append(f"\nAgents ({len(result.agents)}):")
    if result.agents:
        for name, agent in sorted(result.agents.items()):
            tool_names = [t.name for t in agent.tools]
            tools_str = f" [tools: {', '.join(tool_names)}]" if tool_names else ""
            lines.append(f"  - {name} (model={agent.model}){tools_str}")
    else:
        lines.append("  (none)")

    # Workflows
    lines.append(f"\nWorkflows ({len(result.workflows)}):")
    if result.workflows:
        for name in sorted(result.workflows.keys()):
            lines.append(f"  - {name}")
    else:
        lines.append("  (none)")

    # Warnings
    if result.warnings:
        lines.append(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            lines.append(f"  ! {w}")

    # Errors
    if result.errors:
        lines.append(f"\nErrors ({len(result.errors)}):")
        for e in result.errors:
            lines.append(f"  X {e}")

    # Summary
    lines.append("")
    if result.errors:
        lines.append(f"FAILED: {len(result.errors)} error(s) found.")
    else:
        lines.append("OK: No errors found.")

    return "\n".join(lines)
