# Load Testing

This directory contains scripts for load testing the Orchestra FastAPI server using [Locust](https://locust.io/).

## Prerequisites

- Install Locust: `pip install locust`
- Make sure the server dependencies are installed in your environment: `pip install -e ".[server]"`

## Running the Test

1.  **Start the FastAPI Server:**
    From the project root, start the server with the `--factory` flag (required because `create_app` is a factory function, not a bare ASGI app):

    ```sh
    orchestra serve
    ```

    Or, using uvicorn directly:

    ```sh
    uvicorn orchestra.server.app:create_app --factory
    ```

    > **Note — Authentication:** The `/api/v1/runs` endpoint requires an API key when `ORCHESTRA_API_KEY` is set in the environment. For local load testing, either leave `ORCHESTRA_API_KEY` unset, or add an `Authorization: Bearer <key>` header in the locustfile before running against an authenticated server.

    > **Note — Graph registration:** The app factory starts with an **empty** `GraphRegistry` — no test graphs are pre-registered. Requests for unregistered graphs will return 404. You must register any graphs your locustfile targets (e.g. `test-graph`) by extending `create_app` or by POSTing graph definitions before the test begins.

2.  **Run Locust:**
    Once the server is running, open a new terminal and run Locust.

    ```sh
    locust -f load_tests/locustfile.py --host http://127.0.0.1:8000
    ```

3.  **Start the Load Test:**
    Open your web browser to `http://localhost:8089` (the Locust web UI). Enter the number of users to simulate and the spawn rate, then start the test.

## Test Scenarios

- `locustfile.py`: A simple test that repeatedly calls the `POST /api/v1/runs` endpoint for a basic graph. This is useful for testing the baseline overhead of the run creation and execution process.

> **Note:** `tests/load/locustfile.py` is a more complete alternative with multiple
> task types (health checks, run creation, SSE streaming, etc.).
