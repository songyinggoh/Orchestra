"""Locust load test for the Orchestra FastAPI server.

To run this test:
1. Start the FastAPI server: `poetry run uvicorn orchestra.server.app:create_app`
2. Run Locust: `locust -f load_tests/locustfile.py --host http://127.0.0.1:8000`
"""

from locust import HttpUser, task, between

class OrchestraUser(HttpUser):
    wait_time = between(1, 5)

    @task
    def create_simple_run(self):
        """Simulate creating a run of the test-graph."""
        self.client.post(
            "/api/v1/runs",
            json={"graph_name": "test-graph", "input": {"input": "from-locust"}},
            name="/api/v1/runs [test-graph]",
        )

    def on_start(self):
        """Register the test graph before starting the test.
        
        This is a workaround for a test setup. In a real deployment,
        the graphs would be pre-registered. We can't easily do this
        from locust, so we assume the 'test-graph' is available.
        If not, this will result in 404s.
        """
        pass
