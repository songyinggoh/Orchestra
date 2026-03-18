"""Orchestra HTTP server with SSE streaming.

This module provides a FastAPI-based server for running and monitoring
multi-agent workflows over HTTP. Server dependencies are optional and
must be installed separately::

    pip install orchestra-agents[server]
"""

from __future__ import annotations

try:
    from orchestra.server.app import create_app
    from orchestra.server.config import ServerConfig

    __all__ = ["ServerConfig", "create_app"]
except ImportError:
    # Server dependencies not installed — module is importable but
    # create_app / ServerConfig won't be available.
    __all__ = []
