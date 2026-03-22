"""Smoke tests to verify the project scaffolding works."""

from __future__ import annotations


def test_import_orchestra() -> None:
    """Verify the orchestra package is importable."""
    import orchestra

    assert hasattr(orchestra, "__version__")
    assert orchestra.__version__ == "0.1.0"


def test_py_typed_marker_exists() -> None:
    """Verify PEP 561 py.typed marker exists."""
    from pathlib import Path

    import orchestra

    package_dir = Path(orchestra.__file__).parent
    assert (package_dir / "py.typed").exists()


def test_subpackages_importable() -> None:
    """Verify all subpackages are importable."""
    import orchestra.cli
    import orchestra.core
    import orchestra.discovery
    import orchestra.observability
    import orchestra.providers
    import orchestra.testing
    import orchestra.tools  # noqa: F401
