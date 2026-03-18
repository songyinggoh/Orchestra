"""Locust load test for the Orchestra FastAPI server.

Run headless against a live server:
    locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 30s --host http://localhost:8000

The server must be started separately before running:
    orchestra serve  (or)  uvicorn orchestra.server.app:app --factory
"""

from __future__ import annotations

from locust import HttpUser, between, task


class OrchestraUser(HttpUser):
    """Simulated Orchestra API user exercising the three main endpoint groups."""

    wait_time = between(1, 3)
    host = "http://localhost:8000"

    @task(3)
    def create_run(self) -> None:
        """Create a new workflow run."""
        self.client.post(
            "/api/v1/runs",
            json={"graph_name": "echo", "input": {"query": "hello"}},
            catch_response=True,
        )

    @task(5)
    def check_health(self) -> None:
        """Check server health — lightweight probe, high frequency."""
        self.client.get("/healthz")

    @task(2)
    def list_graphs(self) -> None:
        """List available graphs."""
        self.client.get("/api/v1/graphs")
