"""Fixture: private helper file — should be skipped by tool discovery."""


def _internal_helper(value: str) -> str:
    """This function is NOT a tool and this file should be skipped."""
    return value.strip()
