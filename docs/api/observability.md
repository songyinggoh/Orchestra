# Observability API Reference

Orchestra uses [structlog](https://www.structlog.org/) for structured logging with two output modes.

## setup_logging

::: orchestra.observability.logging.setup_logging
    options:
      show_source: false
      heading_level: 3

### Usage

```python
from orchestra.observability.logging import setup_logging

# Development: colored console output
setup_logging(level="DEBUG")

# Production: JSON lines
setup_logging(level="INFO", json_output=True)
```

## get_logger

::: orchestra.observability.logging.get_logger
    options:
      show_source: false
      heading_level: 3

### Usage

```python
from orchestra.observability.logging import get_logger

logger = get_logger(__name__)
logger.info("workflow_started", workflow_id="abc123", node="researcher")
```

## Output Formats

### Console (Development)

```
2026-03-07 12:00:00 [info] workflow_started   workflow_id=abc123 node=researcher
2026-03-07 12:00:01 [info] executing_node     node=researcher turn=1
2026-03-07 12:00:02 [info] executing_node     node=writer turn=2
```

### JSON (Production)

```json
{"event": "workflow_started", "workflow_id": "abc123", "node": "researcher", "timestamp": "2026-03-07T12:00:00Z", "level": "info"}
```
