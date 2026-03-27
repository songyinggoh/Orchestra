# Contributing to Orchestra

Thank you for your interest in contributing to Orchestra! This document provides guidelines for contributing.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/songyinggoh/Orchestra.git
cd orchestra

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run unit tests (recommended for quick local validation)
pytest tests/unit/ -x -q

# Run unit tests with coverage
pytest tests/unit/ --cov=orchestra --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_state.py -v
```

> **Note:** Running `pytest tests/` without a subdirectory will execute ALL tests
> including integration, live, and load tests, which require external services
> (Postgres, Redis, NATS, Ollama, etc.). Use `pytest tests/unit/` for quick local
> validation. Also note that `[dev]` extras do not include `locust` or `hypothesis`;
> those are in `[test-advanced]`.

## Code Quality

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/orchestra/
```

## Pull Request Process

1. Fork the repository and create a feature branch from `master`
2. Write tests for new functionality
3. Ensure all tests pass and coverage remains above 75%
4. Ensure `ruff check` and `mypy` pass with no errors
5. Submit a pull request with a clear description of the changes

## Code Style

- Follow PEP 8 with a line length of 100 characters
- Use type annotations for all public functions
- Use `async/await` for all I/O operations
- Prefer Protocol classes over ABC for interfaces

## Reporting Issues

- Use GitHub Issues to report bugs
- Include a minimal reproducible example
- Include Python version and OS information

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
